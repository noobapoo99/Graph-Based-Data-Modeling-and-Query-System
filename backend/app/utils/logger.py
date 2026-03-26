"""Provides structured JSON logging with per-request correlation IDs."""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from uuid import uuid4


logger = logging.getLogger("graph_query_system")
logging.basicConfig(level=logging.INFO, format="%(message)s")


# Generates a request identifier because one user request touches several steps and external systems.
def generate_request_id() -> str:
    return str(uuid4())


# Writes one structured log line because JSON logs are far easier to filter in Docker and production log aggregators.
def log(event: str, request_id: str, **kwargs: Any) -> None:
    logger.info(
        json.dumps(
            {
                "event": event,
                "request_id": request_id,
                "ts": time.time(),
                **kwargs,
            },
            default=str,
        )
    )
