import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.shared.helpers import utc_now

logger = logging.getLogger(__name__)

ValidationErrors = dict[str, dict[str, list[str]]]


def build_error_response(
    request: Request,
    status_code: int,
    message: str,
    errors: ValidationErrors | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    timestamp = utc_now().isoformat()
    return JSONResponse(
        status_code=status_code,
        content={
            "path": request.url.path,
            "timestamp": timestamp,
            "message": message,
            "errors": errors,
        },
        headers=headers,
    )


def group_validation_errors(exception: RequestValidationError) -> ValidationErrors:
    errors: ValidationErrors = {}
    for error in exception.errors():
        location = error.get("loc", ())
        source = str(location[0]) if location else "body"
        field = ".".join(str(part) for part in location[1:]) or ""
        errors.setdefault(source, {}).setdefault(field, []).append(str(error["msg"]))
    return errors


def request_validation_exception_handler(
    request: Request, exception: RequestValidationError
) -> JSONResponse:
    return build_error_response(
        request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        message="Request validation failed",
        errors=group_validation_errors(exception),
    )


def http_exception_handler(request: Request, exception: StarletteHTTPException) -> JSONResponse:
    return build_error_response(
        request,
        status_code=exception.status_code,
        message=str(exception.detail),
        headers=exception.headers,
    )


def unhandled_exception_handler(request: Request, exception: Exception) -> JSONResponse:
    logger.exception("Unhandled exception at %s", request.url.path)
    return build_error_response(
        request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        message="Internal server error",
    )


def install_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)
