"""文件上传接口模块"""

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, Field

from app.enterprise.adapters.upload_adapter import UploadAdapter
from app.enterprise.auth.dependencies import CurrentUser
from app.enterprise.context import get_current_request_context
from app.enterprise.documents import document_access_service
from app.enterprise.gateway.request_gateway import RequestBlocked
from app.models import DocumentStatus
from app.services.document_health_check_service import (
    DocumentHealthCheckResult,
    DocumentHealthStatus,
    document_health_check_store,
)
from app.services.document_ingestion_service import DocumentIngestionService
from app.services.document_processing_queue import document_processing_queue
from app.services.document_processing_workflow import document_processing_workflow
from app.services.knowledge_metadata_store import knowledge_metadata_store

router = APIRouter()

# 文件上传后存储的路径
UPLOAD_DIR = Path("./uploads")
# 单个文件支持最大大小
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
document_ingestion_service = DocumentIngestionService(upload_root=UPLOAD_DIR)
upload_adapter = UploadAdapter(
    document_ingestion_service,
    max_file_size=MAX_FILE_SIZE,
)


class DocumentStatusBatchRequest(BaseModel):
    doc_ids: list[str] = Field(..., min_length=1, max_length=100)


class DocumentHealthFalsePositiveRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


@router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    kb_id: str = Form(...),
):
    """
    上传文件并自动创建向量索引

    Args:
        file: 上传的文件
        kb_id: 目标知识库 id (required, per §10(b) 2026-05-20 decision —
            production callers must declare the target KB explicitly;
            no implicit "default" fallback at this boundary)

    Returns:
        JSONResponse: 上传结果
    """
    try:
        response_data = await upload_adapter.upload(file, kb_id, request.headers)
        logger.info(
            "文件上传成功并进入正式接入链路: doc_id={}, status={}, path={}",
            response_data["doc_id"],
            response_data["status"],
            response_data["file_path"],
        )

        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "message": "success",
                "data": response_data,
            },
        )

    except RequestBlocked as exc:
        return JSONResponse(
            status_code=403,
            content={
                "code": 403,
                "message": "blocked",
                "data": {
                    "reason": exc.reason,
                    "trace_id": exc.trace_id,
                },
            },
        )
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"文件上传请求无效: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        raise HTTPException(status_code=500, detail=f"文件上传失败: {e}") from e


