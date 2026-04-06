"""Consistent API error envelope for OpenAPI and clients."""

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field


class ApiErrorEnvelope(BaseModel):
    """Standard error body for all non-2xx responses."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "code": "not_found",
                    "message": "deployment not found",
                    "category": "client_error",
                    "details": None,
                }
            ]
        }
    )

    code: str = Field(description="Stable machine-readable error code")
    message: str = Field(description="Human-readable message safe to display")
    category: str = Field(
        default="",
        description="Error category: client_error, server_error, auth_error, rate_limit, queue_full, circuit_open, etc.",
    )
    details: Any | None = Field(
        default=None,
        description="Optional structured detail (validation errors, hints, last_error_type context)",
    )


def raise_api_error(
    *,
    status_code: int,
    code: str,
    message: str,
    category: str = "client_error",
    details: Any | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    """Raise HTTPException with envelope-shaped detail (handled by global exception handler)."""
    raise HTTPException(
        status_code=status_code,
        detail=ApiErrorEnvelope(code=code, message=message, category=category, details=details).model_dump(),
        headers=headers,
    )
