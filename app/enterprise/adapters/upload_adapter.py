"""Thin upload adapter for E2 RequestGateway."""

from fastapi import HTTPException, UploadFile

from app.enterprise.context import RequestContext
from app.enterprise.gateway.models import GatewayRequest
from app.enterprise.gateway.request_gateway import RequestGateway, request_gateway
from app.enterprise.observability.models import AuditEvent
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.service import (
    PermissionService,
    permission_service as default_permission_service,
)


class UploadAdapter:
    def __init__(
        self,
        ingestion_service,
        *,
        max_file_size: int,
        gateway: RequestGateway | None = None,
        permission_service: PermissionService | None = None,
    ):
        self.ingestion_service = ingestion_service
        self.max_file_size = max_file_size
        self.gateway = gateway or request_gateway
        self.permission_service = permission_service or default_permission_service

    async def upload(self, file: UploadFile, kb_id: str, headers) -> dict:
        gateway_request = GatewayRequest.from_headers(
            route="upload",
            payload={"filename": file.filename, "kb_id": kb_id},
            headers=headers,
        )

        async def handler(context):
            if not file.filename:
                raise HTTPException(status_code=400, detail="文件名不能为空")

            content = await file.read()
            if len(content) > self.max_file_size:
                raise HTTPException(
                    status_code=400,
                    detail=f"文件大小超过限制（最大 {self.max_file_size} 字节）",
                )

            document_record = self.ingestion_service.ingest_upload(
                filename=file.filename,
                content=content,
                kb_id=kb_id,
            )
            status_evidence = document_record.status_evidence or {}
            processing_job_id = status_evidence.get("processing_job_id")
            processing_queue = status_evidence.get("processing_queue")
            storage_uri = status_evidence.get(
                "storage_uri",
                document_record.metadata.get("storage_uri", ""),
            )
            uploader_grant = self._ensure_uploader_read_grant(
                context,
                doc_id=document_record.doc_id,
            )

            self.gateway.audit_service.record(
                AuditEvent(
                    event_type="upload_saved",
                    route="upload",
                    trace_id=context.trace_id,
                    request_id=context.request_id,
                    user_id=context.user_id,
                    decision="allowed",
                    metadata={
                        "department_id": context.department_id,
                        "department_name": context.department_name,
                        "kb_id": document_record.kb_id,
                        "doc_id": document_record.doc_id,
                        "storage_uri": storage_uri,
                        "parser_engine": document_record.parser_engine.value,
                        "uploader_read_grant_id": uploader_grant.grant_id,
                    },
                )
            )

            response_data = {
                "filename": document_record.file_name,
                "file_path": document_record.original_path,
                "storage_uri": storage_uri,
                "size": len(content),
                "doc_id": document_record.doc_id,
                "parser_engine": document_record.parser_engine.value,
                "status": document_record.status.value,
                "artifact_dir": document_record.artifact_dir,
                "async_processing": processing_job_id is not None,
                "trace_id": context.trace_id,
            }
            if processing_job_id is not None:
                response_data["processing_job_id"] = processing_job_id
                response_data["processing_queue"] = processing_queue

            return response_data

        return await self.gateway.execute(gateway_request, handler)

    def _ensure_uploader_read_grant(
        self,
        context: RequestContext,
        *,
        doc_id: str,
    ) -> ResourceGrant:
        existing = self.permission_service.repository.list_all_grants(
            resource_type="document",
            resource_id=doc_id,
            action="read",
            principal_type=PrincipalType.USER,
            principal_id=context.user_id,
        )
        for grant in existing:
            if grant.effect == GrantEffect.ALLOW:
                return grant

        return self.permission_service.grant_access(
            ResourceGrant(
                resource_type="document",
                resource_id=doc_id,
                action="read",
                principal_type=PrincipalType.USER,
                principal_id=context.user_id,
                effect=GrantEffect.ALLOW,
                reason="document_uploader_auto_read",
            )
        )
