import uuid

from pydantic import BaseModel, Field, model_validator

from app.models.geofence import GeofenceBoundaryType

_MIN_POLYGON_POINTS = 3


class PolygonPoint(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class GeofenceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    department_id: uuid.UUID | None = None
    boundary_type: GeofenceBoundaryType = GeofenceBoundaryType.CIRCLE
    center_latitude: float | None = Field(default=None, ge=-90, le=90)
    center_longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_meters: float | None = Field(default=None, gt=0, le=50000)
    polygon_points: list[PolygonPoint] | None = None

    @model_validator(mode="after")
    def _check_boundary_fields(self) -> "GeofenceCreate":
        if self.boundary_type == GeofenceBoundaryType.CIRCLE:
            if self.center_latitude is None or self.center_longitude is None or self.radius_meters is None:
                raise ValueError(
                    "circle geofences require center_latitude, center_longitude, and radius_meters"
                )
        elif self.polygon_points is None or len(self.polygon_points) < _MIN_POLYGON_POINTS:
            raise ValueError(f"polygon geofences require at least {_MIN_POLYGON_POINTS} points")
        return self


class GeofenceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    department_id: uuid.UUID | None = None
    boundary_type: GeofenceBoundaryType | None = None
    center_latitude: float | None = Field(default=None, ge=-90, le=90)
    center_longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_meters: float | None = Field(default=None, gt=0, le=50000)
    polygon_points: list[PolygonPoint] | None = None
    is_active: bool | None = None


class GeofenceOut(BaseModel):
    id: uuid.UUID
    name: str
    department_id: uuid.UUID | None
    boundary_type: GeofenceBoundaryType
    center_latitude: float | None
    center_longitude: float | None
    radius_meters: float | None
    polygon_points: list[PolygonPoint] | None
    is_active: bool

    model_config = {"from_attributes": True}


class GeofenceListOut(BaseModel):
    items: list[GeofenceOut]
    total: int
    limit: int
    offset: int


class EmployeeGeofenceOut(BaseModel):
    id: uuid.UUID
    employee_code: str
    full_name: str
    job_title: str

    model_config = {"from_attributes": True}


class EmployeeGeofenceListOut(BaseModel):
    items: list[EmployeeGeofenceOut]
