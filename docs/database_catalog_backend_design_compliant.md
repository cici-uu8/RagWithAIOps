# P1 Database Catalog 后端 API 设计（架构合规版）

## 架构约束

根据 `docs/项目完整架构.md` 第 4.6 节架构铁律：

```
数据库能力必须经过 SafeSqlKernel 和 DB permission

无论哪类（HTTP 展示和 catalog / Agent tool 执行），都不得绕过：
- ToolGateway tool/use
- database/read、database/write、database/admin
- registry allowlist
- SQL classifier / SafeSqlKernel / operation permission checker
- audit
```

Database Catalog 的 sample rows 也属于数据库能力，**必须走 ToolGateway + SafeSqlKernel**。

## 实现方案

### Step 1: 复用现有 DatabaseCapabilityCatalogService

**现状**：
- ✅ 已有：`app/enterprise/database/catalog.py`（`DatabaseCapabilityCatalogService`）
- ✅ 已有：`GET /api/database/catalog`（返回用户可见的 DB 列表）

**不需要新增 Adapter**：`DatabaseCapabilityCatalogService` 本身就是 service 层。

---

### Step 2: 新增 Sample Rows API（必须走 ToolGateway）

**目标**：提供 sample rows 端点，**只能通过 ToolGateway 执行 safe_select**。

**文件清单**：
- 修改：`app/enterprise/database/routes.py`（新增 sample rows 端点）
- 修改：`tests/test_database_catalog_routes.py`（新增测试）

**API 设计**：

```python
# app/enterprise/database/routes.py
from fastapi import APIRouter, Depends, HTTPException
from app.enterprise.auth.dependencies import get_current_user, CurrentUser
from app.enterprise.context import RequestContext, create_request_context
from app.enterprise.gateway.request_gateway import RequestGateway, GatewayRequest
from app.enterprise.tools.gateway import ToolGateway
from app.enterprise.database.catalog import DatabaseCapabilityCatalogService

router = APIRouter(prefix="/api/database", tags=["database"])


@router.get("/{database_id}/tables/{table_name}/sample")
async def get_table_sample_rows(
    database_id: str,
    table_name: str,
    limit: int = 10,
    current_user: CurrentUser = Depends(get_current_user),
    catalog_service: DatabaseCapabilityCatalogService = Depends(get_catalog_service),
    tool_gateway: ToolGateway = Depends(get_tool_gateway),
    request_gateway: RequestGateway = Depends(get_request_gateway)
):
    """
    查询表的 sample rows（前 N 行，只显示已授权列）。
    
    架构路径：
    route -> RequestGateway -> [构造 SQL] -> ToolGateway.execute(safe_select) -> SafeSqlKernel
    
    权限边界：
    - 只查询用户已授权的列
    - 未授权列不在 SQL 中，也不在返回结果中
    - 必须走 ToolGateway（不能直连 DB）
    """
    context = create_request_context(current_user)
    
    async def _handler(ctx: RequestContext):
        # 1. 查询用户已授权的列
        authorized_columns = await catalog_service.get_authorized_columns(
            ctx,
            database_id=database_id,
            table_name=table_name
        )
        
        if not authorized_columns:
            raise HTTPException(
                status_code=403,
                detail=f"No authorized columns for table {table_name}"
            )
        
        # 2. 构造 SQL（只 SELECT 已授权列）
        columns_str = ", ".join(authorized_columns)
        sql = f"SELECT {columns_str} FROM {table_name} LIMIT {limit}"
        
        # 3. 通过 ToolGateway 执行（走 SafeSqlKernel）
        tool_name = _get_tool_name(database_id)  # "database_demo.safe_select" 或 "database_mysql.<id>.safe_select"
        
        result = await tool_gateway.execute(
            context=ctx,
            tool_name=tool_name,
            arguments={"sql": sql}
        )
        
        # 4. 返回结果（只包含已授权列）
        return {
            "rows": result.get("rows", []),
            "columns": authorized_columns,
            "total_rows_estimate": None  # 第一版不提供 row count，避免绕过 SafeSqlKernel
        }
    
    gateway_request = GatewayRequest(
        context=context,
        operation_name="database_catalog_sample_rows",
        handler=_handler
    )
    
    return await request_gateway.execute(gateway_request)


@router.get("/{database_id}/tables/{table_name}/stats")
async def get_table_stats(
    database_id: str,
    table_name: str,
    current_user: CurrentUser = Depends(get_current_user),
    request_gateway: RequestGateway = Depends(get_request_gateway)
):
    """
    查询表的统计信息（row count / size）。
    
    第一版：返回 null，避免绕过 SafeSqlKernel 直连系统表。
    未来可以通过 ToolGateway 执行 COUNT(*) 或查询 information_schema（也必须走 SafeSqlKernel）。
    """
    context = create_request_context(current_user)
    
    async def _handler(ctx: RequestContext):
        # 第一版：不提供真实统计，避免绕过 DB seam
        return {
            "row_count_estimate": None,
            "size_bytes": None,
            "last_updated": None,
            "note": "Stats not available in first version (requires SafeSqlKernel integration)"
        }
    
    gateway_request = GatewayRequest(
        context=context,
        operation_name="database_catalog_table_stats",
        handler=_handler
    )
    
    return await request_gateway.execute(gateway_request)


def _get_tool_name(database_id: str) -> str:
    """
    根据 database_id 返回对应的 tool name。
    
    - sandbox_sales / database_demo -> "database_demo.safe_select"
    - enterprise_mysql_xxx -> "database_mysql.{database_id}.safe_select"
    """
    if database_id in ["sandbox_sales", "database_demo"]:
        return "database_demo.safe_select"
    elif database_id.startswith("enterprise_mysql_"):
        return f"database_mysql.{database_id}.safe_select"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown database_id: {database_id}"
        )
```

