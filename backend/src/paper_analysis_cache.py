"""
Redis cache for paper analysis results (shared by API and Celery worker).

Cache key is derived from SHA-256 of the *raw* upload bytes so the same PDF
always maps to the same key; filename alone is not unique.
"""

from __future__ import annotations

import json
import os
from typing import Any

import redis

CACHE_KEY_PREFIX = "deepread:paper_analysis:v1:"

# How long to keep cached analysis JSON (seconds). Override with env.
DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60


def _redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _ttl_seconds() -> int:
    raw = os.getenv("PAPER_ANALYSIS_CACHE_TTL_SECONDS")
    if raw is None or not raw.strip():
        return DEFAULT_TTL_SECONDS
    try:
        return max(60, int(raw))
    except ValueError:
        return DEFAULT_TTL_SECONDS


def cache_key_for_paper_id(paper_id: str) -> str:
    return f"{CACHE_KEY_PREFIX}{paper_id}"


def _client() -> redis.Redis:
    return redis.Redis.from_url(_redis_url(), decode_responses=True)


def get_cached_result(paper_id: str) -> dict[str, Any] | None:
    try:
        r = _client()
        raw = r.get(cache_key_for_paper_id(paper_id))
        if raw is None:
            return None
        return json.loads(raw)
    except (redis.RedisError, json.JSONDecodeError, TypeError):
        return None


def set_cached_result(paper_id: str, result: dict[str, Any]) -> None:
    try:
        r = _client()
        payload = json.dumps(result, default=str)
        r.setex(cache_key_for_paper_id(paper_id), _ttl_seconds(), payload)
    except redis.RedisError:
        pass
