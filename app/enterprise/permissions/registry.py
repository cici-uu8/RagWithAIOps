"""Resource registries filtered through PermissionService."""

from app.enterprise.context import RequestContext
from app.enterprise.permissions.models import ResourceDescriptor
from app.enterprise.permissions.service import PermissionService, permission_service


class BaseResourceRegistry:
    resource_type: str
    default_action: str

    def __init__(self, permission_service: PermissionService | None = None):
        self.permission_service = permission_service or permission_service_default()
        self._resources: dict[str, ResourceDescriptor] = {}

    def register(self, resource: ResourceDescriptor) -> ResourceDescriptor:
        if resource.resource_type != self.resource_type:
            raise ValueError(
                f"Resource type mismatch: expected {self.resource_type}, "
                f"got {resource.resource_type}"
            )
        self._resources[resource.resource_id] = resource
        return resource

    def get(self, resource_id: str) -> ResourceDescriptor | None:
        return self._resources.get(resource_id)

    def list_all(self) -> list[ResourceDescriptor]:
        return list(self._resources.values())

    def list_visible(
        self,
        context: RequestContext,
        *,
        action: str | None = None,
    ) -> list[ResourceDescriptor]:
        return self.permission_service.filter_allowed(
            context,
            self.list_all(),
            action=action or self.default_action,
        )


class ToolRegistry(BaseResourceRegistry):
    resource_type = "tool"
    default_action = "use"


class DocumentAccessRegistry(BaseResourceRegistry):
    resource_type = "document"
    default_action = "read"


class ModelEndpointRegistry(BaseResourceRegistry):
    resource_type = "model_endpoint"
    default_action = "use"


def permission_service_default() -> PermissionService:
    return permission_service
