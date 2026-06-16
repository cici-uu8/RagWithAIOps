# Admin Stage 3-Lite Resource Catalog And Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Optimization 2 Stage 3-lite: an admin resource catalog, grant create validation, and preview-lite for safer permission grants without implementing scoped admin, permission requests, or full impact preview.

**Architecture:** Keep all new governance logic under `app/enterprise/admin/` so E8 admin remains the product boundary. Add a catalog service that enumerates only authoritative resources, then add one shared grant validator used by both `POST /api/admin/grant-preview` and `POST /api/admin/grants`. The admin console consumes catalog `actions_supported` from the backend and uses preview-lite as a UI guard, while create still reruns validation server-side.

**Tech Stack:** FastAPI, Pydantic, `unittest`, existing `AdminService`, `PermissionService`, `AuthService`, `KnowledgeMetadataStore`, `app.tools` canonical tool list, `DatabaseSchemaRegistry`, static Vue3 CDN admin console.

---

## Locked Decisions

These decisions are part of the implementation contract for this stage:

- Resource catalog includes only `document`, `tool`, `database_table`, and `database_column`.
- `model_endpoint` is not in Stage 3-lite.
- Tool catalog uses a frozen canonical list of the three local tools exported by `app/tools`: `retrieve_knowledge`, `list_knowledge_documents`, and `get_current_time`. Tool `resource_id` values are bare tool names. Do not derive them from `tool:` prefixes, `ToolGateway`, or provider discovery in Stage 3-lite.
- Catalog does not return a top-level `kbs` array. Documents expose `metadata.kb_id`; grouping is a UI concern.
- Stage 3-lite does not clean upstream dirty metadata. If `metadata.kb_id` is blank or whitespace-only, the UI should display that group as `未分组`.
- Catalog does not expose `source`.
- Catalog does not expose a generic `status`; Stage 3-lite only lists eligible resources.
- Catalog lists only documents whose `document.status == DocumentStatus.INDEXED`. `pending`, `failed`, and `unindexed` documents must not appear.
- Catalog is not paginated in the first version. If any single resource type grows beyond 500 items, add pagination later.
- `database_table` and `database_column` resource IDs must use `database_table_resource_id()` and `database_column_resource_id()` from `app/enterprise/database/permissions.py`.
- Supported action matrix for Stage 3-lite:
  - `document` -> `read`
  - `tool` -> `use`
  - `database_table` -> `read`
  - `database_column` -> `read`
- `manage` and `approve` are not exposed in Stage 3-lite.
- `principal_exists` is included in Stage 3-lite.
- `public` principal is valid only when `principal_id == "*"`.
- `principal_exists` for `department` is best-effort in Stage 3-lite and is derived from the active user list. Stage 4 replaces this with an explicit `DepartmentService`.
- Repository lookups for `principal_type` serialize the enum with `.value` so enum/string comparisons stay stable.
- Preview response has `can_submit` and `checks[]`; it does not have `valid` or `normalized_grant`.
- Preview is read-only and must not write audit.
- Create and preview must share the same validator.
- Create must rerun validator. UI preview is not a security token.
- `AdminService.grant_access(context, request: GrantCreateRequest)` becomes async and is awaited only by `app/enterprise/admin/routes.py`; that is an intentional breaking change so create and preview share one validator path.
- Create rejects failed validator checks with HTTP 400.
- Create success keeps existing `admin_operation` with `metadata.operation="grant_access"`.
- Create failure writes `admin_operation` with `decision="failed"`, `reason=<failed_check>`, `metadata.operation="grant_access_rejected"`, and `metadata.failed_check=<failed_check>`.
- Duplicate grant key is the 6-tuple `(principal_type, principal_id, resource_type, resource_id, action, effect)`.
- Direct conflict key is the 5-tuple `(principal_type, principal_id, resource_type, resource_id, action)` with opposite `effect`.
- Direct conflict is a warning, not a blocker.
- Use `POST /api/admin/grant-preview`; do not use `/api/admin/grants/preview`, because it collides with `DELETE /api/admin/grants/{grant_id}`.
- The admin console action dropdown must use `resource.actions_supported`, not a frontend hardcoded mapping.

## File Map

- Create: `app/enterprise/admin/resources.py`
  - Builds the Stage 3-lite catalog from authoritative sources.
  - Owns `STAGE3_ACTIONS_BY_RESOURCE_TYPE`.
  - Exposes `ResourceCatalogService.list_resources()`.
  - Tool catalog uses a frozen canonical list of the three local tools exported by `app/tools`. It does not inspect `tool_gateway.providers` in Stage 3-lite.

- Create: `app/enterprise/admin/grant_validator.py`
  - Owns preview-lite and create validation.
  - Defines stable check names and tuple key helpers.
  - Exposes `GrantValidator.preview(request)`.

- Modify: `app/enterprise/admin/models.py`
  - Add catalog and preview response/request models.
  - Reuse `GrantCreateRequest` as the input shape for preview and create.

- Modify: `app/enterprise/admin/service.py`
  - Inject catalog service and validator.
  - Add `list_resources()`.
  - Add `preview_grant()`.
  - Make `grant_access()` rerun validator and write rejected audit on failed checks.

- Modify: `app/enterprise/admin/routes.py`
  - Add `GET /api/admin/resources`.
  - Add `POST /api/admin/grant-preview`.
  - Keep existing `GET /api/admin/grants`, `POST /api/admin/grants`, and `DELETE /api/admin/grants/{grant_id}`.

- Modify: `static/admin-console.html`
  - Add Resources navigation and resource catalog table.
  - Replace freehand resource/action inputs in grant form with catalog-backed selects.
  - Add preview panel before save.

- Modify: `static/admin-console.js`
  - Load resources.
  - Derive actions from selected resource `actions_supported`.
  - Call `/admin/grant-preview`.
  - Disable save until preview has `can_submit=true`.
  - Preserve backend create validation handling for curl/direct POST failures.

- Modify: `docs/助手优化 2.md`
  - Record Stage 3-lite implementation status, route choice, catalog rules, preview-lite boundary, and audit behavior.

- Modify: `docs/rag_fusion_development_record.md`
  - Add factual development record after implementation and verification.

- Test: `tests/test_enterprise_admin_e8.py`
  - Add backend tests for catalog, preview, create validation, and failed audit.

- Test: `tests/test_assistant_frontend_optimization.py`
  - Add static frontend tests for resource route, `actions_supported`, preview flow, and save gating.

## Response Contracts

