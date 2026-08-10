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

# A misconfigured deploy that forgets to set JWT_SECRET_KEY must fail loudly
# at boot, not silently sign every access token with a value anyone can read
# in this repo's source.
if settings.environment == "production" and (
    settings.jwt_secret_key == "change-me-in-.env" or len(settings.jwt_secret_key) < 32
):
    raise RuntimeError(
        "JWT_SECRET_KEY is unset or too short for a production deploy — "
        "set a random secret of at least 32 characters."
    )

# Same reasoning as the JWT guard above — the default embedding-encryption
# key is a fixed, obviously-fake placeholder committed in this repo's
# source; using it in production would mean biometric embeddings are
# encrypted with a key anyone can read from GitHub, not a real control.
_DEFAULT_FACE_EMBEDDING_KEY = "24xm4P3u0ka-ik3EZdt9dX8M1t-Rb3YAMoUeXD6x1ow="
if settings.environment == "production" and (
    not settings.face_embedding_encryption_keys
    or _DEFAULT_FACE_EMBEDDING_KEY in settings.face_embedding_encryption_keys
):
    raise RuntimeError(
        "FACE_EMBEDDING_ENCRYPTION_KEYS is unset or still contains the default "
        "placeholder key for a production deploy — set at least one real "
        "Fernet key (Fernet.generate_key())."
    )

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
