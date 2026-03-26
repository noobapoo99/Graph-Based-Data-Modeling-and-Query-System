import asyncio
from unittest.mock import Mock

from app.models import QueryRequest
from app.services import query_pipeline


# Verifies mutation blocking because generated Cypher must never contain write operations before reaching Neo4j.
def test_cypher_validator_rejects_mutating_query() -> None:
    is_valid, reason = query_pipeline.cypher_validator(
        "MATCH (n:Order) DELETE n",
        "request-1",
    )

    assert is_valid is False
    assert "blocked pattern" in reason


# Verifies safe rejection because irrelevant questions should stop before cache lookup, query generation, or database execution.
def test_run_pipeline_rejects_irrelevant_query(monkeypatch) -> None:
    monkeypatch.setattr(query_pipeline, "call_llm", Mock(return_value="IRRELEVANT"))
    monkeypatch.setattr(query_pipeline, "get_history_text", Mock(return_value="No prior conversation."))
    monkeypatch.setattr(query_pipeline, "save_turn", Mock())

    response = asyncio.run(
        query_pipeline.run_pipeline_with_request_id(
            QueryRequest(query="What is the capital of France?", session_id="session-1"),
            "request-1",
        )
    )

    assert response.step_failed == "query_classifier"
    assert "only answer questions about customers" in response.answer


# Verifies the happy path because the final answer must come from validated Cypher, real rows, and formatter output in that order.
def test_run_pipeline_returns_database_grounded_answer(monkeypatch) -> None:
    llm_mock = Mock(
        side_effect=[
            "BUSINESS",
            "MATCH (i:Invoice) RETURN i.id, i.status LIMIT 50",
            "Invoice INV-001 is still open.",
        ]
    )

    monkeypatch.setattr(query_pipeline, "call_llm", llm_mock)
    monkeypatch.setattr(query_pipeline, "get_history_text", Mock(return_value="No prior conversation."))
    monkeypatch.setattr(query_pipeline, "get_cached", Mock(return_value=None))
    monkeypatch.setattr(query_pipeline, "run_query", Mock(return_value=[{"i.id": "INV-001", "i.status": "OPEN"}]))
    monkeypatch.setattr(query_pipeline, "set_cache", Mock())
    monkeypatch.setattr(query_pipeline, "save_turn", Mock())
    monkeypatch.setattr(query_pipeline, "resolve_entity", Mock(return_value=None))

    response = asyncio.run(
        query_pipeline.run_pipeline_with_request_id(
            QueryRequest(query="Show unpaid invoices", session_id="session-2"),
            "request-2",
        )
    )

    assert response.step_failed is None
    assert response.cypher == "MATCH (i:Invoice) RETURN i.id, i.status LIMIT 50"
    assert response.answer == "Invoice INV-001 is still open."
