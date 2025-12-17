from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from typing import Union
from slowapi.errors import RateLimitExceeded


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Custom exception handler to ensure all HTTP errors use 'msg' instead of 'detail'"""
    message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"message": message},
        headers=getattr(exc, "headers", None),
    )


async def pydantic_validation_exception_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """Handle Pydantic ValidationError with only missing required field names"""
    missing_fields = []
    for error in exc.errors():
        if error["type"] == "missing":
            field = ".".join(str(loc) for loc in error["loc"])
            missing_fields.append(field)
    if not missing_fields:
        # fallback to all error fields if none are strictly 'missing'
        missing_fields = [".".join(str(loc) for loc in error["loc"]) for error in exc.errors()]
    # Only show the first missing field if that's preferred, else join all
    # To show only the first, uncomment the next line and comment the join below
    # return JSONResponse(status_code=422, content={"msg": f"{missing_fields[0]} is required"})
    return JSONResponse(status_code=422, content={"message": f"Missing required fields: {', '.join(missing_fields)}"})


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle general exceptions with consistent 'msg' format"""
    return JSONResponse(
        status_code=500,
        content={"message": "Internal server error"},
    )


async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={
            "message": "You have exceeded the allowed request limit. Please try again later.",
        },
    )