@router.get("/documents")
async def list_documents(
    _current_user: CurrentUser,
    kb_id: str | None = None,
    status: str | None = None,
    page: int = 1,
    limit: int = 20,
    offset: int | None = None,
):
    """List current-user visible documents for the file-management console."""
    context = get_current_request_context()
    if context is None:
        raise HTTPException(status_code=500, detail="RequestContext is missing")

    document_processing_workflow.reconcile_stale_processing()
    status_filter = None
    if status:
        try:
            status_filter = DocumentStatus(status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Unsupported document status: {status}") from exc

    documents = document_access_service.list_visible_documents(
        context,
        kb_id=kb_id,
        status=status_filter,
    )
    safe_limit = max(min(limit, 100), 1)
    if offset is None:
        safe_page = max(page, 1)
        safe_offset = (safe_page - 1) * safe_limit
    else:
        safe_offset = max(offset, 0)
        safe_page = (safe_offset // safe_limit) + 1
    page = documents[safe_offset : safe_offset + safe_limit]

    return JSONResponse(
        status_code=200,
        content={
            "code": 200,
            "message": "success",
            "data": {
                "documents": [_document_payload(document) for document in page],
                "total": len(documents),
                "page": safe_page,
                "limit": safe_limit,
                "offset": safe_offset,
                "has_next": safe_offset + safe_limit < len(documents),
                "kb_ids": sorted({document.kb_id for document in documents if document.kb_id}),
            },
        },
    )


@router.get("/documents/{doc_id}")
async def get_document_status(doc_id: str):
    """查询异步文档处理状态。"""
    document_processing_workflow.reconcile_stale_processing()
    document_record = knowledge_metadata_store.get_document(doc_id)
    if document_record is None:
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")

    return JSONResponse(
        status_code=200,
        content={
            "code": 200,
            "message": "success",
            "data": document_processing_workflow.document_status_payload(document_record),
        },
    )


@router.get("/documents/{doc_id}/health")
async def get_document_health(doc_id: str, _current_user: CurrentUser):
    """Return deterministic post-index health diagnostics for a visible document."""
    document_processing_workflow.reconcile_stale_processing()
    document_record = _visible_document_or_404(doc_id)
    return JSONResponse(
        status_code=200,
        content={
            "code": 200,
            "message": "success",
            "data": _document_health_detail_payload(document_record),
        },
    )


@router.post("/documents/{doc_id}/health/mark-false-positive")
async def mark_document_health_false_positive(
    doc_id: str,
    request: DocumentHealthFalsePositiveRequest,
    _current_user: CurrentUser,
):
    """Mark a diagnostic result as false positive without changing document status."""
    document_processing_workflow.reconcile_stale_processing()
    _visible_document_or_404(doc_id)
    reason = request.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="reason 不能为空")
    result = document_health_check_store.mark_false_positive(doc_id, reason)
    return JSONResponse(
        status_code=200,
        content={
            "code": 200,
            "message": "success",
            "data": result.model_dump(mode="json"),
        },
    )


@router.post("/documents/status-batch")
async def get_document_status_batch(request: DocumentStatusBatchRequest):
    """Batch query document processing statuses after stale reconciliation."""
    return JSONResponse(
        status_code=200,
        content={
            "code": 200,
            "message": "success",
            "data": document_processing_workflow.status_batch(request.doc_ids),
        },
    )


@router.post("/index_directory")
async def index_directory(
    directory_path: str = Form(None),
    kb_id: str = Form(...),
):
    """
    索引指定目录下的所有文件

    Args:
        directory_path: 目录路径（可选，默认使用 uploads 目录）
        kb_id: 目标知识库 id

    Returns:
        JSONResponse: 批量索引任务引用
    """
    try:
        target_path = directory_path or str(UPLOAD_DIR)
        logger.info(f"投递目录批量索引任务: {target_path}, kb_id={kb_id}")

        job_ref = document_processing_queue.enqueue_directory_index_batch(
            target_path,
            kb_id=kb_id,
        )

        return JSONResponse(
            status_code=200,
            content={
                "code": 200,
                "message": "accepted",
                "data": {
                    "async_processing": True,
                    "batch_job_id": job_ref.job_id,
                    "processing_queue": job_ref.queue_name,
                    "directory_path": job_ref.directory_path,
                    "kb_id": job_ref.kb_id,
                },
            },
        )

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"目录批量索引请求无效: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"目录批量索引任务投递失败: {e}")
        raise HTTPException(status_code=500, detail=f"目录批量索引任务投递失败: {e}") from e


def _document_payload(document) -> dict:
    confirmed_at = document.status_confirmed_at
    created_at = document.created_at.isoformat() if document.created_at else None
    updated_at = document.updated_at.isoformat() if document.updated_at else None
    return {
        "id": document.doc_id,
        "doc_id": document.doc_id,
        "kb_id": document.kb_id,
        "filename": document.file_name,
        "file_name": document.file_name,
        "status": document.status.value,
        "status_detail": document.status_detail,
        "parser_engine": document.parser_engine.value,
        "created_at": created_at,
        "uploaded_at": created_at,
        "updated_at": updated_at,
        "status_confirmed_at": confirmed_at.isoformat() if confirmed_at else None,
        "error_message": document.error_message,
        "trace_id": _document_trace_id(document),
        "health_check": document_health_check_store.summary_for_document(document),
    }


def _visible_document_or_404(doc_id: str):
    context = get_current_request_context()
    if context is None:
        raise HTTPException(status_code=500, detail="RequestContext is missing")
    document_record = document_access_service.metadata_store.get_document(doc_id)
    if document_record is None or not document_access_service.can_read_document(context, document_record):
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    return document_record


def _document_health_detail_payload(document) -> dict:
    result = document_health_check_store.get(document.doc_id)
    if result is None:
        result = DocumentHealthCheckResult(
            doc_id=document.doc_id,
            kb_id=document.kb_id,
            status=(
                DocumentHealthStatus.PENDING
                if document.status == DocumentStatus.INDEXED
                else DocumentHealthStatus.SKIPPED
            ),
            summary=(
                "health_check_pending"
                if document.status == DocumentStatus.INDEXED
                else "waiting_for_indexed_status"
            ),
            retrieval={"passed": False, "queries": []},
            source_ref={"passed": False, "errors": []},
            pdf={"passed": False, "errors": []},
        )
    return result.model_dump(mode="json")


def _document_trace_id(document) -> str | None:
    evidence = document.status_evidence or {}
    if isinstance(evidence, dict):
        for key in ("trace_id", "request_trace_id"):
            value = evidence.get(key)
            if value:
                return str(value)

    metadata = document.metadata or {}
    if isinstance(metadata, dict):
        for key in ("trace_id", "request_trace_id"):
            value = metadata.get(key)
            if value:
                return str(value)
    return None
