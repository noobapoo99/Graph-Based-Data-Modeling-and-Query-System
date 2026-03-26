"""Defines the Stage 1 API routes for querying, health, graph inspection, and schema access."""

import asyncio
import os
import secrets

from fastapi import APIRouter, Body, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.database.neo4j_client import check_health as check_neo4j_health
from app.database.neo4j_client import run_query
from app.database.schema import SCHEMA
from app.ingestion.loader import load_all
from app.models import QueryRequest, QueryResponse
from app.services.llm_client import check_llm_health
from app.services.query_pipeline import run_pipeline_with_request_id
from app.utils.logger import generate_request_id, log


limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/api", tags=["api"])


NEO4J_UNREACHABLE_DETAIL = (
    "Neo4j is unreachable. Check NEO4J_URI, NEO4J_USER, "
    "NEO4J_PASSWORD, and NEO4J_DATABASE in the deployment environment."
)


# Returns the fixed node inspection query because the graph endpoint must stay read-only and predictable.
def _graph_nodes_cypher() -> str:
    return """
    MATCH (n)
    RETURN
      coalesce(n.id, elementId(n)) AS id,
      labels(n) AS labels,
      properties(n) AS properties
    LIMIT 500
    """


# Returns the fixed edge inspection query because graph visualization should not depend on LLM-generated Cypher.
def _graph_edges_cypher() -> str:
    return """
    MATCH (source)-[rel]->(target)
    RETURN
      elementId(rel) AS id,
      type(rel) AS type,
      coalesce(source.id, elementId(source)) AS source,
      coalesce(target.id, elementId(target)) AS target
    LIMIT 1000
    """


# Returns the fixed broken-flow queries because these checks are operational diagnostics, not free-form LLM tasks.
def _broken_flow_queries() -> dict[str, str]:
    return {
        "orders_without_delivery": """
            MATCH (o:Order)
            WHERE NOT (o)-[:FULFILLED_BY]->(:Delivery)
            RETURN o.id AS order_id, o.date AS date, o.status AS status
            LIMIT 50
        """,
        "deliveries_without_invoice": """
            MATCH (d:Delivery)
            WHERE NOT (d)-[:BILLED_AS]->(:Invoice)
            RETURN d.id AS delivery_id, d.date AS date, d.status AS status
            LIMIT 50
        """,
        "invoices_without_payment": """
            MATCH (i:Invoice)
            WHERE NOT (i)-[:SETTLED_BY]->(:Payment)
            RETURN i.id AS invoice_id, i.date AS date, i.amount AS amount, i.status AS status
            LIMIT 50
        """,
    }


# Runs one fixed read query because API endpoints should keep Neo4j access off the event loop thread.
async def _run_read_query(cypher: str) -> list[dict]:
    return await asyncio.to_thread(run_query, cypher, None, 10)


# Builds a consistent dependency failure response because read-only graph routes should degrade without throwing raw 500 errors.
async def _neo4j_failure_response(request_id: str, log_event: str, error: Exception, fallback_detail: str) -> JSONResponse:
    neo4j_ok = await asyncio.to_thread(check_neo4j_health)
    detail = fallback_detail if neo4j_ok else NEO4J_UNREACHABLE_DETAIL
    log(log_event, request_id, neo4j_ok=neo4j_ok, error=str(error))
    return JSONResponse(content={"detail": detail}, status_code=503)


# Validates the ingestion bearer token because production ingestion should not be publicly callable.
def _require_ingest_token(authorization: str | None) -> None:
    expected_token = os.environ.get("INGEST_TOKEN", "").strip()
    if not expected_token:
        raise HTTPException(status_code=503, detail="Ingest endpoint is not configured.")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")

    provided_token = authorization.removeprefix("Bearer ").strip()
    if not provided_token or not secrets.compare_digest(provided_token, expected_token):
        raise HTTPException(status_code=401, detail="Unauthorized")


