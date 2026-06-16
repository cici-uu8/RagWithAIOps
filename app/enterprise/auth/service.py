"""Local AuthService for Gateway-MVP E1."""

from datetime import UTC, datetime
from secrets import compare_digest

from app.enterprise.auth.jwt_handler import JwtError, JwtHandler
from app.enterprise.auth.models import SeedUser, TokenPayload, UserProfile
from app.enterprise.auth.seed import SEED_USERS_BY_USERNAME


class AuthError(ValueError):
    pass


class AuthService:
    def __init__(
        self,
        users_by_username: dict[str, SeedUser] | None = None,
        jwt_handler: JwtHandler | None = None,
    ):
        self._seed_users_by_username = users_by_username or SEED_USERS_BY_USERNAME
        self._users_by_username: dict[str, SeedUser] = {}
        self._users_by_id: dict[str, SeedUser] = {}
        self._jwt_handler = jwt_handler or JwtHandler()
        self._blacklisted_jtis: dict[str, int] = {}
        self._token_invalid_after_by_user_id: dict[str, int] = {}
        self.reset_users()

    def authenticate(self, username: str, password: str) -> UserProfile:
        user = self._users_by_username.get(username)
        expected_password = user.password if user else ""
        if not user or not compare_digest(password, expected_password):
            raise AuthError("Invalid username or password")
        if not user.is_active:
            raise AuthError("User is disabled")
        return user.to_profile()

    def create_access_token(
        self,
        user: UserProfile,
        expires_delta_seconds: int | None = None,
    ) -> str:
        return self._jwt_handler.create_access_token(
            user,
            expires_delta_seconds=expires_delta_seconds,
        )

    def validate_access_token(self, token: str) -> tuple[UserProfile, TokenPayload]:
        try:
            payload = self._jwt_handler.decode_access_token(token)
        except JwtError as exc:
            raise AuthError(str(exc)) from exc

        self._purge_expired_blacklist_entries()
        if payload.jti in self._blacklisted_jtis:
            raise AuthError("Token is blacklisted")

        invalid_after = self._token_invalid_after_by_user_id.get(payload.sub)
        if invalid_after is not None:
            issued_at = payload.iat_ms if payload.iat_ms is not None else payload.iat * 1000
            if issued_at <= invalid_after:
                raise AuthError("Token is stale")

        user = self._users_by_id.get(payload.sub)
        if user is None:
            raise AuthError("User not found")
        if not user.is_active:
            raise AuthError("User is disabled")

        return user.to_profile(), payload

    def blacklist_token(self, token: str) -> TokenPayload:
        try:
            payload = self._jwt_handler.decode_access_token(token)
        except JwtError as exc:
            raise AuthError(str(exc)) from exc
        self._blacklisted_jtis[payload.jti] = payload.exp
        return payload

    def clear_blacklist(self) -> None:
        self._blacklisted_jtis.clear()
        self._token_invalid_after_by_user_id.clear()

    def reset_users(self) -> None:
        self._users_by_username = {
            username: user.model_copy(deep=True)
            for username, user in self._seed_users_by_username.items()
        }
        self._users_by_id = {
            user.user_id: user for user in self._users_by_username.values()
        }
        self._token_invalid_after_by_user_id.clear()

    def invalidate_tokens_for_user(self, user_id: str) -> int:
        invalid_after = int(datetime.now(UTC).timestamp() * 1000)
        self._token_invalid_after_by_user_id[user_id] = invalid_after
        return invalid_after

    def list_users(self) -> list[UserProfile]:
        return [
            user.to_profile()
            for user in sorted(self._users_by_id.values(), key=lambda item: item.username)
        ]

    def create_user(
        self,
        *,
        user_id: str,
        username: str,
        password: str,
        department_id: str,
        department_name: str,
        roles: list[str],
    ) -> UserProfile:
        if user_id in self._users_by_id:
            raise AuthError("User id already exists")
        if username in self._users_by_username:
            raise AuthError("Username already exists")
        user = SeedUser(
            user_id=user_id,
            username=username,
            password=password,
            department_id=department_id,
            department_name=department_name,
            roles=list(roles),
            is_active=True,
        )
        self._users_by_username[username] = user
        self._users_by_id[user_id] = user
        return user.to_profile()

    def update_user(
        self,
        user_id: str,
        *,
        username: str | None = None,
        password: str | None = None,
        department_id: str | None = None,
        department_name: str | None = None,
        roles: list[str] | None = None,
        is_active: bool | None = None,
    ) -> UserProfile:
        user = self._users_by_id.get(user_id)
        if user is None:
            raise AuthError("User not found")

        if username is not None and username != user.username:
            if username in self._users_by_username:
                raise AuthError("Username already exists")
            del self._users_by_username[user.username]
            user.username = username
            self._users_by_username[username] = user
        if password is not None:
            user.password = password
        if department_id is not None:
            user.department_id = department_id
        if department_name is not None:
            user.department_name = department_name
        if roles is not None:
            user.roles = list(roles)
        if is_active is not None:
            user.is_active = is_active
        return user.to_profile()

    def disable_user(self, user_id: str) -> UserProfile:
        return self.update_user(user_id, is_active=False)

    def _purge_expired_blacklist_entries(self) -> None:
        now = int(datetime.now(UTC).timestamp())
        expired_jtis = [
            jti for jti, expires_at in self._blacklisted_jtis.items() if expires_at <= now
        ]
        for jti in expired_jtis:
            del self._blacklisted_jtis[jti]


auth_service = AuthService()
