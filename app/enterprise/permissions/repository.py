"""Local governance-data repository for E3.

This repository intentionally covers only enterprise governance grants. It does
not wrap legacy RAG, Memory, or upload SQLite stores.
"""

from app.enterprise.permissions.models import ResourceGrant


class InMemoryGovernanceRepository:
    def __init__(self, grants: list[ResourceGrant] | None = None):
        self._grants: dict[str, ResourceGrant] = {}
        for grant in grants or []:
            self.add_grant(grant)

    def add_grant(self, grant: ResourceGrant) -> ResourceGrant:
        self._grants[grant.grant_id] = grant
        return grant

    def get_grant(self, grant_id: str) -> ResourceGrant | None:
        return self._grants.get(grant_id)

    def revoke_grant(self, grant_id: str) -> bool:
        return self._grants.pop(grant_id, None) is not None

    def list_grants(
        self,
        *,
        resource_type: str,
        resource_id: str,
        action: str,
    ) -> list[ResourceGrant]:
        return [
            grant
            for grant in self._grants.values()
            if grant.resource_type == resource_type
            and grant.resource_id == resource_id
            and grant.action == action
        ]

    def list_all_grants(
        self,
        *,
        resource_type: str | None = None,
        resource_id: str | None = None,
        action: str | None = None,
        principal_type: str | None = None,
        principal_id: str | None = None,
    ) -> list[ResourceGrant]:
        return [
            grant
            for grant in self._grants.values()
            if (resource_type is None or grant.resource_type == resource_type)
            and (resource_id is None or grant.resource_id == resource_id)
            and (action is None or grant.action == action)
            and (principal_type is None or grant.principal_type == principal_type)
            and (principal_id is None or grant.principal_id == principal_id)
        ]

    def clear(self) -> None:
        self._grants.clear()
