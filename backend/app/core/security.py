"""
Encryption, hashing, and JWT utilities.

- Email        → Fernet symmetric encryption (reversible, ENCRYPTION_KEY)
- Email lookup → SHA-256 blind index (fast DB lookup without decrypting every row)
- Password     → bcrypt one-way hash (cannot be reversed)
- Access token → HS256 JWT signed with JWT_SECRET_KEY; carries email + role
"""

import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt
from cryptography.fernet import Fernet
from jose import JWTError, jwt

from app.core.config import settings

_fernet = Fernet(settings.encryption_key.encode())


# ── Email ─────────────────────────────────────────────────────────────────────

def encrypt_email(email: str) -> str:
    """Fernet-encrypt an email for storage."""
    return _fernet.encrypt(email.lower().strip().encode()).decode()


def decrypt_email(token: str) -> str:
    """Decrypt a Fernet-encrypted email."""
    return _fernet.decrypt(token.encode()).decode()


def hash_email(email: str) -> str:
    """SHA-256 blind index used for fast DB lookup by email."""
    return hashlib.sha256(email.lower().strip().encode()).hexdigest()


# ── Password ──────────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the plain-text password."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the stored bcrypt hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ── JWT ───────────────────────────────────────────────────────────────────────

_ALGORITHM = "HS256"


def create_access_token(email: str, name: str, role: str, expires_minutes: int | None = None) -> str:
    """Return a signed JWT. Defaults to settings.jwt_expire_minutes."""
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    payload = {"sub": email, "name": name, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Decode and verify the JWT. Returns the payload dict.
    Raises jose.JWTError if the token is invalid or expired.
    """
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[_ALGORITHM])