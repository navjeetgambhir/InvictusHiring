from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, CurrentUser
from app.core.security import decrypt_email, hash_email, verify_password, create_access_token
from app.db.models import User

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
    from app.core.security import hash_email
    digest = hash_email(request.email)
    result = await db.execute(select(User).where(User.email_hash == digest))
    user = result.scalar_one_or_none()

    if user:
        # Production: generate a signed reset token and email it.
        # For now, log the intent so it's visible in server logs.
        from loguru import logger
        logger.info(f"Password reset requested for user id={user.id}")

    # Always return the same response to prevent email enumeration
    return {"message": "If that email is registered, a reset link has been sent."}


@router.get("/me", response_model=dict)
async def me(user: CurrentUser = Depends(get_current_user)):
    """Returns the authenticated user's profile. Useful for token validation on page load."""
    return {"email": user.email, "name": user.name, "role": user.role}