# Handles the natural-language query endpoint because this is the main business workflow for Stage 1.
@router.post("/query", response_model=QueryResponse)
@limiter.limit("10/minute")
async def query_endpoint(request: Request, payload: QueryRequest = Body(...)) -> QueryResponse:
    request_id = generate_request_id()
    log("api.query.request", request_id, query=payload.query, session_id=payload.session_id)
    response = await run_pipeline_with_request_id(payload, request_id)
    log(
        "api.query.response",
        request_id,
        step_failed=response.step_failed,
        latency_ms=response.latency_ms,
    )
    return response


# Reports dependency reachability because operators need a fast signal about Neo4j and LLM availability.
@router.get("/health")
@limiter.limit("10/minute")
async def health_endpoint(request: Request) -> JSONResponse:
    request_id = generate_request_id()
    log("api.health.request", request_id)

    neo4j_ok, llm_ok = await asyncio.gather(
        asyncio.to_thread(check_neo4j_health),
        asyncio.to_thread(check_llm_health, request_id),
    )

    payload = {
        "status": "healthy" if neo4j_ok and llm_ok else "degraded",
        "neo4j": "ok" if neo4j_ok else "unreachable",
        "llm": "ok" if llm_ok else "unreachable",
    }
    status_code = 200 if neo4j_ok and llm_ok else 503
    log("api.health.response", request_id, **payload, status_code=status_code)
    return JSONResponse(content=payload, status_code=status_code)


# Returns a graph snapshot because the frontend and operators need a direct visualization payload without using the LLM.
@router.get("/graph", response_model=None)
@limiter.limit("10/minute")
async def graph_endpoint(request: Request) -> dict[str, list[dict]] | JSONResponse:
    request_id = generate_request_id()
    log("api.graph.request", request_id)

    try:
        nodes, edges = await asyncio.gather(
            _run_read_query(_graph_nodes_cypher()),
            _run_read_query(_graph_edges_cypher()),
        )
    except Exception as exc:
        return await _neo4j_failure_response(
            request_id,
            "api.graph.failed",
            exc,
            "Graph data could not be loaded from Neo4j.",
        )

    log("api.graph.response", request_id, node_count=len(nodes), edge_count=len(edges))
    return {"nodes": nodes, "edges": edges}


# Returns operationally interesting missing-link flows because incomplete order-to-cash chains are a core Stage 1 use case.
@router.get("/broken-flows", response_model=None)
@limiter.limit("10/minute")
async def broken_flows_endpoint(request: Request) -> dict[str, object] | JSONResponse:
    request_id = generate_request_id()
    log("api.broken_flows.request", request_id)

    try:
        details: dict[str, list[dict]] = {}
        for flow_name, cypher in _broken_flow_queries().items():
            details[flow_name] = await _run_read_query(cypher)
    except Exception as exc:
        return await _neo4j_failure_response(
            request_id,
            "api.broken_flows.failed",
            exc,
            "Broken-flow diagnostics could not be loaded from Neo4j.",
        )

    broken_flow_count = sum(len(rows) for rows in details.values())
    log("api.broken_flows.response", request_id, broken_flow_count=broken_flow_count)
    return {
        "broken_flow_count": broken_flow_count,
        "details": details,
    }


# Returns the canonical schema because clients and debugging tools need the same model the LLM sees.
@router.get("/schema")
@limiter.limit("10/minute")
async def schema_endpoint(request: Request) -> dict:
    request_id = generate_request_id()
    log("api.schema.request", request_id)
    log("api.schema.response", request_id, node_count=len(SCHEMA["nodes"]))
    return SCHEMA


# Triggers data loading because Aura-backed deployments need a safe operational path to seed data after startup.
@router.post("/ingest")
@limiter.limit("5/minute")
async def ingest_endpoint(request: Request, authorization: str | None = Header(default=None)) -> dict[str, object]:
    request_id = generate_request_id()
    log("api.ingest.request", request_id)

    _require_ingest_token(authorization)
    counts = await asyncio.to_thread(load_all, request_id)

    log("api.ingest.response", request_id, **counts)
    return {
        "status": "ok",
        "counts": counts,
    }
