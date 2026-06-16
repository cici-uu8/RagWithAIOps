"""HTTP routes for explicit database-demo access."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.config import config
from app.enterprise.admin.models import success_payload
from app.enterprise.auth.dependencies import CurrentUser
from app.enterprise.context import RequestContext, get_current_request_context
from app.enterprise.database.confirmations import (
    DatabaseOperationConfirmationDenied,
    DatabaseOperationConfirmationStatus,
    DatabaseOperationDirectExecuteDenied,
    DatabaseOperationDirectExecuteService,
    DatabaseOperationDirectExecutor,
    DatabaseOperationExecutor,
    DatabaseOperationPrepareDenied,
    DatabaseOperationPrepareService,
    SQLiteDatabaseOperationConfirmationRepository,
    SQLiteDatabaseOperationExecutor,
)
from app.enterprise.database.mysql import (
    build_mysql_operation_executor_from_config,
    build_mysql_provider_from_config,
)
from app.enterprise.database.provider import DatabaseDemoToolProvider
from app.enterprise.database.registry import DatabaseSchemaRegistry, build_default_sandbox_registry
from app.enterprise.database.safe_sql import DatabaseExecutionError, SafeSqlBlocked, SafeSqlKernel
from app.enterprise.database.sandbox import ensure_sandbox_database
from app.enterprise.database.service import DatabaseCapabilityCatalogService
from app.enterprise.gateway.models import GatewayRequest
from app.enterprise.gateway.request_gateway import request_gateway
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.permissions.service import (
    PermissionService,
    permission_service as global_permission_service,
)
from app.enterprise.tools.gateway import ToolAccessDenied, ToolExecutionError, ToolGateway

router = APIRouter(prefix="/database", tags=["数据库"])
gateway = request_gateway

SANDBOX_DATABASE_PATH = Path("logs/database_demo.sqlite3")


class SafeSelectRequest(BaseModel):
    database_id: str = Field(default="sandbox_sales", min_length=1)
    sql: str = Field(min_length=1)


class DatabaseOperationPrepareRequest(BaseModel):
    database_id: str = Field(default="sandbox_sales", min_length=1)
    sql: str = Field(min_length=1)
    reason: str | None = None


class DatabaseOperationExecuteRequest(BaseModel):
    database_id: str = Field(default="sandbox_sales", min_length=1)
    sql: str = Field(min_length=1)


def build_database_tool_gateway(database_path: str | Path = SANDBOX_DATABASE_PATH) -> ToolGateway:
    registry = build_default_sandbox_registry()
    db_path = Path(database_path)
    ensure_sandbox_database(db_path, registry)
    kernel = SafeSqlKernel(database_path=db_path, registry=registry)
    provider = DatabaseDemoToolProvider(
        registry=registry,
        kernel=kernel,
        permission_service=global_permission_service,
    )
    providers = [provider]
    mysql_provider = build_mysql_provider_from_config(
        app_config=config,
        permission_service=global_permission_service,
        audit_service=kernel.audit_service,
    )
    if mysql_provider is not None:
        providers.append(mysql_provider)
    return ToolGateway(
        providers=providers,
        permission_service=global_permission_service,
        audit_service=kernel.audit_service,
    )


database_tool_gateway: ToolGateway | None = None
database_operation_prepare_service: DatabaseOperationPrepareService | None = None
database_operation_direct_execute_service: DatabaseOperationDirectExecuteService | None = None


def get_database_tool_gateway() -> ToolGateway:
    global database_tool_gateway
    if database_tool_gateway is None:
        database_tool_gateway = build_database_tool_gateway()
    return database_tool_gateway


def build_database_operation_prepare_service(
    *,
    database_path: str | Path = SANDBOX_DATABASE_PATH,
    confirmation_path: str | Path | None = None,
    registry: DatabaseSchemaRegistry | None = None,
    permission_service: PermissionService | None = None,
    audit_service: AuditService | None = None,
    dialect: str = "sqlite",
    operation_executor: DatabaseOperationExecutor | None = None,
) -> DatabaseOperationPrepareService:
    registry = registry or build_default_sandbox_registry()
    permission_service = permission_service or global_permission_service
    db_path = Path(database_path)
    if dialect == "sqlite":
        ensure_sandbox_database(db_path, registry)
    repository = SQLiteDatabaseOperationConfirmationRepository(confirmation_path)
    if audit_service is None:
        audit_service = AuditService()
    return DatabaseOperationPrepareService(
        registry=registry,
        database_path=db_path,
        permission_service=permission_service,
        repository=repository,
        audit_service=audit_service,
        dialect=dialect,
        operation_executor=operation_executor,
    )


def build_database_operation_direct_execute_service(
    *,
    database_path: str | Path = SANDBOX_DATABASE_PATH,
    registry: DatabaseSchemaRegistry | None = None,
    permission_service: PermissionService | None = None,
    audit_service: AuditService | None = None,
    dialect: str = "sqlite",
    operation_executor: DatabaseOperationDirectExecutor | None = None,
) -> DatabaseOperationDirectExecuteService:
    registry = registry or build_default_sandbox_registry()
    permission_service = permission_service or global_permission_service
    db_path = Path(database_path)
    if operation_executor is None:
        if dialect == "sqlite":
            ensure_sandbox_database(db_path, registry)
        operation_executor = SQLiteDatabaseOperationExecutor(
            registry=registry,
            database_path=db_path,
        )
    if audit_service is None:
        audit_service = AuditService()
    return DatabaseOperationDirectExecuteService(
        registry=registry,
        permission_service=permission_service,
        audit_service=audit_service,
        dialect=dialect,
        operation_executor=operation_executor,
    )


def build_default_database_operation_services() -> tuple[
    DatabaseOperationPrepareService,
    DatabaseOperationDirectExecuteService,
]:
    mysql_bundle = build_mysql_operation_executor_from_config(app_config=config)
    if mysql_bundle is not None:
        registry, operation_executor = mysql_bundle
        audit_service = AuditService()
        return (
            build_database_operation_prepare_service(
                registry=registry,
                permission_service=global_permission_service,
                audit_service=audit_service,
                dialect=operation_executor.dialect,
                operation_executor=operation_executor,
            ),
            build_database_operation_direct_execute_service(
                registry=registry,
                permission_service=global_permission_service,
                audit_service=audit_service,
                dialect=operation_executor.dialect,
                operation_executor=operation_executor,
            ),
        )
    return (
        build_database_operation_prepare_service(),
        build_database_operation_direct_execute_service(),
    )


def get_database_operation_prepare_service() -> DatabaseOperationPrepareService:
    global database_operation_prepare_service
    global database_operation_direct_execute_service
    if (
        database_operation_prepare_service is None
        and database_operation_direct_execute_service is None
    ):
        (
            database_operation_prepare_service,
            database_operation_direct_execute_service,
        ) = build_default_database_operation_services()
    elif database_operation_prepare_service is None:
        database_operation_prepare_service = build_database_operation_prepare_service()
    return database_operation_prepare_service


def get_database_operation_direct_execute_service() -> DatabaseOperationDirectExecuteService:
    global database_operation_prepare_service
    global database_operation_direct_execute_service
    if (
        database_operation_prepare_service is None
        and database_operation_direct_execute_service is None
    ):
        (
            database_operation_prepare_service,
            database_operation_direct_execute_service,
        ) = build_default_database_operation_services()
    elif database_operation_direct_execute_service is None:
        database_operation_direct_execute_service = build_database_operation_direct_execute_service()
    return database_operation_direct_execute_service


def _require_context() -> RequestContext:
    context = get_current_request_context()
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="RequestContext is missing",
        )
    return context


def _tool_error_to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, ToolAccessDenied):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.reason)
    if isinstance(exc, ToolExecutionError):
        if isinstance(exc.cause, SafeSqlBlocked):
            return HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=exc.cause.reason,
            )
        if isinstance(exc.cause, DatabaseExecutionError):
            return HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="database_execution_failed",
            )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="database_tool_execution_failed",
    )


def _safe_select_tool_id(database_id: str) -> str:
    normalized = database_id.strip()
    if normalized in {"sandbox_sales", "database_demo"}:
        return "database_demo.safe_select"
    return f"database_mysql.{normalized}.safe_select"


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _build_sample_sql(table_name: str, columns: list[str], limit: int) -> str:
    column_sql = ", ".join(_quote_identifier(column) for column in columns)
    return f"SELECT {column_sql} FROM {_quote_identifier(table_name)} LIMIT {limit}"


@router.post("/safe-select")
async def safe_select(request: SafeSelectRequest, _current_user: CurrentUser):
    context = _require_context()
    try:
        result = await get_database_tool_gateway().execute(
            context,
            _safe_select_tool_id(request.database_id),
            {"sql": request.sql},
        )
    except (ToolAccessDenied, ToolExecutionError) as exc:
        raise _tool_error_to_http(exc) from exc
    return success_payload({"result": result})


@router.get("/catalog")
async def database_catalog(_current_user: CurrentUser):
    context = _require_context()
    gateway = get_database_tool_gateway()
    catalog = await DatabaseCapabilityCatalogService(
        registry=build_default_sandbox_registry(),
        permission_service=gateway.permission_service,
        tool_gateway=gateway,
    ).build_catalog(context)
    return success_payload({"catalog": catalog})


@router.get("/{database_id}/tables/{table_name}/sample")
async def database_table_sample_rows(
    http_request: Request,
    database_id: str,
    table_name: str,
    _current_user: CurrentUser,
    limit: int = Query(default=10, ge=1, le=100),
):
    gateway_request = GatewayRequest.from_headers(
        route="database_catalog_sample_rows",
        payload={"database_id": database_id, "table_name": table_name, "limit": limit},
        headers=http_request.headers,
    )

    async def handler(context: RequestContext):
        tool_gateway = get_database_tool_gateway()
        catalog_service = DatabaseCapabilityCatalogService(
            registry=build_default_sandbox_registry(),
            permission_service=tool_gateway.permission_service,
            tool_gateway=tool_gateway,
        )
        try:
            authorized_columns = catalog_service.get_authorized_columns(
                context,
                database_id=database_id,
                table_name=table_name,
            )
            table = catalog_service.registry.require_table(table_name)
        except SafeSqlBlocked as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.reason) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="unauthorized_table",
            ) from exc

        if not authorized_columns:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="database_column_denied",
            )

        sql = _build_sample_sql(table.name, authorized_columns, limit)
        try:
            result = await tool_gateway.execute(
                context,
                _safe_select_tool_id(database_id),
                {"sql": sql},
            )
        except (ToolAccessDenied, ToolExecutionError) as exc:
            raise _tool_error_to_http(exc) from exc

        return success_payload(
            {
                "sample": {
                    "database_id": result.get("database_id", database_id),
                    "table_name": table.name,
                    "columns": result.get("columns", authorized_columns),
                    "rows": result.get("rows", []),
                    "row_count": result.get("row_count", 0),
                    "limit": limit,
                    "safe_sql_verified": bool(result.get("safe_sql_verified")),
                    "total_rows_estimate": None,
                }
            }
        )

    return await gateway.execute(gateway_request, handler)


@router.post("/operations/prepare")
async def prepare_database_operation(
    request: DatabaseOperationPrepareRequest,
    _current_user: CurrentUser,
):
    context = _require_context()
    try:
        result = get_database_operation_prepare_service().prepare(
            context,
            database_id=request.database_id,
            sql=request.sql,
            reason=request.reason,
        )
    except DatabaseOperationPrepareDenied as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.reason) from exc
    return success_payload(result.model_dump(mode="json"))


@router.post("/operations/execute")
async def execute_database_operation(
    request: DatabaseOperationExecuteRequest,
    _current_user: CurrentUser,
):
    context = _require_context()
    try:
        result = get_database_operation_direct_execute_service().execute(
            context,
            database_id=request.database_id,
            sql=request.sql,
        )
    except DatabaseOperationDirectExecuteDenied as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.reason) from exc
    return success_payload(result.model_dump(mode="json"))


def _confirmation_error_to_http(exc: DatabaseOperationConfirmationDenied) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.reason)


@router.get("/confirmations")
async def list_database_operation_confirmations(
    _current_user: CurrentUser,
    status_filter: str | None = Query(default=None, alias="status"),
):
    context = _require_context()
    try:
        parsed_status = (
            DatabaseOperationConfirmationStatus(status_filter)
            if status_filter is not None
            else None
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid_confirmation_status",
        ) from exc
    confirmations = get_database_operation_prepare_service().list_confirmations(
        context,
        status=parsed_status,
    )
    return success_payload(
        {
            "confirmations": [
                confirmation.model_dump(mode="json")
                for confirmation in confirmations
            ]
        }
    )


@router.get("/confirmations/{confirmation_id}")
async def get_database_operation_confirmation(
    confirmation_id: str,
    _current_user: CurrentUser,
):
    context = _require_context()
    try:
        confirmation = get_database_operation_prepare_service().get_confirmation(
            context,
            confirmation_id,
        )
    except DatabaseOperationConfirmationDenied as exc:
        raise _confirmation_error_to_http(exc) from exc
    return success_payload({"confirmation": confirmation.model_dump(mode="json")})


@router.post("/confirmations/{confirmation_id}/cancel")
async def cancel_database_operation_confirmation(
    confirmation_id: str,
    _current_user: CurrentUser,
):
    context = _require_context()
    try:
        confirmation = get_database_operation_prepare_service().cancel(
            context,
            confirmation_id,
        )
    except DatabaseOperationConfirmationDenied as exc:
        raise _confirmation_error_to_http(exc) from exc
    return success_payload(confirmation.model_dump(mode="json"))


@router.post("/confirmations/{confirmation_id}/confirm")
async def confirm_database_operation_confirmation(
    confirmation_id: str,
    _current_user: CurrentUser,
):
    context = _require_context()
    try:
        confirmation = get_database_operation_prepare_service().confirm(
            context,
            confirmation_id,
        )
    except DatabaseOperationConfirmationDenied as exc:
        raise _confirmation_error_to_http(exc) from exc
    return success_payload(confirmation.model_dump(mode="json"))
