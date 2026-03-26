from app.utils import cache


class FakeRedis:
    # Initializes an in-memory store because the cache tests should verify key behavior without needing a real Redis server.
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    # Returns a cached value because the production cache path reads serialized JSON strings from Redis by key.
    def get(self, key: str) -> str | None:
        return self.store.get(key)

    # Stores a cached value because the production cache path writes responses with a TTL-aware Redis command.
    def setex(self, key: str, ttl_seconds: int, value: str) -> None:
        self.store[key] = value


class BrokenRedis:
    # Raises on read because cache failures should degrade gracefully instead of breaking the request path.
    def get(self, key: str) -> str | None:
        raise RuntimeError("redis unavailable")


# Verifies context-aware caching because identical follow-up text must not leak answers across different session histories.
def test_cache_uses_history_to_isolate_follow_up_questions(monkeypatch) -> None:
    monkeypatch.setattr(cache, "_redis_client", FakeRedis())

    cache.set_cache("what about that customer?", {"answer": "Customer A"}, "history-a")
    cache.set_cache("what about that customer?", {"answer": "Customer B"}, "history-b")

    assert cache.get_cached("what about that customer?", "history-a") == {"answer": "Customer A"}
    assert cache.get_cached("what about that customer?", "history-b") == {"answer": "Customer B"}


# Verifies Redis URL configuration because Upstash and local Redis both need to use one connection string setting.
def test_get_redis_client_uses_redis_url(monkeypatch) -> None:
    fake_client = FakeRedis()
    captured: dict[str, object] = {}

    def fake_from_url(url: str, **kwargs) -> FakeRedis:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return fake_client

    monkeypatch.setattr(cache, "_redis_client", None)
    monkeypatch.setenv("REDIS_URL", "rediss://default:secret@cache.example.com:6379")
    monkeypatch.setattr(cache.redis, "from_url", fake_from_url)

    assert cache._get_redis_client() is fake_client
    assert captured["url"] == "rediss://default:secret@cache.example.com:6379"
    assert captured["kwargs"] == {
        "decode_responses": True,
        "socket_timeout": 2,
        "socket_connect_timeout": 2,
    }


# Verifies graceful cache misses because Redis outages should not fail the request pipeline.
def test_get_cached_returns_none_when_redis_read_fails(monkeypatch) -> None:
    monkeypatch.setattr(cache, "_redis_client", BrokenRedis())

    assert cache.get_cached("show invoices") is None