---

### Step 3: DatabaseCapabilityCatalogService 新增方法

**目标**：提供 `get_authorized_columns()` 方法，返回用户已授权的列。

**文件清单**：
- 修改：`app/enterprise/database/catalog.py`

**方法设计**：

```python
# app/enterprise/database/catalog.py
class DatabaseCapabilityCatalogService:
    def __init__(
        self,
        permission_service: PermissionService,
        registry: DatabaseSchemaRegistry,
        tool_gateway: ToolGateway
    ):
        self.permission_service = permission_service
        self.registry = registry
        self.tool_gateway = tool_gateway
    
    async def get_authorized_columns(
        self,
        context: RequestContext,
        database_id: str,
        table_name: str
    ) -> list[str]:
        """
        查询用户对指定表的已授权列。
        
        权限边界：
        - 用户必须有 table read 权限
        - 只返回有 column read 权限的列
        
        Returns:
            ["column_a", "column_b", ...]  # 只包含已授权列
        """
        # 1. 检查 table read 权限
        table_resource_id = f"database_table:{database_id}.{table_name}:read"
        table_allowed = await self.permission_service.check(
            context.user_id,
            table_resource_id,
            "read"
        )
        
        if not table_allowed:
            return []  # 无 table 权限，返回空列表
        
        # 2. 从 registry 获取所有列
        all_columns = self.registry.get_columns(database_id, table_name)
        
        # 3. 过滤：只保留已授权的列
        authorized_columns = []
        for col in all_columns:
            column_resource_id = f"database_column:{database_id}.{table_name}.{col.column_name}:read"
            col_allowed = await self.permission_service.check(
                context.user_id,
                column_resource_id,
                "read"
            )
            if col_allowed:
                authorized_columns.append(col.column_name)
        
        return authorized_columns
```

---

### Step 4: 明确不做（第一版）

**不做的原因**：避免绕过 SafeSqlKernel。

1. ❌ **不直连数据库查询 row count**：
   - 第一版 `get_table_stats()` 返回 `row_count_estimate=null`
   - 未来可以通过 ToolGateway 执行 `SELECT COUNT(*) FROM {table}`（也走 SafeSqlKernel）

2. ❌ **不直连 information_schema 查询 size_bytes**：
   - 第一版返回 `size_bytes=null`
   - 未来可以通过 ToolGateway 执行 `SELECT * FROM information_schema.tables WHERE table_name=...`

3. ❌ **不在 route 中拼接 SQL 后直连 DB**：
   - 所有 SQL 执行都必须走 `ToolGateway.execute(..., tool_name="database_demo.safe_select", ...)`

---

## 架构合规检查

### ✅ 遵守架构铁律 4.1（RequestGateway）
- ✅ 所有 HTTP route 都走 `RequestGateway.execute(...)`
- ✅ 自动写 `request_started` / `request_completed` / `request_failed` audit

### ✅ 遵守架构铁律 4.6（SafeSqlKernel）
- ✅ sample rows 通过 `ToolGateway.execute(..., tool_name="database_demo.safe_select", ...)` 执行
- ✅ SQL 经过 `SafeSqlKernel` 检查（allowlist / classifier / permission）
- ✅ 未授权列不在 SQL 中，也不在返回结果中
- ✅ 写 `database_query` audit（由 ToolGateway 自动完成）

### ✅ 遵守架构铁律 4.3（权限判断）
- ✅ 权限判断在 `PermissionService` 中完成
- ✅ `get_authorized_columns()` 先查 table read，再过滤 column read
- ✅ 页面不硬编码权限

---

## 验收标准

1. ✅ 所有 HTTP route 都走 `RequestGateway.execute(...)`
2. ✅ sample rows 通过 `ToolGateway.execute(...)` 执行，不直连 DB
3. ✅ SQL 经过 `SafeSqlKernel` 检查
4. ✅ 只返回已授权列（未授权列不在 SQL 中）
5. ✅ 无 table 权限返回 403
6. ✅ 无 column 权限的列不在返回结果中
7. ✅ 写 `database_query` audit（由 ToolGateway 自动完成）
8. ✅ 第一版 stats 返回 null，明确标注原因

**测试覆盖**：
```bash
uv run pytest tests/test_database_catalog_routes.py -q --no-cov

# 测试覆盖：
# - 有 table + column 权限：返回 sample rows
# - 无 table 权限：返回 403
# - 只有部分 column 权限：只返回已授权列
# - ToolGateway.execute 被调用（mock 验证）
# - SafeSqlKernel 被调用（通过 ToolGateway）
# - 写 request audit 和 database_query audit
```

