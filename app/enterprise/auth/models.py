"""Enterprise E1 local identity models."""

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UserProfile(BaseModel):
    user_id: str
    username: str
    department_id: str
    department_name: str
    roles: list[str]
    is_active: bool = True


class SeedUser(UserProfile):
    password: str

    def to_profile(self) -> UserProfile:
        return UserProfile(
            user_id=self.user_id,
            username=self.username,
            department_id=self.department_id,
            department_name=self.department_name,
            roles=list(self.roles),
            is_active=self.is_active,
        )


class TokenPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sub: str
    username: str
    department_id: str
    department_name: str
    roles: list[str]
    jti: str
    iat: int
    iat_ms: int | None = None
    exp: int
