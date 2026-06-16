"""Storage models for enterprise upload boundaries."""

from pydantic import BaseModel


class StoredObject(BaseModel):
    storage_uri: str
    local_path: str
    provider: str = "local"
    relative_path: str
