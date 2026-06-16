"""JWT creation and validation for the local E1 auth provider."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError
from pydantic import ValidationError

from app.config import config
from app.enterprise.auth.models import TokenPayload, UserProfile


class JwtError(ValueError):
    pass


class JwtExpiredError(JwtError):
    pass


class JwtHandler:
    def __init__(
        self,
        secret_key: str | None = None,
        algorithm: str | None = None,
        access_token_expire_minutes: int | None = None,
    ):
        self.secret_key = secret_key or config.jwt_secret_key
        self.algorithm = algorithm or config.jwt_algorithm
        self.access_token_expire_minutes = (
            access_token_expire_minutes
            if access_token_expire_minutes is not None
            else config.jwt_access_token_expire_minutes
        )

    def create_access_token(
        self,
        user: UserProfile,
        expires_delta_seconds: int | None = None,
    ) -> str:
        now = datetime.now(UTC)
        lifetime_seconds = (
            expires_delta_seconds
            if expires_delta_seconds is not None
            else self.access_token_expire_minutes * 60
        )
        expires_at = now + timedelta(seconds=lifetime_seconds)
        payload = {
            "sub": user.user_id,
            "username": user.username,
            "department_id": user.department_id,
            "department_name": user.department_name,
            "roles": list(user.roles),
            "jti": str(uuid4()),
            "iat": int(now.timestamp()),
            "iat_ms": int(now.timestamp() * 1000),
            "exp": expires_at,
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def decode_access_token(self, token: str) -> TokenPayload:
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                options={"require": ["sub", "jti", "exp"]},
            )
            return TokenPayload.model_validate(payload)
        except ExpiredSignatureError as exc:
            raise JwtExpiredError("Token has expired") from exc
        except (InvalidTokenError, ValidationError) as exc:
            raise JwtError("Could not validate token") from exc
