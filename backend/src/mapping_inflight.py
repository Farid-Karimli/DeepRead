"""
Redis-backed in-flight guards for ad-hoc mapping tasks.

Prevents duplicate Celery jobs for the same mapping cache key while a prior
request is still queued or running. Completed mappings remain guarded by the
Supabase cache_key lookup in the API.
"""

from __future__ import annotations

import os

import redis

INFLIGHT_KEY_PREFIX = "deepread:mapping:inflight:v1:"
DEFAULT_TTL_SECONDS = 30 * 60


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _ttl_seconds() -> int:
    raw = os.getenv("MAPPING_INFLIGHT_TTL_SECONDS")
    if raw is None or not raw.strip():
        return DEFAULT_TTL_SECONDS
    try:
        return max(60, int(raw))
    except ValueError:
        return DEFAULT_TTL_SECONDS


def _client() -> redis.Redis:
    return redis.Redis.from_url(_redis_url(), decode_responses=True)


def _inflight_key(cache_key: str) -> str:
    return f"{INFLIGHT_KEY_PREFIX}{cache_key}"


def claim_mapping_inflight(cache_key: str, task_id: str) -> bool:
    """Reserve cache_key for task_id. Returns True when this task_id owns the slot."""
    try:
        r = _client()
        return bool(
            r.set(
                _inflight_key(cache_key),
                task_id,
                nx=True,
                ex=_ttl_seconds(),
            )
        )
    except redis.RedisError:
        # Availability over strict deduplication when Redis is unavailable.
        return True


def get_mapping_inflight_task_id(cache_key: str) -> str | None:
    try:
        r = _client()
        value = r.get(_inflight_key(cache_key))
        return value if value else None
    except redis.RedisError:
        return None


def release_mapping_inflight(cache_key: str, task_id: str) -> None:
    if not task_id:
        return
    try:
        r = _client()
        key = _inflight_key(cache_key)
        current = r.get(key)
        if current == task_id:
            r.delete(key)
    except redis.RedisError:
        pass
