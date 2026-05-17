"""
Auth routes — login, password reset, JWT validation, and active-session persistence.

All protected routes require a valid JWT issued by /auth/login.
Active session state is stored in Redis (30-day TTL) rather than browser localStorage
so it survives page refreshes and cross-device sessions.
"""

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.core.redis import get_active_session, set_active_session, clear_active_session
from app.core.security import decrypt_email, hash_email, verify_password, create_access_token
from app.db.models import User
from app.services.email_sender import send_password_reset_email

router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: str
    name: str
    role: str


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    # Look up by blind index — no table scan, no decryption needed for lookup
    digest = hash_email(request.email)
    result = await db.execute(select(User).where(User.email_hash == digest))
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    email = decrypt_email(user.email_encrypted)
    token = create_access_token(email=email, name=user.name, role=user.role)

    return LoginResponse(
        access_token=token,
        email=email,
        name=user.name,
        role=user.role,
    )


class ForgotPasswordRequest(BaseModel):
    email: str


@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """
    Accepts an email and returns 200 regardless of whether the account exists
    (prevents user enumeration). In production this would send a reset email.
    """
    digest = hash_email(request.email)
    result = await db.execute(select(User).where(User.email_hash == digest))
    user = result.scalar_one_or_none()

    if user:
        # Reuse JWT infrastructure as a short-lived reset token rather than a separate token store
        reset_token = create_access_token(
            email=request.email, name="", role="reset", expires_minutes=30
        )
        try:
            await send_password_reset_email(to=request.email, reset_token=reset_token)
        except Exception as exc:
            logger.error(f"Failed to send password reset email to {request.email}: {exc}")
        logger.info(f"Password reset email dispatched for user id={user.id}")

    # Always return the same response to prevent email enumeration
    return {"message": "If that email is registered, a reset link has been sent."}


@router.get("/me", response_model=dict)
async def me(user: CurrentUser = Depends(get_current_user)):
    """Returns the authenticated user's profile. Useful for token validation on page load."""
    return {"email": user.email, "name": user.name, "role": user.role}


class ActiveSessionIn(BaseModel):
    session_id: str


@router.put("/active-session")
async def save_active_session(
    body: ActiveSessionIn,
    user: CurrentUser = Depends(get_current_user),
):
    """Persist the user's last active JD session in Redis (30-day TTL)."""
    await set_active_session(user.email, body.session_id)
    return {"ok": True}


@router.get("/active-session")
async def load_active_session(user: CurrentUser = Depends(get_current_user)):
    """Return the user's last active session_id, or null if none stored."""
    session_id = await get_active_session(user.email)
    return {"session_id": session_id}


@router.delete("/active-session")
async def delete_active_session(user: CurrentUser = Depends(get_current_user)):
    """Clear the stored active session (called on logout or New JD)."""
    await clear_active_session(user.email)
    return {"ok": True}