### `GET /api/admin/resources`

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "resources": [
      {
        "resource_type": "document",
        "resource_id": "doc-guide",
        "name": "guide.md",
        "description": "Indexed document in KB guide",
        "actions_supported": ["read"],
        "metadata": {
          "kb_id": "guide",
          "file_name": "guide.md",
          "parser_engine": "plain_text"
        }
      },
      {
        "resource_type": "tool",
        "resource_id": "retrieve_knowledge",
        "name": "retrieve_knowledge",
        "description": "Knowledge retrieval tool",
        "actions_supported": ["use"],
        "metadata": {
          "category": "knowledge"
        }
      },
      {
        "resource_type": "tool",
        "resource_id": "list_knowledge_documents",
        "name": "list_knowledge_documents",
        "description": "Knowledge document listing tool",
        "actions_supported": ["use"],
        "metadata": {
          "category": "knowledge"
        }
      },
      {
        "resource_type": "database_table",
        "resource_id": "sandbox_sales.orders",
        "name": "orders",
        "description": "Sandbox order records for read-only database demos.",
        "actions_supported": ["read"],
        "metadata": {
          "database_id": "sandbox_sales",
          "table_name": "orders"
        }
      },
      {
        "resource_type": "database_column",
        "resource_id": "sandbox_sales.orders.order_id",
        "name": "orders.order_id",
        "description": "Order id",
        "actions_supported": ["read"],
        "metadata": {
          "database_id": "sandbox_sales",
          "table_name": "orders",
          "column_name": "order_id",
          "data_type": "INTEGER",
          "sensitive": false,
          "mask": null
        }
      }
    ]
  }
}
```

### `POST /api/admin/grant-preview`

Request is exactly the current `GrantCreateRequest` shape:

```json
{
  "principal_type": "user",
  "principal_id": "user_demo_dept1",
  "resource_type": "document",
  "resource_id": "doc-guide",
  "action": "read",
  "effect": "allow",
  "reason": "Need guide access"
}
```

Success response:

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "can_submit": true,
    "checks": [
      {
        "check": "resource_exists",
        "status": "passed",
        "message": "Resource exists in catalog.",
        "matched_grant_ids": []
      },
      {
        "check": "action_supported",
        "status": "passed",
        "message": "Action is supported for this resource.",
        "matched_grant_ids": []
      },
      {
        "check": "principal_exists",
        "status": "passed",
        "message": "Principal exists.",
        "matched_grant_ids": []
      },
      {
        "check": "duplicate_grant",
        "status": "passed",
        "message": "No duplicate grant found.",
        "matched_grant_ids": []
      },
      {
        "check": "direct_conflict",
        "status": "passed",
        "message": "No direct allow/deny conflict found.",
        "matched_grant_ids": []
      }
    ]
  }
}
```

Conflict warning example:

```json
{
  "check": "direct_conflict",
  "status": "warning",
  "message": "Existing deny will block this allow (deny precedes allow).",
  "matched_grant_ids": ["grant-existing-deny"]
}
```

Submit-deny warning example:

```json
{
  "check": "direct_conflict",
  "status": "warning",
  "message": "This deny will override existing allow grant.",
  "matched_grant_ids": ["grant-existing-allow"]
}
```

