import uuid
from datetime import date

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.employee import EmployeeStatus
from app.schemas.auth import UserOut, _validate_password_strength


class EmployeeCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role_name: str = Field(default="employee")
    department_id: uuid.UUID | None = None
    supervisor_id: uuid.UUID | None = None
    job_title: str = Field(default="", max_length=255)
    phone_number: str = Field(default="", max_length=50)
    hire_date: date

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)


class EmployeeUpdate(BaseModel):
    department_id: uuid.UUID | None = None
    supervisor_id: uuid.UUID | None = None
    job_title: str | None = Field(default=None, max_length=255)
    phone_number: str | None = Field(default=None, max_length=50)


class EmployeeStatusUpdate(BaseModel):
    status: EmployeeStatus


class EmployeeOut(BaseModel):
    id: uuid.UUID
    employee_code: str
    user: UserOut
    department_id: uuid.UUID | None
    supervisor_id: uuid.UUID | None
    job_title: str
    phone_number: str
    hire_date: date
    status: EmployeeStatus

    model_config = {"from_attributes": True}


class EmployeeListOut(BaseModel):
    items: list[EmployeeOut]
    total: int
    limit: int
    offset: int
