from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import get_settings
from app.core.logging_config import configure_logging
from app.routes import (
    attendance,
    auth,
    departments,
    devices,
    employees,
    face,
    geofences,
    health,
    sessions,
)

configure_logging()
settings = get_settings()

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(devices.router)
app.include_router(sessions.router)
app.include_router(departments.router)
app.include_router(employees.router)
app.include_router(geofences.router)
app.include_router(attendance.router)
app.include_router(face.router)
