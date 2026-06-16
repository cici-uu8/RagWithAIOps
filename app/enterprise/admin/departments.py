"""Department model and seed scope for Stage 4 scoped admin."""

from __future__ import annotations

from pydantic import BaseModel, Field, computed_field


class DepartmentResourceRef(BaseModel):
    resource_type: str = Field(..., min_length=1)
    resource_id: str = Field(..., min_length=1)
    actions: list[str] = Field(default_factory=list)

    def allows(self, *, resource_type: str, resource_id: str, action: str | None = None) -> bool:
        if self.resource_type != resource_type or self.resource_id != resource_id:
            return False
        return action is None or action in self.actions


class DepartmentRecord(BaseModel):
    department_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    admin_user_ids: list[str] = Field(default_factory=list)
    manageable_resources: list[DepartmentResourceRef] = Field(default_factory=list)

    @computed_field
    @property
    def manageable_resource_types(self) -> list[str]:
        return sorted({resource.resource_type for resource in self.manageable_resources})

    @computed_field
    @property
    def manageable_resource_ids(self) -> list[str]:
        return sorted({resource.resource_id for resource in self.manageable_resources})


def _resource(resource_type: str, resource_id: str, action: str) -> DepartmentResourceRef:
    return DepartmentResourceRef(
        resource_type=resource_type,
        resource_id=resource_id,
        actions=[action],
    )


def _seed_departments() -> list[DepartmentRecord]:
    return [
        DepartmentRecord(
            department_id="dept_1",
            name="Department 1",
            manageable_resources=[
                _resource("tool", "retrieve_knowledge", "use"),
                _resource("tool", "list_knowledge_documents", "use"),
                _resource("database_table", "sandbox_sales.factory_access_events", "read"),
                _resource("database_column", "sandbox_sales.factory_access_events.event_id", "read"),
                _resource("database_column", "sandbox_sales.factory_access_events.employee_id", "read"),
                _resource("database_column", "sandbox_sales.factory_access_events.direction", "read"),
                _resource("database_column", "sandbox_sales.factory_access_events.event_time", "read"),
            ],
        ),
        DepartmentRecord(
            department_id="dept_2",
            name="Department 2",
            manageable_resources=[
                _resource("tool", "get_current_time", "use"),
                _resource("database_table", "sandbox_sales.building_access_events", "read"),
                _resource("database_column", "sandbox_sales.building_access_events.event_id", "read"),
                _resource("database_column", "sandbox_sales.building_access_events.employee_id", "read"),
                _resource("database_column", "sandbox_sales.building_access_events.building_name", "read"),
                _resource("database_column", "sandbox_sales.building_access_events.event_time", "read"),
            ],
        ),
        DepartmentRecord(
            department_id="system",
            name="System",
            manageable_resources=[],
        ),
    ]


class DepartmentService:
    def __init__(self, departments: list[DepartmentRecord] | None = None):
        self._seed_departments = [
            department.model_copy(deep=True)
            for department in (departments or _seed_departments())
        ]
        self.reset_departments()

    def reset_departments(self) -> None:
        self._departments = {
            department.department_id: department.model_copy(deep=True)
            for department in self._seed_departments
        }

    def list_departments(self) -> list[DepartmentRecord]:
        return [
            department.model_copy(deep=True)
            for department in sorted(self._departments.values(), key=lambda item: item.department_id)
        ]

    def get_department(self, department_id: str) -> DepartmentRecord | None:
        department = self._departments.get(department_id)
        return department.model_copy(deep=True) if department is not None else None

    def upsert_department(self, record: DepartmentRecord) -> DepartmentRecord:
        self._departments[record.department_id] = record.model_copy(deep=True)
        return self.get_department(record.department_id)  # type: ignore[return-value]

    def update_manageable_resources(
        self,
        department_id: str,
        resources: list[DepartmentResourceRef],
    ) -> DepartmentRecord:
        department = self._require_business_department(department_id)
        updated = department.model_copy(update={"manageable_resources": list(resources)}, deep=True)
        self._departments[department_id] = updated
        return updated.model_copy(deep=True)

    def assign_admin(self, department_id: str, user_id: str) -> DepartmentRecord:
        department = self._require_business_department(department_id)
        admin_user_ids = list(dict.fromkeys([*department.admin_user_ids, user_id]))
        updated = department.model_copy(update={"admin_user_ids": admin_user_ids}, deep=True)
        self._departments[department_id] = updated
        return updated.model_copy(deep=True)

    def manageable_resource_refs(self, department_id: str) -> list[DepartmentResourceRef]:
        department = self.get_department(department_id)
        return list(department.manageable_resources) if department is not None else []

    def _require_business_department(self, department_id: str) -> DepartmentRecord:
        department = self.get_department(department_id)
        if department is None:
            raise KeyError(f"Department not found: {department_id}")
        if department.department_id == "system":
            raise ValueError("System department resource scope is not configurable")
        return department


department_service = DepartmentService()
