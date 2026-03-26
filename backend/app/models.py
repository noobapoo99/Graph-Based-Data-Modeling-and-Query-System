"""Defines the API request and response contracts for Stage 1."""

from __future__ import annotations

from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# Generates a stable session identifier because follow-up questions need a conversation key even before authentication exists.
def generate_session_id() -> str:
    return str(uuid4())


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)
    session_id: str = Field(default_factory=generate_session_id)


class QueryResponse(BaseModel):
    answer: str
    cypher: Optional[str] = None
    explanation: Optional[str] = None
    latency_ms: int
    step_failed: Optional[str] = None
