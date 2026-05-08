"""
Redis conversation cache.

Each active JD session keeps its full chat history in a Redis list:
  key:  conversation:{session_id}
  type: Redis list of JSON-encoded {role, content} objects
  TTL:  24 hours, refreshed on every push

On a cache miss (key expired or Redis unavailable) the callers fall back
to reading history from the Postgres chat_messages table.
"""
import json
from typing import Any

import redis.asyncio as aioredis
from loguru import logger

from app.core.config import settings

_CONVERSATION_TTL  = 60 * 60 * 24       # 24 hours
_ACTIVE_SESSION_TTL = 60 * 60 * 24 * 30  # 30 days

_pool: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _pool


async def close_redis() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


def _key(session_id: str) -> str:
    return f"conversation:{session_id}"


async def push_message(session_id: str, role: str, content: str) -> None:
    """Append one message to the Redis list and refresh the TTL."""
    try:
        r = get_redis()
        k = _key(session_id)
        payload = json.dumps({"role": role, "content": content})
        await r.rpush(k, payload)
        await r.expire(k, _CONVERSATION_TTL)
    except Exception as exc:
        logger.warning(f"redis push_message failed | session={session_id} — {exc}")


async def get_history(session_id: str) -> list[dict[str, Any]] | None:
    """
    Return the full conversation list, or None if the key doesn't exist
    (cache miss — caller should fall back to the DB).
    """
    try:
        r = get_redis()
        k = _key(session_id)
        raw = await r.lrange(k, 0, -1)
        if not raw:
            return None
        return [json.loads(item) for item in raw]
    except Exception as exc:
        logger.warning(f"redis get_history failed | session={session_id} — {exc}")
        return None


async def seed_history(session_id: str, messages: list[dict[str, Any]]) -> None:
    """
    Populate Redis from DB records (called on cache miss after DB fallback).
    Overwrites any existing key.
    """
    if not messages:
        return
    try:
        r = get_redis()
        k = _key(session_id)
        await r.delete(k)
        pipeline = r.pipeline()
        for m in messages:
            pipeline.rpush(k, json.dumps({"role": m["role"], "content": m["content"]}))
        pipeline.expire(k, _CONVERSATION_TTL)
        await pipeline.execute()
    except Exception as exc:
        logger.warning(f"redis seed_history failed | session={session_id} — {exc}")


async def clear_history(session_id: str) -> None:
    """Delete the conversation cache for a session."""
    try:
        await get_redis().delete(_key(session_id))
    except Exception as exc:
        logger.warning(f"redis clear_history failed | session={session_id} — {exc}")


# ── Active session persistence (per user) ─────────────────────────────────────

def _active_session_key(user_id: str) -> str:
    return f"active_session:{user_id}"


async def set_active_session(user_id: str, session_id: str) -> None:
    """Persist the user's last active JD session for 30 days."""
    try:
        r = get_redis()
        k = _active_session_key(user_id)
        await r.set(k, session_id, ex=_ACTIVE_SESSION_TTL)
    except Exception as exc:
        logger.warning(f"redis set_active_session failed | user={user_id} — {exc}")


async def get_active_session(user_id: str) -> str | None:
    """Return the user's last active session_id, or None if not set / expired."""
    try:
        return await get_redis().get(_active_session_key(user_id))
    except Exception as exc:
        logger.warning(f"redis get_active_session failed | user={user_id} — {exc}")
        return None


async def clear_active_session(user_id: str) -> None:
    """Remove the stored active session (on logout or explicit reset)."""
    try:
        await get_redis().delete(_active_session_key(user_id))
    except Exception as exc:
        logger.warning(f"redis clear_active_session failed | user={user_id} — {exc}")