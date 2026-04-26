from collections.abc import Mapping


class AppError(Exception):
    code = "internal_error"
    http_status = 500

    def __init__(self, message: str, details: Mapping[str, object] | None = None):
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})


class NotFoundError(AppError):
    code = "not_found"
    http_status = 404


class ValidationAppError(AppError):
    code = "validation_error"
    http_status = 422


class AuthRequiredError(AppError):
    code = "auth_required"
    http_status = 401


class ForbiddenError(AppError):
    code = "forbidden"
    http_status = 403


class ConflictError(AppError):
    code = "conflict"
    http_status = 409
