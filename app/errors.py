from fastapi.responses import JSONResponse
from typing import Optional, List


def v1_error(
    status_code: int,
    message: str,
    status: str,
    details: Optional[List] = None,
) -> JSONResponse:
    """Modern error envelope — Account Management, Business Information, Notifications APIs (v1)."""
    body: dict = {"error": {"code": status_code, "message": message, "status": status}}
    if details:
        body["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=body)


def v4_error(
    status_code: int,
    message: str,
    reason: str,
    domain: str = "global",
) -> JSONResponse:
    """Legacy error envelope — Reviews API (v4)."""
    body = {
        "error": {
            "errors": [{"domain": domain, "reason": reason, "message": message}],
            "code": status_code,
            "message": message,
        }
    }
    return JSONResponse(status_code=status_code, content=body)
