from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api import routes
from app.models import QueryResponse


# Builds a test app because route behavior should be verifiable without booting the full production startup sequence.
def create_test_app() -> TestClient:
    app = FastAPI()
    app.state.limiter = routes.limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(routes.router)
    return TestClient(app)


# Verifies degraded health reporting because operators need a 503 when either Neo4j or the LLM path is unreachable.
def test_health_endpoint_returns_503_when_dependency_is_down(monkeypatch) -> None:
    monkeypatch.setattr(routes, "check_neo4j_health", Mock(return_value=False))
    monkeypatch.setattr(routes, "check_llm_health", Mock(return_value=True))

    client = create_test_app()
    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


# Verifies broken-flow aggregation because the endpoint must return both per-flow details and the total broken flow count.
def test_broken_flows_endpoint_aggregates_all_queries(monkeypatch) -> None:
    monkeypatch.setattr(
        routes,
        "run_query",
        Mock(
            side_effect=[
                [{"order_id": "ORD-1"}],
                [{"delivery_id": "DEL-1"}, {"delivery_id": "DEL-2"}],
                [],
            ]
        ),
    )

    client = create_test_app()
    response = client.get("/api/broken-flows")

    assert response.status_code == 200
    assert response.json()["broken_flow_count"] == 3


# Verifies the query endpoint contract because it should return the pipeline's structured response unchanged.
def test_query_endpoint_returns_pipeline_response(monkeypatch) -> None:
    monkeypatch.setattr(
        routes,
        "run_pipeline_with_request_id",
        AsyncMock(
            return_value=QueryResponse(
                answer="Invoice INV-001 is open.",
                cypher="MATCH (i:Invoice) RETURN i.id LIMIT 50",
                explanation="The answer was generated from 1 database row(s).",
                latency_ms=12,
                step_failed=None,
            )
        ),
    )

    client = create_test_app()
    response = client.post(
        "/api/query",
        json={"query": "Show unpaid invoices", "session_id": "session-3"},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "Invoice INV-001 is open."


# Verifies auth enforcement because ingestion must not run without a valid bearer token.
def test_ingest_endpoint_returns_401_without_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv("INGEST_TOKEN", "super-secret")

    client = create_test_app()
    response = client.post("/api/ingest")

    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


# Verifies the protected ingestion path because production needs a post-deploy data loading route.
def test_ingest_endpoint_runs_loader_with_valid_bearer_token(monkeypatch) -> None:
    load_all_mock = Mock(return_value={"customers": 2})

    monkeypatch.setenv("INGEST_TOKEN", "super-secret")
    monkeypatch.setattr(routes, "load_all", load_all_mock)

    client = create_test_app()
    response = client.post("/api/ingest", headers={"Authorization": "Bearer super-secret"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "counts": {"customers": 2}}
    load_all_mock.assert_called_once()
