from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class AppException(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    detail = "An unexpected error occurred."

    def __init__(self, detail: str | None = None):
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class UnauthorizedException(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Not authenticated."


class ForbiddenException(AppException):
    status_code = status.HTTP_403_FORBIDDEN
    detail = "Not authorized to perform this action."


class NotFoundException(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    detail = "Resource not found."


class ConflictException(AppException):
    status_code = status.HTTP_409_CONFLICT
    detail = "Conflicting state."


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppException, app_exception_handler)
