"""Provides Redis-backed caching for repeated natural-language queries."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import redis


TTL_SECONDS = 3600
_redis_client: redis.Redis | None = None


# Normalizes the user query because small whitespace or casing changes should not destroy cache hit rates.
def _normalize_query(query: str) -> str:
    return " ".join(query.lower().strip().split())


# Normalizes prompt history because follow-up questions must be isolated by conversational context.
def _normalize_history(history_text: str) -> str:
    return " ".join(history_text.strip().split()) if history_text.strip() else "root-history"


# Reuses one Redis client because the Redis library already manages connection pooling internally.
def _get_redis_client() -> redis.Redis:
    global _redis_client

    if _redis_client is None:
        _redis_client = redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379"),
            decode_responses=True,
            socket_timeout=2,
            socket_connect_timeout=2,
        )

    return _redis_client


# Builds a stable key because cached answers must stay correct for both repeated standalone queries and follow-up questions.
def _build_cache_key(query: str, history_text: str = "") -> str:
    query_hash = hashlib.md5(_normalize_query(query).encode("utf-8")).hexdigest()
    history_hash = hashlib.md5(_normalize_history(history_text).encode("utf-8")).hexdigest()[:12]
    return f"gqs:{query_hash}:{history_hash}"


# Reads one cached response because repeated questions should return instantly when the conversational context matches.
def get_cached(query: str, history_text: str = "") -> dict[str, Any] | None:
    try:
        raw_value = _get_redis_client().get(_build_cache_key(query, history_text))
    except Exception:
        return None

    if not raw_value:
        return None

    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return None


# Stores one response because Redis should accelerate future identical questions without making the API depend on cache availability.
def set_cache(query: str, response: dict[str, Any], history_text: str = "") -> None:
    try:
        _get_redis_client().setex(
            _build_cache_key(query, history_text),
            TTL_SECONDS,
            json.dumps(response),
        )
    except Exception:
        return
