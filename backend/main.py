"""Bootstraps the FastAPI application, startup lifecycle, and infrastructure wiring."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.routes import limiter, router
from app.database.neo4j_client import check_health as check_neo4j_health
from app.database.neo4j_client import close_driver, create_indexes, graph_has_data
from app.ingestion.loader import load_all
from app.utils.logger import generate_request_id, log


load_dotenv()
_startup_warmup_task: asyncio.Task[None] | None = None


DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "https://graph-query-frontend.onrender.com",
]


# Splits configured frontend origins because local dev and Render need different CORS values without code edits.
def _allowed_origins() -> list[str]:
    configured = os.environ.get("ALLOWED_ORIGINS", ",".join(DEFAULT_ALLOWED_ORIGINS))
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return origins or DEFAULT_ALLOWED_ORIGINS

app = FastAPI(
    title="Graph Query System",
    version="1.0.0",
    docs_url="/docs",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


# Checks Neo4j readiness because Aura cold starts should degrade the app instead of crashing startup.
async def _wait_for_neo4j(request_id: str) -> bool:
    neo4j_ready = await asyncio.to_thread(check_neo4j_health)
    if neo4j_ready:
        log("app.startup.neo4j_ready", request_id)
        return True

    log("app.startup.neo4j_unavailable", request_id, reason="startup_connectivity_check_failed")
    return False


# Chooses the likely CSV data path because local runs and Docker runs need one shared discovery rule.
def _default_csv_dir() -> Path:
    configured = os.environ.get("DATA_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1] / "data"


# Chooses the likely SAP fallback path because the current repository already contains JSONL data for local demos.
def _default_jsonl_dir() -> Path:
    configured = os.environ.get("SAP_DATA_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1] / "sap-o2c-data"


# Seeds the graph only when needed because idempotent startup should be fast on normal restarts.
async def _maybe_seed_database(request_id: str) -> None:
    if await asyncio.to_thread(graph_has_data):
        log("app.startup.seed_skipped", request_id, reason="graph_not_empty")
        return

    counts = await asyncio.to_thread(
        load_all,
        request_id,
        _default_csv_dir(),
        _default_jsonl_dir(),
    )
    log("app.startup.seed_complete", request_id, **counts)


# Warms external dependencies in the background because Render only needs the HTTP server to bind quickly.
async def _run_startup_warmup(request_id: str) -> None:
    neo4j_ready = False

    try:
        neo4j_ready = await _wait_for_neo4j(request_id)
        if neo4j_ready:
            await asyncio.to_thread(create_indexes)
            await _maybe_seed_database(request_id)
        else:
            log("app.startup.degraded", request_id, neo4j="unreachable")
    except asyncio.CancelledError:
        log("app.startup.cancelled", request_id)
        raise
    except Exception as exc:
        log("app.startup.failed", request_id, error=str(exc))
    finally:
        log("app.startup.complete", request_id, neo4j_ready=neo4j_ready)


# Schedules indexes and optional seed data because the web server must accept traffic before warmup finishes.
@app.on_event("startup")
async def startup_event() -> None:
    global _startup_warmup_task

    request_id = generate_request_id()
    log("app.startup.begin", request_id)
    _startup_warmup_task = asyncio.create_task(_run_startup_warmup(request_id))
    log("app.startup.warmup_scheduled", request_id)


# Closes external resources because orderly shutdown prevents connection leaks between restarts and tests.
@app.on_event("shutdown")
async def shutdown_event() -> None:
    global _startup_warmup_task

    request_id = generate_request_id()
    log("app.shutdown.begin", request_id)
    if _startup_warmup_task is not None and not _startup_warmup_task.done():
        _startup_warmup_task.cancel()
        await asyncio.gather(_startup_warmup_task, return_exceptions=True)
    _startup_warmup_task = None
    await asyncio.to_thread(close_driver)
    log("app.shutdown.complete", request_id)


# Returns a simple root payload because Render uses this path for lightweight health checks.
@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "Graph Query System API"}
