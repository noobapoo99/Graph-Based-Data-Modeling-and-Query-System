"""Wraps Neo4j access behind a small, safe API for reads, health, and ingestion."""

from __future__ import annotations

import os
import time
from typing import Any

from neo4j import Driver, GraphDatabase, READ_ACCESS, WRITE_ACCESS

from app.utils.logger import log


_driver: Driver | None = None


# Returns the configured Neo4j database because managed Neo4j instances may require either an explicit name or the server default.
def _get_database_name() -> str | None:
    configured = os.environ.get("NEO4J_DATABASE", "").strip()
    return configured or None


# Returns the configured Neo4j URI because local Docker and Aura differ only by environment.
def _get_neo4j_uri() -> str:
    return os.environ.get("NEO4J_URI", "neo4j+s://localhost.databases.neo4j.io")


# Returns the configured Neo4j auth tuple because the driver expects credentials in one stable shape.
def _get_neo4j_auth() -> tuple[str, str]:
    return (
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "password123"),
    )


# Creates a verified driver with retries because Aura and free-tier environments can take a moment to accept connections.
def _create_driver_with_retry(attempts: int = 3, delay_seconds: int = 2) -> Driver:
    request_id = "neo4j-driver"
    uri = _get_neo4j_uri()
    auth = _get_neo4j_auth()
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        driver = None
        try:
            log("neo4j.driver.connect_attempt", request_id, attempt=attempt, max_attempts=attempts, uri=uri)
            driver = GraphDatabase.driver(uri, auth=auth)
            driver.verify_connectivity()
            log("neo4j.driver.connect_success", request_id, attempt=attempt, uri=uri)
            return driver
        except Exception as exc:
            last_error = exc
            log(
                "neo4j.driver.connect_failed",
                request_id,
                attempt=attempt,
                max_attempts=attempts,
                uri=uri,
                error=str(exc),
            )
            if driver is not None:
                driver.close()
            if attempt < attempts:
                time.sleep(delay_seconds)

    raise RuntimeError(f"Neo4j did not become reachable after {attempts} attempts.") from last_error


# Creates and reuses one Neo4j driver because the official driver is designed to pool connections efficiently.
def get_driver() -> Driver:
    global _driver

    if _driver is None:
        _driver = _create_driver_with_retry()

    return _driver


# Closes the shared driver because clean shutdown prevents stale pooled sockets during restarts and tests.
def close_driver() -> None:
    global _driver

    if _driver is not None:
        _driver.close()
        _driver = None


# Executes one read transaction because the driver can retry transient failures around a transaction function.
def _read_transaction(
    tx: Any,
    cypher: str,
    parameters: dict[str, Any],
    timeout: int,
) -> list[dict[str, Any]]:
    result = tx.run(cypher, parameters, timeout=timeout)
    return [record.data() for record in result]


# Executes one write transaction because ingestion needs an internal path for idempotent MERGE operations.
def _write_transaction(
    tx: Any,
    cypher: str,
    parameters: dict[str, Any],
    timeout: int,
) -> list[dict[str, Any]]:
    result = tx.run(cypher, parameters, timeout=timeout)
    return [record.data() for record in result]


# Runs a read-only query because the user-facing query pipeline must never mutate the graph.
def run_query(
    cypher: str,
    parameters: dict[str, Any] | None = None,
    timeout: int = 10,
) -> list[dict[str, Any]]:
    with get_driver().session(
        database=_get_database_name(),
        default_access_mode=READ_ACCESS,
    ) as session:
        return session.execute_read(
            _read_transaction,
            cypher,
            parameters or {},
            timeout,
        )


# Runs an internal write query because the loader must create nodes and relationships before the API can answer questions.
def _run_write_query(
    cypher: str,
    parameters: dict[str, Any] | None = None,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    with get_driver().session(
        database=_get_database_name(),
        default_access_mode=WRITE_ACCESS,
    ) as session:
        return session.execute_write(
            _write_transaction,
            cypher,
            parameters or {},
            timeout,
        )


# Creates the required indexes because without them even simple lookups can degrade into full graph scans.
def create_indexes() -> None:
    index_queries = [
        "CREATE INDEX order_id IF NOT EXISTS FOR (n:Order) ON (n.id)",
        "CREATE INDEX customer_id IF NOT EXISTS FOR (n:Customer) ON (n.id)",
        "CREATE INDEX invoice_id IF NOT EXISTS FOR (n:Invoice) ON (n.id)",
        "CREATE INDEX delivery_id IF NOT EXISTS FOR (n:Delivery) ON (n.id)",
        "CREATE INDEX payment_id IF NOT EXISTS FOR (n:Payment) ON (n.id)",
    ]

    for query in index_queries:
        _run_write_query(query, timeout=30)


# Checks Neo4j connectivity because the health endpoint should report dependency reachability without running a business query.
def check_health() -> bool:
    try:
        get_driver().verify_connectivity()
        return True
    except Exception:
        return False


# Checks whether the graph already has data because startup seeding should run only when the database is empty.
def graph_has_data() -> bool:
    try:
        result = run_query("MATCH (n) RETURN count(n) AS count", timeout=10)
        return bool(result and result[0].get("count", 0))
    except Exception:
        return False
