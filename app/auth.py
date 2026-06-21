from fastapi import Request
from fastapi.responses import JSONResponse
from app.errors import v1_error, v4_error
from typing import Optional


def require_auth(request: Request, surface: str = "v1") -> Optional[JSONResponse]:
    """Return an error response if the Authorization header is missing, else None."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        if surface == "v4":
            return v4_error(
                401,
                "Request is missing required authentication credential.",
                "authError",
            )
        return v1_error(
            401,
            "Request is missing required authentication credential.",
            "UNAUTHENTICATED",
        )
    return None
