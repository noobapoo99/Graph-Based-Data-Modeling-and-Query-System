"""Maps vague business terms to schema entities using sentence-transformer embeddings."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from app.database.schema import SCHEMA
from app.utils.logger import log


SCHEMA_ENTITIES = SCHEMA["nodes"] + SCHEMA["relationships"]
_model: Any | None = None
_entity_embeddings: np.ndarray | None = None
_model_available = False
_model_error: Exception | None = None


# Normalizes free-form text because embedding search works better when trivial whitespace and casing differences are removed.
def _normalize_term(vague_term: str) -> str:
    return " ".join(vague_term.lower().strip().split())


# Loads the embedding model at import time because the module should be ready to resolve schema hints immediately.
def _load_model_at_import() -> None:
    global _model
    global _entity_embeddings
    global _model_available
    global _model_error

    try:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer("all-MiniLM-L6-v2")
        _entity_embeddings = np.asarray(_model.encode(SCHEMA_ENTITIES))
        _model_available = True
        _model_error = None
    except Exception as exc:
        _model = None
        _entity_embeddings = None
        _model_available = False
        _model_error = exc
        log("semantic_search.model_unavailable", "semantic-search", error=str(exc))


# Resolves a vague term because users often say things like "bills" or "shipments" instead of exact schema labels.
def resolve_entity(vague_term: str, threshold: float = 0.5) -> str | None:
    normalized_term = _normalize_term(vague_term)
    if not normalized_term or not _model_available or _model is None or _entity_embeddings is None:
        return None

    try:
        query_embedding = np.asarray(_model.encode([normalized_term]))
        scores = cosine_similarity(query_embedding, _entity_embeddings)[0]
        best_index = int(np.argmax(scores))
        best_score = float(scores[best_index])
        if best_score >= threshold:
            return SCHEMA_ENTITIES[best_index]
    except Exception:
        return None

    return None


_load_model_at_import()
