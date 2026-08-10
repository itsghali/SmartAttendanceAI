import uuid

from pydantic import BaseModel, Field


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=1000)
    manager_id: uuid.UUID | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    manager_id: uuid.UUID | None = None


class DepartmentOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    manager_id: uuid.UUID | None

    model_config = {"from_attributes": True}
