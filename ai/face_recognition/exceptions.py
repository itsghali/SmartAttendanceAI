"""Pipeline-level errors. Framework-agnostic on purpose — this package knows
nothing about FastAPI or the backend's DomainError hierarchy. The backend's
face_service.py catches these and re-raises its own named DomainError
subclasses (see backend/app/core/exceptions.py)."""


class PipelineError(Exception):
    pass


class PipelineInvalidImageError(PipelineError):
    pass


class PipelineNoFaceError(PipelineError):
    pass


class PipelineMultiFaceError(PipelineError):
    pass


class PipelineModelUnavailableError(PipelineError):
    pass
