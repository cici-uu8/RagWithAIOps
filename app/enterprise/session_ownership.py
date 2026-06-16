"""In-memory ownership guard for user session history."""


class SessionOwnershipError(PermissionError):
    pass


class SessionOwnershipService:
    def __init__(self):
        self._owners_by_session_id: dict[str, str] = {}

    def claim_or_assert_owner(self, session_id: str, user_id: str) -> None:
        session_id = self._require_text(session_id, "session_id")
        user_id = self._require_text(user_id, "user_id")
        owner_id = self._owners_by_session_id.get(session_id)
        if owner_id is not None and owner_id != user_id:
            raise SessionOwnershipError("Session belongs to another user")
        self._owners_by_session_id[session_id] = user_id

    def assert_owner(self, session_id: str, user_id: str) -> None:
        session_id = self._require_text(session_id, "session_id")
        user_id = self._require_text(user_id, "user_id")
        owner_id = self._owners_by_session_id.get(session_id)
        if owner_id != user_id:
            raise SessionOwnershipError("Session belongs to another user")

    def release_for_owner(self, session_id: str, user_id: str) -> None:
        self.assert_owner(session_id, user_id)
        self._owners_by_session_id.pop(session_id, None)

    def clear(self) -> None:
        self._owners_by_session_id.clear()

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise SessionOwnershipError(f"{field_name} is required")
        return value.strip()


session_ownership_service = SessionOwnershipService()
