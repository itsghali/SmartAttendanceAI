class DomainError(Exception):
    pass


class UserAlreadyExistsError(DomainError):
    pass


class InvalidCredentialsError(DomainError):
    pass


class UserInactiveError(DomainError):
    pass


class UserNotVerifiedError(DomainError):
    pass


class InvalidOTPError(DomainError):
    pass


class InvalidSignupCodeError(DomainError):
    pass


class InvalidRefreshTokenError(DomainError):
    pass


class PermissionDeniedError(DomainError):
    pass


class DepartmentAlreadyExistsError(DomainError):
    pass


class DepartmentNotFoundError(DomainError):
    pass


class EmployeeNotFoundError(DomainError):
    pass


class InvalidRoleError(DomainError):
    pass


class SelfSupervisionError(DomainError):
    pass


class GeofenceNotFoundError(DomainError):
    pass


class PolygonInvalidError(DomainError):
    pass


class AttendanceNotFoundError(DomainError):
    pass


class NoActiveGeofenceError(DomainError):
    pass


class OutsideGeofenceError(DomainError):
    pass


class PoorLocationAccuracyError(DomainError):
    pass


class MockLocationDetectedError(DomainError):
    pass


class ImpossibleTravelError(DomainError):
    pass


class AlreadyCheckedInError(DomainError):
    pass


class NotCheckedInError(DomainError):
    pass


class AlreadyCheckedOutError(DomainError):
    pass


class BreakAlreadyActiveError(DomainError):
    pass


class NoActiveBreakError(DomainError):
    pass


class BreakStillActiveError(DomainError):
    pass


class InvalidImageError(DomainError):
    pass


class NoFaceDetectedError(DomainError):
    pass


class MultipleFacesDetectedError(DomainError):
    pass


class FaceModelUnavailableError(DomainError):
    pass


class FaceProfileNotFoundError(DomainError):
    pass


class FaceProfileCorruptedError(DomainError):
    pass


class FaceMismatchError(DomainError):
    pass


class LivenessCheckFailedError(DomainError):
    pass