Failed response stays HTTP 200 for preview, with `can_submit=false`:

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "can_submit": false,
    "checks": [
      {
        "check": "resource_exists",
        "status": "failed",
        "message": "Resource is not in catalog.",
        "matched_grant_ids": []
      },
      {
        "check": "action_supported",
        "status": "skipped",
        "message": "Skipped because resource_exists failed.",
        "matched_grant_ids": []
      },
      {
        "check": "principal_exists",
        "status": "skipped",
        "message": "Skipped because resource_exists failed.",
        "matched_grant_ids": []
      },
      {
        "check": "duplicate_grant",
        "status": "skipped",
        "message": "Skipped because resource_exists failed.",
        "matched_grant_ids": []
      },
      {
        "check": "direct_conflict",
        "status": "skipped",
        "message": "Skipped because resource_exists failed.",
        "matched_grant_ids": []
      }
    ]
  }
}
```

## Task 1: Backend Resource Catalog

**Files:**
- Create: `app/enterprise/admin/resources.py`
- Modify: `app/enterprise/admin/models.py`
- Modify: `app/enterprise/admin/service.py`
- Modify: `app/enterprise/admin/routes.py`
- Test: `tests/test_enterprise_admin_e8.py`

- [ ] **Step 1: Write failing catalog tests**

Append these tests to `tests/test_enterprise_admin_e8.py`. Reuse the existing `EnterpriseAdminE8Tests` class and helper methods.

```python
    def test_admin_resource_catalog_lists_indexed_documents_tools_and_database_resources(self):
        from app.enterprise.admin.resources import ResourceCatalogService
        from app.enterprise.database.permissions import database_column_resource_id, database_table_resource_id
        from app.enterprise.database.registry import build_default_sandbox_registry
        from app.models import DocumentRecord, DocumentStatus, ParserEngine
        from app.services.knowledge_metadata_store import KnowledgeMetadataStore

        token = self.login()

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(
                DocumentRecord(
                    doc_id="doc-guide",
                    kb_id="guide",
                    file_name="guide.md",
                    file_ext="md",
                    original_path=(root / "guide.md").as_posix(),
                    artifact_dir=(root / "doc-guide" / "artifacts").as_posix(),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.INDEXED,
                )
            )
            metadata_store.upsert_document(
                DocumentRecord(
                    doc_id="doc-pending",
                    kb_id="guide",
                    file_name="pending.md",
                    file_ext="md",
                    original_path=(root / "pending.md").as_posix(),
                    artifact_dir=(root / "doc-pending" / "artifacts").as_posix(),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.PARSE_PENDING,
                )
            )
            registry = build_default_sandbox_registry()
            self.admin_service.resource_catalog = ResourceCatalogService(
                metadata_store=metadata_store,
                database_registry=registry,
            )

            response = self.client.get(
                "/api/admin/resources",
                headers={"Authorization": f"Bearer {token}"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        resources = response.json()["data"]["resources"]
        by_id = {resource["resource_id"]: resource for resource in resources}

        self.assertIn("doc-guide", by_id)
        self.assertNotIn("doc-pending", by_id)
        self.assertEqual(by_id["doc-guide"]["resource_type"], "document")
        self.assertEqual(by_id["doc-guide"]["actions_supported"], ["read"])
        self.assertEqual(by_id["doc-guide"]["metadata"]["kb_id"], "guide")
        self.assertNotIn("status", by_id["doc-guide"])
        self.assertNotIn("source", by_id["doc-guide"])

        self.assertIn("retrieve_knowledge", by_id)
        self.assertEqual(by_id["retrieve_knowledge"]["actions_supported"], ["use"])
        self.assertIn("list_knowledge_documents", by_id)
        self.assertEqual(by_id["list_knowledge_documents"]["actions_supported"], ["use"])
        self.assertIn("get_current_time", by_id)
        self.assertEqual(by_id["get_current_time"]["actions_supported"], ["use"])

        table_id = database_table_resource_id(registry.database_id, "orders")
        column_id = database_column_resource_id(registry.database_id, "orders", "order_id")
        self.assertIn(table_id, by_id)
        self.assertIn(column_id, by_id)
        self.assertEqual(by_id[table_id]["actions_supported"], ["read"])
        self.assertEqual(by_id[column_id]["metadata"]["column_name"], "order_id")
        self.assertNotIn("kbs", response.json()["data"])

    def test_non_admin_cannot_read_resource_catalog(self):
        token = self.login("demo_user_dept1", "Demo123!")

        response = self.client.get(
            "/api/admin/resources",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m unittest tests.test_enterprise_admin_e8.EnterpriseAdminE8Tests.test_admin_resource_catalog_lists_indexed_documents_tools_and_database_resources tests.test_enterprise_admin_e8.EnterpriseAdminE8Tests.test_non_admin_cannot_read_resource_catalog -v
```

Expected: FAIL because `app.enterprise.admin.resources` and `/api/admin/resources` do not exist.

- [ ] **Step 3: Add catalog models**

Modify `app/enterprise/admin/models.py` and add these classes after `GrantCreateRequest`:

```python
class AdminResourceDescriptor(BaseModel):
    resource_type: str = Field(..., min_length=1)
    resource_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    actions_supported: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Implement catalog service**

Create `app/enterprise/admin/resources.py`:

```python
"""Resource catalog for Optimization 2 Stage 3-lite admin grants."""

from __future__ import annotations

from app.enterprise.admin.models import AdminResourceDescriptor
from app.enterprise.database.permissions import (
    database_column_resource_id,
    database_table_resource_id,
)
from app.enterprise.database.registry import DatabaseSchemaRegistry, build_default_sandbox_registry
from app.tools import get_current_time, list_knowledge_documents, retrieve_knowledge
from app.models import DocumentStatus
from app.services.knowledge_metadata_store import KnowledgeMetadataStore, knowledge_metadata_store


STAGE3_ACTIONS_BY_RESOURCE_TYPE: dict[str, list[str]] = {
    "document": ["read"],
    "tool": ["use"],
    "database_table": ["read"],
    "database_column": ["read"],
}


class ResourceCatalogService:
    def __init__(
        self,
        *,
        metadata_store: KnowledgeMetadataStore | None = None,
        database_registry: DatabaseSchemaRegistry | None = None,
    ):
        self.metadata_store = metadata_store or knowledge_metadata_store
        self.database_registry = database_registry or build_default_sandbox_registry()

    async def list_resources(self) -> list[AdminResourceDescriptor]:
        resources: list[AdminResourceDescriptor] = []
        resources.extend(self._document_resources())
        resources.extend(self._tool_resources())
        resources.extend(self._database_table_resources())
        resources.extend(self._database_column_resources())
        return sorted(
            resources,
            key=lambda resource: (
                resource.resource_type,
                resource.metadata.get("kb_id", ""),
                resource.name,
                resource.resource_id,
            ),
        )

    async def get_resource(
        self,
        *,
        resource_type: str,
        resource_id: str,
    ) -> AdminResourceDescriptor | None:
        for resource in await self.list_resources():
            if resource.resource_type == resource_type and resource.resource_id == resource_id:
                return resource
        return None

    def _document_resources(self) -> list[AdminResourceDescriptor]:
        return [
            AdminResourceDescriptor(
                resource_type="document",
                resource_id=document.doc_id,
                name=document.file_name,
                description=f"Indexed document in KB {document.kb_id}",
                actions_supported=STAGE3_ACTIONS_BY_RESOURCE_TYPE["document"],
                metadata={
                    "kb_id": document.kb_id,
                    "file_name": document.file_name,
                    "parser_engine": document.parser_engine.value,
                },
            )
            for document in self.metadata_store.list_documents()
            if document.status == DocumentStatus.INDEXED
        ]

    def _tool_resources(self) -> list[AdminResourceDescriptor]:
        canonical_tools = {
            "retrieve_knowledge": {
                "tool": retrieve_knowledge,
                "description": "Knowledge retrieval tool",
                "category": "knowledge",
            },
            "list_knowledge_documents": {
                "tool": list_knowledge_documents,
                "description": "Knowledge document listing tool",
                "category": "knowledge",
            },
            "get_current_time": {
                "tool": get_current_time,
                "description": "Current time tool",
                "category": "time",
            },
        }
        return [
            AdminResourceDescriptor(
                resource_type="tool",
                resource_id=resource_id,
                name=resource_id,
                description=str(
                    getattr(definition["tool"], "description", "")
                    or definition["description"]
                ),
                actions_supported=STAGE3_ACTIONS_BY_RESOURCE_TYPE["tool"],
                metadata={"category": definition["category"]},
            )
            for resource_id, definition in sorted(canonical_tools.items())
        ]

    def _database_table_resources(self) -> list[AdminResourceDescriptor]:
        resources: list[AdminResourceDescriptor] = []
        for table_name in self.database_registry.list_tables():
            table = self.database_registry.require_table(table_name)
            resources.append(
                AdminResourceDescriptor(
                    resource_type="database_table",
                    resource_id=database_table_resource_id(
                        self.database_registry.database_id,
                        table.name,
                    ),
                    name=table.name,
                    description=table.description,
                    actions_supported=STAGE3_ACTIONS_BY_RESOURCE_TYPE["database_table"],
                    metadata={
                        "database_id": self.database_registry.database_id,
                        "table_name": table.name,
                    },
                )
            )
        return resources

    def _database_column_resources(self) -> list[AdminResourceDescriptor]:
        resources: list[AdminResourceDescriptor] = []
        for table_name in self.database_registry.list_tables():
            table = self.database_registry.require_table(table_name)
            for column in table.visible_columns():
                resources.append(
                    AdminResourceDescriptor(
                        resource_type="database_column",
                        resource_id=database_column_resource_id(
                            self.database_registry.database_id,
                            table.name,
                            column.name,
                        ),
                        name=f"{table.name}.{column.name}",
                        description=column.description,
                        actions_supported=STAGE3_ACTIONS_BY_RESOURCE_TYPE["database_column"],
                        metadata={
                            "database_id": self.database_registry.database_id,
                            "table_name": table.name,
                            "column_name": column.name,
                            "data_type": column.data_type,
                            "sensitive": column.sensitive,
                            "mask": column.mask,
                        },
                    )
                )
        return resources

resource_catalog_service = ResourceCatalogService()
```

- [ ] **Step 5: Wire service and route**

Modify `app/enterprise/admin/service.py`:

```python
from app.enterprise.admin.resources import ResourceCatalogService, resource_catalog_service
```

Add `resource_catalog` to `AdminService.__init__`:

```python
        resource_catalog: ResourceCatalogService | None = None,
```

Store it:

```python
        self.resource_catalog = resource_catalog or resource_catalog_service
```

Add method:

```python
    async def list_resources(self) -> list:
        return await self.resource_catalog.list_resources()
```

Modify `app/enterprise/admin/routes.py`:

```python
@router.get("/resources")
async def list_resources(_admin: AdminUser):
    resources = await admin_service.list_resources()
    return success_payload({"resources": [resource.model_dump(mode="json") for resource in resources]})
```

- [ ] **Step 6: Run catalog tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_enterprise_admin_e8.EnterpriseAdminE8Tests.test_admin_resource_catalog_lists_indexed_documents_tools_and_database_resources tests.test_enterprise_admin_e8.EnterpriseAdminE8Tests.test_non_admin_cannot_read_resource_catalog -v
```

Expected: PASS.

## Task 2: Preview-Lite And Shared Validator

**Files:**
- Create: `app/enterprise/admin/grant_validator.py`
- Modify: `app/enterprise/admin/models.py`
- Modify: `app/enterprise/admin/service.py`
- Modify: `app/enterprise/admin/routes.py`
- Test: `tests/test_enterprise_admin_e8.py`

- [ ] **Step 1: Write failing preview tests**

Append these tests to `tests/test_enterprise_admin_e8.py`:

```python
    def test_grant_preview_passes_for_existing_resource_action_and_principal(self):
        from app.enterprise.admin.resources import ResourceCatalogService
        from app.models import DocumentRecord, DocumentStatus, ParserEngine
        from app.services.knowledge_metadata_store import KnowledgeMetadataStore

        token = self.login()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(
                DocumentRecord(
                    doc_id="doc-guide",
                    kb_id="guide",
                    file_name="guide.md",
                    file_ext="md",
                    original_path=(root / "guide.md").as_posix(),
                    artifact_dir=(root / "doc-guide" / "artifacts").as_posix(),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.INDEXED,
                )
            )
            self.admin_service.resource_catalog = ResourceCatalogService(metadata_store=metadata_store)

            response = self.client.post(
                "/api/admin/grant-preview",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "resource_type": "document",
                    "resource_id": "doc-guide",
                    "action": "read",
                    "principal_type": "user",
                    "principal_id": "user_demo_dept1",
                    "effect": "allow",
                    "reason": "preview pass",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertTrue(data["can_submit"])
        self.assertEqual(
            [check["check"] for check in data["checks"]],
            [
                "resource_exists",
                "action_supported",
                "principal_exists",
                "duplicate_grant",
                "direct_conflict",
            ],
        )
        self.assertTrue(all(check["status"] == "passed" for check in data["checks"]))

    def test_grant_preview_blocks_missing_resource_and_skips_dependent_checks(self):
        token = self.login()

        response = self.client.post(
            "/api/admin/grant-preview",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "resource_type": "document",
                "resource_id": "doc-missing",
                "action": "read",
                "principal_type": "user",
                "principal_id": "user_demo_dept1",
                "effect": "allow",
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertFalse(data["can_submit"])
        self.assertEqual(data["checks"][0]["check"], "resource_exists")
        self.assertEqual(data["checks"][0]["status"], "failed")
        self.assertEqual(
            [check["status"] for check in data["checks"][1:]],
            ["skipped", "skipped", "skipped", "skipped"],
        )

    def test_grant_preview_blocks_unsupported_action_and_missing_principal(self):
        from app.enterprise.admin.resources import ResourceCatalogService
        from app.models import DocumentRecord, DocumentStatus, ParserEngine
        from app.services.knowledge_metadata_store import KnowledgeMetadataStore

        token = self.login()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(
                DocumentRecord(
                    doc_id="doc-guide",
                    kb_id="guide",
                    file_name="guide.md",
                    file_ext="md",
                    original_path=(root / "guide.md").as_posix(),
                    artifact_dir=(root / "doc-guide" / "artifacts").as_posix(),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.INDEXED,
                )
            )
            self.admin_service.resource_catalog = ResourceCatalogService(metadata_store=metadata_store)

            response = self.client.post(
                "/api/admin/grant-preview",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "resource_type": "document",
                    "resource_id": "doc-guide",
                    "action": "use",
                    "principal_type": "user",
                    "principal_id": "user_missing",
                    "effect": "allow",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        checks = {check["check"]: check for check in response.json()["data"]["checks"]}
        self.assertFalse(response.json()["data"]["can_submit"])
        self.assertEqual(checks["resource_exists"]["status"], "passed")
        self.assertEqual(checks["action_supported"]["status"], "failed")
        self.assertEqual(checks["principal_exists"]["status"], "failed")

    def test_grant_preview_reports_duplicate_and_direct_conflict(self):
        from app.enterprise.admin.resources import ResourceCatalogService
        from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
        from app.models import DocumentRecord, DocumentStatus, ParserEngine
        from app.services.knowledge_metadata_store import KnowledgeMetadataStore

        token = self.login()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(
                DocumentRecord(
                    doc_id="doc-guide",
                    kb_id="guide",
                    file_name="guide.md",
                    file_ext="md",
                    original_path=(root / "guide.md").as_posix(),
                    artifact_dir=(root / "doc-guide" / "artifacts").as_posix(),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.INDEXED,
                )
            )
            self.admin_service.resource_catalog = ResourceCatalogService(metadata_store=metadata_store)
            duplicate = self.permission_service.grant_access(
                ResourceGrant(
                    resource_type="document",
                    resource_id="doc-guide",
                    action="read",
                    principal_type=PrincipalType.USER,
                    principal_id="user_demo_dept1",
                    effect=GrantEffect.ALLOW,
                )
            )
            conflict = self.permission_service.grant_access(
                ResourceGrant(
                    resource_type="document",
                    resource_id="doc-guide",
                    action="read",
                    principal_type=PrincipalType.USER,
                    principal_id="user_demo_dept1",
                    effect=GrantEffect.DENY,
                )
            )

            response = self.client.post(
                "/api/admin/grant-preview",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "resource_type": "document",
                    "resource_id": "doc-guide",
                    "action": "read",
                    "principal_type": "user",
                    "principal_id": "user_demo_dept1",
                    "effect": "allow",
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        checks = {check["check"]: check for check in data["checks"]}
        self.assertFalse(data["can_submit"])
        self.assertEqual(checks["duplicate_grant"]["status"], "failed")
        self.assertEqual(checks["duplicate_grant"]["matched_grant_ids"], [duplicate.grant_id])
        self.assertEqual(checks["direct_conflict"]["status"], "warning")
        self.assertEqual(checks["direct_conflict"]["matched_grant_ids"], [conflict.grant_id])
        self.assertIn("Existing deny will block this allow", checks["direct_conflict"]["message"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_enterprise_admin_e8.EnterpriseAdminE8Tests.test_grant_preview_passes_for_existing_resource_action_and_principal \
  tests.test_enterprise_admin_e8.EnterpriseAdminE8Tests.test_grant_preview_blocks_missing_resource_and_skips_dependent_checks \
  tests.test_enterprise_admin_e8.EnterpriseAdminE8Tests.test_grant_preview_blocks_unsupported_action_and_missing_principal \
  tests.test_enterprise_admin_e8.EnterpriseAdminE8Tests.test_grant_preview_reports_duplicate_and_direct_conflict \
  -v
```

Expected: FAIL because `/api/admin/grant-preview` and validator do not exist.

- [ ] **Step 3: Add preview models**

Modify `app/enterprise/admin/models.py`:

```python
class GrantValidationCheck(BaseModel):
    check: str
    status: str
    message: str
    matched_grant_ids: list[str] = Field(default_factory=list)


class GrantPreviewResult(BaseModel):
    can_submit: bool
    checks: list[GrantValidationCheck]

    @property
    def failed_check(self) -> str | None:
        for check in self.checks:
            if check.status == "failed":
                return check.check
        return None
```

- [ ] **Step 4: Implement validator**

Create `app/enterprise/admin/grant_validator.py`:

```python
"""Grant preview and create validation for Optimization 2 Stage 3-lite."""

from __future__ import annotations

from app.enterprise.admin.models import GrantCreateRequest, GrantPreviewResult, GrantValidationCheck
from app.enterprise.admin.resources import ResourceCatalogService
from app.enterprise.auth.service import AuthService, auth_service
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.service import PermissionService


CHECK_RESOURCE_EXISTS = "resource_exists"
CHECK_ACTION_SUPPORTED = "action_supported"
CHECK_PRINCIPAL_EXISTS = "principal_exists"
CHECK_DUPLICATE_GRANT = "duplicate_grant"
CHECK_DIRECT_CONFLICT = "direct_conflict"
CHECK_ORDER = [
    CHECK_RESOURCE_EXISTS,
    CHECK_ACTION_SUPPORTED,
    CHECK_PRINCIPAL_EXISTS,
    CHECK_DUPLICATE_GRANT,
    CHECK_DIRECT_CONFLICT,
]


class GrantValidator:
    def __init__(
        self,
        *,
        resource_catalog: ResourceCatalogService,
        permission_service: PermissionService,
        auth: AuthService | None = None,
        roles_by_id: dict[str, object] | None = None,
    ):
        self.resource_catalog = resource_catalog
        self.permission_service = permission_service
        self.auth = auth or auth_service
        self.roles_by_id = roles_by_id if roles_by_id is not None else {}

    async def preview(self, request: GrantCreateRequest) -> GrantPreviewResult:
        checks: list[GrantValidationCheck] = []

        resource = await self.resource_catalog.get_resource(
            resource_type=request.resource_type,
            resource_id=request.resource_id,
        )
        if resource is None:
            checks.append(_failed(CHECK_RESOURCE_EXISTS, "Resource is not in catalog."))
            checks.extend(_skipped_after(CHECK_RESOURCE_EXISTS, start_after=CHECK_RESOURCE_EXISTS))
            return GrantPreviewResult(can_submit=False, checks=checks)
        checks.append(_passed(CHECK_RESOURCE_EXISTS, "Resource exists in catalog."))

        if request.action not in resource.actions_supported:
            checks.append(_failed(CHECK_ACTION_SUPPORTED, "Action is not supported for this resource."))
        else:
            checks.append(_passed(CHECK_ACTION_SUPPORTED, "Action is supported for this resource."))

        if not self._principal_exists(request.principal_type, request.principal_id):
            checks.append(_failed(CHECK_PRINCIPAL_EXISTS, "Principal does not exist."))
        else:
            checks.append(_passed(CHECK_PRINCIPAL_EXISTS, "Principal exists."))

        duplicate_grants = self._matching_grants(request, include_effect=True)
        if duplicate_grants:
            checks.append(
                _failed(
                    CHECK_DUPLICATE_GRANT,
                    "Duplicate grant already exists.",
                    duplicate_grants,
                )
            )
        else:
            checks.append(_passed(CHECK_DUPLICATE_GRANT, "No duplicate grant found."))

        conflict_grants = self._opposite_effect_grants(request)
        if conflict_grants:
            checks.append(
                GrantValidationCheck(
                    check=CHECK_DIRECT_CONFLICT,
                    status="warning",
                    message=_conflict_message(request.effect),
                    matched_grant_ids=[grant.grant_id for grant in conflict_grants],
                )
            )
        else:
            checks.append(_passed(CHECK_DIRECT_CONFLICT, "No direct allow/deny conflict found."))

        can_submit = not any(check.status == "failed" for check in checks)
        return GrantPreviewResult(can_submit=can_submit, checks=checks)

    def _principal_exists(self, principal_type: PrincipalType, principal_id: str) -> bool:
        if principal_type == PrincipalType.PUBLIC:
            return principal_id == "*"
        if principal_type == PrincipalType.USER:
            return any(user.user_id == principal_id for user in self.auth.list_users())
        if principal_type == PrincipalType.ROLE:
            return principal_id in self.roles_by_id
        if principal_type == PrincipalType.DEPARTMENT:
            # Stage 3-lite: department validation is best-effort, derived from active user list.
            # Stage 4 will replace this with explicit DepartmentService.
            return principal_id in {user.department_id for user in self.auth.list_users()}
        return False

    def _matching_grants(
        self,
        request: GrantCreateRequest,
        *,
        include_effect: bool,
    ) -> list[ResourceGrant]:
        grants = self.permission_service.repository.list_all_grants(
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            action=request.action,
            principal_type=request.principal_type.value,
            principal_id=request.principal_id,
        )
        if include_effect:
            grants = [grant for grant in grants if grant.effect == request.effect]
        return grants

    def _opposite_effect_grants(self, request: GrantCreateRequest) -> list[ResourceGrant]:
        opposite = GrantEffect.DENY if request.effect == GrantEffect.ALLOW else GrantEffect.ALLOW
        return [
            grant
            for grant in self._matching_grants(request, include_effect=False)
            if grant.effect == opposite
        ]


def _passed(check: str, message: str) -> GrantValidationCheck:
    return GrantValidationCheck(check=check, status="passed", message=message)


def _failed(
    check: str,
    message: str,
    matched_grants: list[ResourceGrant] | None = None,
) -> GrantValidationCheck:
    return GrantValidationCheck(
        check=check,
        status="failed",
        message=message,
        matched_grant_ids=[grant.grant_id for grant in matched_grants or []],
    )


def _skipped_after(failed_check: str, *, start_after: str) -> list[GrantValidationCheck]:
    start_index = CHECK_ORDER.index(start_after) + 1
    return [
        GrantValidationCheck(
            check=check,
            status="skipped",
            message=f"Skipped because {failed_check} failed.",
        )
        for check in CHECK_ORDER[start_index:]
    ]


def _conflict_message(effect: GrantEffect) -> str:
    if effect == GrantEffect.ALLOW:
        return "Existing deny will block this allow (deny precedes allow)."
    return "This deny will override existing allow grant."
```

- [ ] **Step 5: Wire preview into service**

Modify `app/enterprise/admin/service.py` imports:

```python
from .grant_validator import GrantValidator
from .models import GrantCreateRequest, GrantPreviewResult, RoleRecord
```

Add helper method:

```python
    def _grant_validator(self) -> GrantValidator:
        return GrantValidator(
            resource_catalog=self.resource_catalog,
            permission_service=self.permission_service,
            auth=self.auth,
            roles_by_id=self._roles,
        )
```

Add preview method:

```python
    async def preview_grant(self, request: GrantCreateRequest) -> GrantPreviewResult:
        return await self._grant_validator().preview(request)
```

- [ ] **Step 6: Add route**

Modify `app/enterprise/admin/routes.py`:

```python
@router.post("/grant-preview")
async def preview_grant(request: GrantCreateRequest, _admin: AdminUser):
    preview = await admin_service.preview_grant(request)
    return success_payload(preview.model_dump(mode="json"))
```

- [ ] **Step 7: Run preview tests**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_enterprise_admin_e8.EnterpriseAdminE8Tests.test_grant_preview_passes_for_existing_resource_action_and_principal \
  tests.test_enterprise_admin_e8.EnterpriseAdminE8Tests.test_grant_preview_blocks_missing_resource_and_skips_dependent_checks \
  tests.test_enterprise_admin_e8.EnterpriseAdminE8Tests.test_grant_preview_blocks_unsupported_action_and_missing_principal \
  tests.test_enterprise_admin_e8.EnterpriseAdminE8Tests.test_grant_preview_reports_duplicate_and_direct_conflict \
  -v
```

Expected: PASS.

## Task 3: Enforce Validator On Grant Create And Audit Rejections

**Files:**
- Modify: `app/enterprise/admin/service.py`
- Modify: `app/enterprise/admin/routes.py`
- Test: `tests/test_enterprise_admin_e8.py`

- [ ] **Step 1: Write failing create-validation tests**

Append these tests to `tests/test_enterprise_admin_e8.py`:

```python
    def test_grant_create_rejects_missing_resource_and_writes_failed_audit(self):
        token = self.login()

        response = self.client.post(
            "/api/admin/grants",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Trace-Id": "trace-grant-rejected",
            },
            json={
                "resource_type": "document",
                "resource_id": "doc-missing",
                "action": "read",
                "principal_type": "user",
                "principal_id": "user_demo_dept1",
                "effect": "allow",
            },
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("resource_exists", response.json()["detail"])
        rejected_events = [
            event
            for event in self.sink.events
            if event.event_type == "admin_operation"
            and event.metadata.get("operation") == "grant_access_rejected"
        ]
        self.assertEqual(len(rejected_events), 1)
        self.assertEqual(rejected_events[0].decision, "failed")
        self.assertEqual(rejected_events[0].reason, "resource_exists")
        self.assertEqual(rejected_events[0].metadata["failed_check"], "resource_exists")
        self.assertEqual(rejected_events[0].metadata["target_type"], "grant")
        self.assertEqual(rejected_events[0].metadata["status"], "failed")

    def test_grant_create_rejects_duplicate_but_allows_direct_conflict_warning(self):
        from app.enterprise.admin.resources import ResourceCatalogService
        from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
        from app.models import DocumentRecord, DocumentStatus, ParserEngine
        from app.services.knowledge_metadata_store import KnowledgeMetadataStore

        token = self.login()
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            metadata_store = KnowledgeMetadataStore(root / "metadata.json")
            metadata_store.upsert_document(
                DocumentRecord(
                    doc_id="doc-guide",
                    kb_id="guide",
                    file_name="guide.md",
                    file_ext="md",
                    original_path=(root / "guide.md").as_posix(),
                    artifact_dir=(root / "doc-guide" / "artifacts").as_posix(),
                    parser_engine=ParserEngine.PLAIN_TEXT,
                    status=DocumentStatus.INDEXED,
                )
            )
            self.admin_service.resource_catalog = ResourceCatalogService(metadata_store=metadata_store)
            self.permission_service.grant_access(
                ResourceGrant(
                    resource_type="document",
                    resource_id="doc-guide",
                    action="read",
                    principal_type=PrincipalType.USER,
                    principal_id="user_demo_dept1",
                    effect=GrantEffect.DENY,
                )
            )

            allow_response = self.client.post(
                "/api/admin/grants",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "resource_type": "document",
                    "resource_id": "doc-guide",
                    "action": "read",
                    "principal_type": "user",
                    "principal_id": "user_demo_dept1",
                    "effect": "allow",
                },
            )
            duplicate_response = self.client.post(
                "/api/admin/grants",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "resource_type": "document",
                    "resource_id": "doc-guide",
                    "action": "read",
                    "principal_type": "user",
                    "principal_id": "user_demo_dept1",
                    "effect": "allow",
                },
            )

        self.assertEqual(allow_response.status_code, 200, allow_response.text)
        self.assertEqual(duplicate_response.status_code, 400, duplicate_response.text)
        self.assertIn("duplicate_grant", duplicate_response.json()["detail"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_enterprise_admin_e8.EnterpriseAdminE8Tests.test_grant_create_rejects_missing_resource_and_writes_failed_audit \
  tests.test_enterprise_admin_e8.EnterpriseAdminE8Tests.test_grant_create_rejects_duplicate_but_allows_direct_conflict_warning \
  -v
```

Expected: FAIL because existing `POST /api/admin/grants` accepts arbitrary resource IDs.

- [ ] **Step 3: Change service grant creation to validate first**

Change `AdminService.grant_access()` signature in `app/enterprise/admin/service.py`:

```python
    async def grant_access(self, context: RequestContext, request: GrantCreateRequest) -> ResourceGrant:
        preview = await self.preview_grant(request)
        if not preview.can_submit:
            failed_check = preview.failed_check or "grant_validation_failed"
            self._record_admin_operation(
                context,
                "grant_access_rejected",
                "grant",
                f"{request.resource_type}:{request.resource_id}",
                "failed",
                failed_check,
                metadata_extra={
                    "failed_check": failed_check,
                    "principal_type": request.principal_type.value,
                    "principal_id": request.principal_id,
                    "resource_type": request.resource_type,
                    "resource_id": request.resource_id,
                    "action": request.action,
                    "effect": request.effect.value,
                },
            )
            raise AdminError(f"Grant validation failed: {failed_check}")

        stored = self.permission_service.grant_access(ResourceGrant(**request.model_dump()))
        self._record_admin_operation(context, "grant_access", "grant", stored.grant_id)
        return stored
```

Update `_record_admin_operation()` to accept optional metadata:

```python
    def _record_admin_operation(
        self,
        context: RequestContext,
        operation: str,
        target_type: str,
        target_id: str,
        status: str = "success",
        reason: str | None = None,
        metadata_extra: dict | None = None,
    ) -> None:
        metadata = {
            "operation": operation,
            "target_type": target_type,
            "target_id": target_id,
            "status": status,
        }
        if metadata_extra:
            metadata.update(metadata_extra)
        self.audit_service.record(
            AuditEvent(
                event_type="admin_operation",
                route="admin",
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision="allowed" if status == "success" else "failed",
                reason=reason,
                metadata=metadata,
            )
        )
```

- [ ] **Step 4: Change route to await service and return 400 on validation failure**

Modify `app/enterprise/admin/routes.py`:

```python
@router.post("/grants")
async def grant_access(request: GrantCreateRequest, _admin: AdminUser):
    context = _require_context()
    try:
        grant = await admin_service.grant_access(context, request)
    except AdminError as exc:
        raise _not_found_or_bad_request(exc) from exc
    return success_payload({"grant": grant.model_dump(mode="json")})
```

- [ ] **Step 5: Run create-validation tests**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_enterprise_admin_e8.EnterpriseAdminE8Tests.test_grant_create_rejects_missing_resource_and_writes_failed_audit \
  tests.test_enterprise_admin_e8.EnterpriseAdminE8Tests.test_grant_create_rejects_duplicate_but_allows_direct_conflict_warning \
  -v
```

Expected: PASS.

## Task 4: Admin Console Resource Catalog And Preview Flow

**Files:**
- Modify: `static/admin-console.html`
- Modify: `static/admin-console.js`
- Test: `tests/test_assistant_frontend_optimization.py`

- [ ] **Step 1: Write failing frontend static tests**

Append this test to `tests/test_assistant_frontend_optimization.py`:

```python
    def test_admin_console_stage3_lite_uses_resources_actions_and_preview_before_save(self):
        static_root = Path(__file__).resolve().parents[1] / "static"
        html = (static_root / "admin-console.html").read_text(encoding="utf-8")
        js = (static_root / "admin-console.js").read_text(encoding="utf-8")

        self.assertIn("{ key: 'resources', label: '资源' }", js)
        self.assertIn("loadResources", js)
        self.assertIn("/admin/resources", js)
        self.assertIn("/admin/grant-preview", js)
        self.assertIn("selectedResource.actions_supported", js)
        self.assertIn("previewGrant", js)
        self.assertIn("grantPreview?.can_submit", js)
        self.assertIn("请先通过授权预览", js)
        self.assertIn("route === 'resources'", html)
        self.assertIn("actions_supported", html)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m unittest tests.test_assistant_frontend_optimization.AssistantFrontendOptimizationTests.test_admin_console_stage3_lite_uses_resources_actions_and_preview_before_save -v
```

Expected: FAIL because resources route and preview flow are not wired yet.

- [ ] **Step 3: Update route list and state**

Modify `static/admin-console.js`.

Change route keys:

```javascript
const routeKeys = ['overview', 'users', 'roles', 'resources', 'grants', 'reviews', 'audit'];
```

Add state fields in `data()`:

```javascript
resources: [],
grantPreview: null,
```

Add nav item:

```javascript
{ key: 'resources', label: '资源' },
```

Add computed properties:

```javascript
selectedResource() {
    return this.resources.find((resource) => resource.resource_id === this.forms.grant.resource_id) || null;
},
selectedResourceActions() {
    return this.selectedResource?.actions_supported || [];
},
grantCanSubmit() {
    return Boolean(this.grantPreview?.can_submit);
},
```

- [ ] **Step 4: Load resources**

Modify `loadRouteData(route)`:

```javascript
} else if (route === 'resources') {
    return this.loadResources();
}
```

Modify `loadOverview()` `Promise.all()` to include resources:

```javascript
this.loadResources(false),
```

Add method:

```javascript
async loadResources(setBusy = true) {
    if (setBusy) this.busy = true;
    try {
        const payload = await this.adminFetch('/admin/resources');
        this.resources = payload.data?.resources || [];
        if (!this.forms.grant.resource_id && this.resources.length > 0) {
            this.applyResourceToGrant(this.resources[0]);
        }
        return true;
    } catch (error) {
        this.showToast(error.message, 'error');
        return false;
    } finally {
        if (setBusy) this.busy = false;
    }
},
applyResourceToGrant(resource) {
    if (!resource) return;
    this.forms.grant.resource_type = resource.resource_type;
    this.forms.grant.resource_id = resource.resource_id;
    this.forms.grant.action = (resource.actions_supported || [])[0] || '';
    this.grantPreview = null;
},
onGrantResourceChanged() {
    const resource = this.selectedResource;
    if (resource) {
        this.applyResourceToGrant(resource);
    }
},
onGrantActionChanged() {
    this.grantPreview = null;
},
```

- [ ] **Step 5: Add preview method and create guard**

Add method:

```javascript
async previewGrant() {
    this.busy = true;
    try {
        const body = this.buildGrantPayload();
        const payload = await this.adminFetch('/admin/grant-preview', {
            method: 'POST',
            body: JSON.stringify(body),
        });
        this.grantPreview = payload.data || null;
        this.showToast(this.grantPreview?.can_submit ? '授权预览通过' : '授权预览未通过', this.grantPreview?.can_submit ? 'success' : 'error');
    } catch (error) {
        this.showToast(error.message, 'error');
    } finally {
        this.busy = false;
    }
},
buildGrantPayload() {
    const body = {
        resource_type: this.forms.grant.resource_type,
        resource_id: this.forms.grant.resource_id,
        action: this.forms.grant.action,
        principal_type: this.forms.grant.principal_type,
        principal_id: this.forms.grant.principal_id,
        effect: this.forms.grant.effect,
    };
    if (this.forms.grant.reason) {
        body.reason = this.forms.grant.reason;
    }
    return body;
},
```

Change `createGrant()` to guard on preview:

```javascript
if (!this.grantPreview?.can_submit) {
    this.showToast('请先通过授权预览', 'error');
    return;
}
```

Then use `this.buildGrantPayload()` instead of inline body construction.

After create success, reset preview:

```javascript
this.grantPreview = null;
```

- [ ] **Step 6: Update HTML grant form and resource page**

In `static/admin-console.html`, change the grant form resource/action fields to:

```html
<label class="ea-field">Resource
    <select v-model="forms.grant.resource_id" required @change="onGrantResourceChanged">
        <option v-for="resource in resources" :key="resource.resource_id" :value="resource.resource_id">
            {{ resource.resource_type }} · {{ resource.name }} · {{ resource.resource_id }}
        </option>
    </select>
</label>
<label class="ea-field">Action
    <select v-model="forms.grant.action" required @change="onGrantActionChanged">
        <option v-for="action in selectedResourceActions" :key="action" :value="action">{{ action }}</option>
    </select>
</label>
```

Add preview and save buttons:

```html
<button class="ea-btn" type="button" @click="previewGrant" :disabled="busy">预览</button>
<button class="ea-btn ea-btn-primary" type="submit" :disabled="busy || !grantPreview?.can_submit">保存 Grant</button>
```

Add preview panel below the form:

```html
<div v-if="grantPreview" class="admin-preview-panel">
    <h4>授权预览</h4>
    <p :class="grantPreview.can_submit ? 'admin-preview-ok' : 'admin-preview-blocked'">
        {{ grantPreview.can_submit ? '可以提交' : '不可提交' }}
    </p>
    <ul>
        <li v-for="check in grantPreview.checks" :key="check.check">
            <span class="ea-badge" :data-tone="check.status === 'passed' ? 'success' : (check.status === 'warning' ? 'warning' : 'danger')">
                {{ check.status }}
            </span>
            <strong>{{ check.check }}</strong>
            <span>{{ check.message }}</span>
            <code v-if="check.matched_grant_ids?.length">{{ check.matched_grant_ids.join(', ') }}</code>
        </li>
    </ul>
</div>
```

Add resources page section:

```html
<section v-if="route === 'resources'" class="admin-card">
    <div class="admin-card-header">
        <div>
            <h3>资源目录</h3>
            <p class="admin-section-note">第一版只列可权威枚举的 document、tool、database_table、database_column。</p>
        </div>
    </div>
    <div class="admin-table-wrap">
        <table class="ea-table">
            <thead><tr><th>类型</th><th>Resource ID</th><th>名称</th><th>actions_supported</th><th>说明</th><th>Metadata</th></tr></thead>
            <tbody>
                <tr v-for="resource in resources" :key="`${resource.resource_type}:${resource.resource_id}`">
                    <td>{{ resource.resource_type }}</td>
                    <td><code>{{ resource.resource_id }}</code></td>
                    <td>{{ resource.name }}</td>
                    <td>{{ (resource.actions_supported || []).join(', ') }}</td>
                    <td>{{ resource.description || '-' }}</td>
                    <td><pre>{{ compactJson(resource.metadata) }}</pre></td>
                </tr>
            </tbody>
        </table>
    </div>
</section>
```

- [ ] **Step 7: Run frontend static test and JS syntax check**

Run:

```bash
.venv/bin/python -m unittest tests.test_assistant_frontend_optimization.AssistantFrontendOptimizationTests.test_admin_console_stage3_lite_uses_resources_actions_and_preview_before_save -v
node --check static/admin-console.js
```

Expected: both PASS.

## Task 5: Documentation And Development Record

**Files:**
- Modify: `docs/助手优化 2.md`
- Modify: `docs/rag_fusion_development_record.md`

- [ ] **Step 1: Update `docs/助手优化 2.md` status**

Append a new section after the MVP status section:

```markdown
## 16. 2026-05-31 阶段 3-lite 实施状态

阶段 3-lite 的目标是让系统管理员不再靠手填猜测 `resource_id`，并让无效授权在写入前被后端拒绝。

已实现：

- `GET /api/admin/resources`：返回第一版 Resource Catalog。
- `POST /api/admin/grant-preview`：返回 preview-lite，不写 audit。
- `POST /api/admin/grants`：写入前复用同一套 validator。
- 管理后台“资源”页面。
- 管理后台授权表单从资源目录选择 `resource_id`，action 下拉从 `actions_supported` 获取。

第一版 Resource Catalog 硬规则：

- 只列 `document` / `tool` / `database_table` / `database_column`。
- `document` 只列 `document_status=indexed` 的文档；`pending` / `failed` / `unindexed` 不在目录里出现。
- 不返回独立 `kbs` 字段；知识库分组由前端根据 `document.metadata.kb_id` 完成。
- 不返回 `source` 字段。
- 不返回通用 `status` 字段。
- 不分页；单类资源数量超过 500 时再加分页参数。
- `database_table` / `database_column` 的 `resource_id` 复用 `database_table_resource_id()` / `database_column_resource_id()`。

preview-lite 检查：

- `resource_exists`：资源必须存在于 catalog。
- `action_supported`：action 必须来自资源的 `actions_supported`。
- `principal_exists`：user / role / department / public principal 必须存在或合法。
- `duplicate_grant`：同 6-tuple 重复 grant 阻断提交。
- `direct_conflict`：同 5-tuple 反向 effect 返回 warning，不阻断提交。

audit 行为：

- preview 是只读检查，不写 audit。
- create 成功仍写 `admin_operation`，`metadata.operation="grant_access"`。
- create 被 validator 拒绝时写 `admin_operation`，`decision="failed"`，`metadata.operation="grant_access_rejected"`，`metadata.failed_check=<check_name>`。

仍未做：

- 部门管理员 scoped admin。
- 权限申请。
- full grant preview 影响用户数计算。
- preview token / TTL。
- model endpoint 资源目录。
```

- [ ] **Step 2: Update development record with factual implementation summary**

Append to `docs/rag_fusion_development_record.md`:

```markdown
## 2026-05-31 - Assistant Optimization 2 Stage 3-lite Resource Catalog And Preview

背景:
- 管理后台 MVP 已能创建用户、角色、grant 和查询 audit，但授权仍依赖管理员手填 `resource_id`。
- 真实体验中已经暴露“用户不知道知识库有什么、管理员不知道可授权什么”的产品缺口。
- 阶段 3-lite 只处理可权威枚举资源、存在性校验、重复授权校验和直接 allow/deny 冲突提示，不做部门 scoped admin 和 full impact preview。

改动:
- 新增 `app/enterprise/admin/resources.py`，从 indexed documents、固定本地工具清单、sandbox database schema registry 枚举 catalog。
- 新增 `app/enterprise/admin/grant_validator.py`，实现 `resource_exists` / `action_supported` / `principal_exists` / `duplicate_grant` / `direct_conflict`。
- 新增 `GET /api/admin/resources` 和 `POST /api/admin/grant-preview`。
- 修改 `POST /api/admin/grants`，写入前复用 validator；失败写 `grant_access_rejected` audit。
- 修改 `static/admin-console.html` / `static/admin-console.js`，管理后台新增资源页，授权表单改为 catalog-backed resource/action 选择和 preview-first 流程。

关键边界:
- catalog 不返回 `kbs` / `source` / 通用 `status`。
- document 只列 `DocumentStatus.INDEXED`。
- database table / column resource_id 必须复用 E7 权限 helper。
- preview 不写 audit，create 失败写 audit。

验证:
- `.venv/bin/python -m unittest tests.test_enterprise_admin_e8 -v`
- `.venv/bin/python -m unittest tests.test_assistant_frontend_optimization -v`
- `node --check static/admin-console.js`
- `.venv/bin/python -m compileall -q app tests`
- `git diff --check`

面试解释:
- 这一步不是完整 IAM，而是把“管理员手填无效授权”的高频坑先封住。
- preview 只是提前解释结果，不是安全令牌；真正安全边界在 `POST /api/admin/grants` 里再次运行同一 validator。
```

- [ ] **Step 3: Verify documentation mentions the route conflict**

Run:

```bash
rg -n "grant-preview|grants/preview|grant_access_rejected|document_status=indexed" docs/助手优化\ 2.md docs/rag_fusion_development_record.md
```

Expected: output includes `/api/admin/grant-preview`, `grant_access_rejected`, and `document_status=indexed`.

## Task 6: Final Verification

**Files:**
- No new files beyond prior tasks.

- [ ] **Step 1: Run backend admin tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_enterprise_admin_e8 -v
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend optimization tests**

Run:

```bash
.venv/bin/python -m unittest tests.test_assistant_frontend_optimization -v
```

Expected: all tests pass.

- [ ] **Step 3: Run syntax checks**

Run:

```bash
node --check static/admin-console.js
.venv/bin/python -m compileall -q app tests
```

Expected: `node --check` exits 0 and `compileall` has no output.

- [ ] **Step 4: Run diff hygiene**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 5: Manual smoke test with running server**

If the server is already running on port 9900, reuse it. Otherwise start the existing project command the user has been using.

Login:

```bash
ADMIN_TOKEN=$(curl -s -X POST http://localhost:9900/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Admin123!"}' | jq -r '.data.access_token')
```

Catalog:

```bash
curl -s http://localhost:9900/api/admin/resources \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.data.resources[0:5]'
```

Preview missing resource:

```bash
curl -s -X POST http://localhost:9900/api/admin/grant-preview \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"resource_type":"document","resource_id":"doc_missing","action":"read","principal_type":"user","principal_id":"user_demo_dept1","effect":"allow"}' \
  | jq '.data'
```

Expected: `can_submit=false`, first check is `resource_exists failed`, no audit event is written for preview.

Create rejected grant:

```bash
curl -s -i -X POST http://localhost:9900/api/admin/grants \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Trace-Id: trace-stage3-lite-reject" \
  -d '{"resource_type":"document","resource_id":"doc_missing","action":"read","principal_type":"user","principal_id":"user_demo_dept1","effect":"allow"}'
```

Expected: HTTP 400 with `resource_exists` in `detail`.

Audit rejected grant:

```bash
curl -s "http://localhost:9900/api/admin/audit?event_type=admin_operation&trace_id=trace-stage3-lite-reject&limit=5" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  | jq '.data.events[] | {decision, reason, metadata}'
```

Expected: one event has `decision="failed"`, `metadata.operation="grant_access_rejected"`, and `metadata.failed_check="resource_exists"`.

## Self-Review Checklist

- [ ] Catalog does not include `kbs`, `source`, or generic `status`.
- [ ] Catalog document filter is hardcoded to `DocumentStatus.INDEXED`.
- [ ] Tool action comes from backend `actions_supported`.
- [ ] Database table and column resource IDs use existing helper functions.
- [ ] Preview uses `/api/admin/grant-preview`.
- [ ] Preview does not write audit.
- [ ] Create reruns the same validator.
- [ ] Create rejected grant writes failed `admin_operation`.
- [ ] Duplicate is 6-tuple and blocks.
- [ ] Direct conflict is 5-tuple with opposite effect and only warns.
- [ ] `principal_exists` covers user, role, department, and public.
- [ ] Department scoped admin, permission requests, and full grant preview are still explicitly out of scope.
