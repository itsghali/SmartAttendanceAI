from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SmartAttendanceAI"
    environment: str = Field(default="development")
    debug: bool = Field(default=False)

    database_url: str = Field(default="postgresql+asyncpg://postgres:postgres@localhost:55432/smartattendance")
    redis_url: str = Field(default="redis://localhost:6379/0")

    jwt_secret_key: str = Field(default="change-me-in-.env")
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    smtp_host: str | None = Field(default=None)
    smtp_port: int = Field(default=587)
    smtp_username: str | None = Field(default=None)
    smtp_password: str | None = Field(default=None)
    smtp_use_tls: bool = Field(default=True)
    from_email: str = Field(default="noreply@smartattendance.local")

    otp_expire_minutes: int = Field(default=10)

    # Gates self-service admin/hr/super_admin signup (web dashboard only —
    # mobile signup always defaults to the "employee" role and never checks
    # this). Unset/empty means privileged signup is hard-disabled: register()
    # rejects every request that names a role, never falling open. Set via
    # env var ADMIN_SIGNUP_CODE, shared out-of-band with whoever should be
    # able to create HR/Admin/SuperAdmin accounts.
    admin_signup_code: str | None = Field(default=None)

    attendance_max_accuracy_meters: float = Field(default=100.0)

    # Continuous geofence monitoring (see PLAN.md Phase 3 Eng Section 1 finding 6).
    geofence_ping_interval_seconds: int = Field(default=60)
    geofence_exit_debounce_count: int = Field(default=3)
    location_ping_rate_limit_per_window: int = Field(default=10)
    location_ping_rate_limit_window_seconds: int = Field(default=60)
    # check-in/check-out/break start/end — far less frequent than pings, but
    # unbounded a compromised token could still hammer the geofence-match path.
    attendance_action_rate_limit_per_window: int = Field(default=20)
    attendance_action_rate_limit_window_seconds: int = Field(default=60)

    # GPS-spoof detection (see PLAN.md T1 — approved to block, not just log).
    # Both checks run on check-in only, before face verification (cheap before
    # expensive) and before the check-in row is created (fail closed).
    mock_location_check_enabled: bool = Field(default=True)
    impossible_travel_check_enabled: bool = Field(default=True)
    impossible_travel_max_speed_kmh: float = Field(default=120.0)
    # Below this, a real ping-rate elapsed time is too close to GPS-jitter
    # scale to judge — a few meters of accuracy noise over a few seconds of
    # elapsed time can compute an inflated speed with a genuinely ~0 distance
    # double-submit. The check is skipped entirely below this floor, not
    # loosened — see PLAN.md Eng review, item 1 edge cases.
    impossible_travel_min_elapsed_minutes: float = Field(default=5.0)

    # Face recognition (standalone enrollment + verification, not yet wired into
    # check-in — see TODOS.md "Face Enrollment + Face-Gated Check-in"). Kill switch
    # lets the endpoints be disabled without a redeploy if the model misbehaves.
    face_verification_enabled: bool = Field(default=False)
    # Cosine similarity cutoff for a match. Starting point only — unvalidated
    # against field conditions (lighting, angle, masks); pilot-test before
    # trusting this value in production.
    face_similarity_threshold: float = Field(default=0.6)
    face_liveness_threshold: float = Field(default=0.5)
    face_max_upload_size_mb: float = Field(default=5.0)
    face_enrollment_min_photos: int = Field(default=1)
    face_enrollment_max_photos: int = Field(default=5)
    # User-keyed (not IP-keyed rate_limit()'s factory — see
    # attendance_action_rate_limit_per_window's identical rationale: IP is
    # unreliable for mobile clients and NAT/shared-WiFi both under- and
    # over-throttles). /face/verify is callable by any authenticated employee
    # directly (not just via check-in) and runs a CPU-bound ONNX pipeline per
    # call, so it needs the same protection check-in already has.
    face_action_rate_limit_per_window: int = Field(default=10)
    face_action_rate_limit_window_seconds: int = Field(default=60)

    # Free-text employee-submitted problem reports — infrequent by nature, so
    # a tighter window than the action endpoints above is enough to stop
    # spam without ever bothering a genuine user.
    problem_report_rate_limit_per_window: int = Field(default=5)
    problem_report_rate_limit_window_seconds: int = Field(default=300)

    # Application-layer encryption for FaceProfile.embedding at rest (see
    # PLAN.md item 5). Newest key first — encryption always uses the first
    # key; decryption tries each in order, so rotation is "prepend a new key,
    # keep the old one" with no forced re-encryption migration. The default
    # is an obviously-fake placeholder (same convention as jwt_secret_key's
    # "change-me-in-.env"), guarded against in production at boot (main.py).
    face_embedding_encryption_keys: list[str] = Field(
        default_factory=lambda: ["24xm4P3u0ka-ik3EZdt9dX8M1t-Rb3YAMoUeXD6x1ow="]
    )

    # Workforce-intelligence daily automation (app/core/scheduler.py):
    # rebuilds baselines + runs detection for every active/on-leave employee
    # on a schedule, and gives an employee with zero attendance history a
    # one-time synthetic bootstrap corpus first (this system's only
    # bootstrap data source per PLAN.md — see
    # AttendanceRepository.list_for_baseline_including_synthetic's
    # docstring). Supersedes the Admin-actions panel as the default path;
    # that panel still works for on-demand re-runs. Single-container
    # deploy (Dockerfile runs one uvicorn process, no --workers) — this is
    # an in-process scheduler, not a distributed lock; running multiple
    # backend replicas would fire this job once per replica (harmless
    # today since rebuild/detect overwrite idempotently and synthetic
    # backfill is idempotency-key-guarded, but wasteful).
    workforce_intelligence_auto_schedule: bool = Field(default=True)
    workforce_intelligence_schedule_hour_utc: int = Field(default=2)

    # Kill switch for the email channel specifically (app/services/
    # notification_service.py), independent of smtp_host being set — dev/CI
    # can leave this on with no SMTP configured (falls back to
    # ConsoleEmailBackend, which logs instead of sending) or turn it off
    # outright without touching SMTP config. The in-app notification record
    # is created either way (see NotificationService.notify_new_flags) —
    # this only gates the external email send.
    workforce_intelligence_email_notifications_enabled: bool = Field(default=True)

    # Base URL the web dashboard is served from, used only to build the
    # "View details" deep link in notification emails
    # (ai/workforce_intelligence/insights/generator.py's render_email).
    frontend_base_url: str = Field(default="http://localhost:3000")


@lru_cache
def get_settings() -> Settings:
    return Settings()
