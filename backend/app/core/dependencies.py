"""
FastAPI dependencies for authentication.

Usage:
    from app.core.dependencies import get_current_user, require_role

    @router.get("/something")
    async def endpoint(user = Depends(get_current_user)):
        ...

    @router.post("/hr-only")
    async def endpoint(user = Depends(require_role("hr"))):
        ...
"""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from app.core.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    email: str
    name: str
    role: str  # "hr" | "hm"


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    """
    Extracts and validates the Bearer JWT from the Authorization header.
    Raises 401 if the token is missing, malformed, or expired.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(credentials.credentials)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return CurrentUser(
        email=payload["sub"],
        name=payload["name"],
        role=payload["role"],
    )


def require_role(*roles: str):
    """
    Returns a dependency that enforces the caller has one of the given roles.

    Example:
        Depends(require_role("hr", "hm"))   # either role allowed
        Depends(require_role("hr"))          # HR only
    """
    def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access restricted to: {', '.join(roles)}",
            )
        return user
    return _check