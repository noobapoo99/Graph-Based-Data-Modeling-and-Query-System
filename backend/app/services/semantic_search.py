"""Maps vague business terms to schema entities with lightweight heuristics and optional embeddings."""

from __future__ import annotations

import os
from difflib import SequenceMatcher
from threading import Lock
from typing import Any

from app.database.schema import SCHEMA
from app.utils.logger import log


SCHEMA_ENTITIES = SCHEMA["nodes"] + SCHEMA["relationships"]
ENTITY_ALIASES = {
    "bill": "Invoice",
    "bills": "Invoice",
    "billing": "Invoice",
    "client": "Customer",
    "clients": "Customer",
    "customer": "Customer",
    "customers": "Customer",
    "delivery": "Delivery",
    "deliveries": "Delivery",
    "fulfillment": "Delivery",
    "invoice": "Invoice",
    "invoices": "Invoice",
    "item": "Product",
    "items": "Product",
    "journal": "JournalEntry",
    "ledger": "JournalEntry",
    "order": "Order",
    "orders": "Order",
    "payment": "Payment",
    "payments": "Payment",
    "product": "Product",
    "products": "Product",
    "shipment": "Delivery",
    "shipments": "Delivery",
}
NORMALIZED_SCHEMA_ENTITIES = {
    " ".join(entity.lower().strip().split()): entity for entity in SCHEMA_ENTITIES
}
_model: Any | None = None
_entity_embeddings: Any | None = None
_model_available = False
_model_error: Exception | None = None
_model_load_attempted = False
_model_lock = Lock()


# Normalizes free-form text because embedding search works better when trivial whitespace and casing differences are removed.
def _normalize_term(vague_term: str) -> str:
    return " ".join(vague_term.lower().strip().split())


# Keeps semantic search opt-in because model downloads at process boot can prevent Render from seeing an open port.
def _embedding_model_enabled() -> bool:
    configured = os.environ.get("ENABLE_EMBEDDING_SEMANTIC_SEARCH", "").strip().lower()
    return configured in {"1", "true", "yes", "on"}


# Loads the embedding model lazily because semantic hints are optional and should never block application startup.
def _load_model_if_enabled() -> None:
    global _model
    global _entity_embeddings
    global _model_available
    global _model_error
    global _model_load_attempted

    if _model_available or _model_load_attempted or not _embedding_model_enabled():
        return

    with _model_lock:
        if _model_available or _model_load_attempted or not _embedding_model_enabled():
            return

        _model_load_attempted = True

        try:
            import numpy as np
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


# Checks lightweight aliases first because they cover the common business synonyms this app expects in production.
def _alias_match(normalized_term: str) -> str | None:
    if normalized_term in NORMALIZED_SCHEMA_ENTITIES:
        return NORMALIZED_SCHEMA_ENTITIES[normalized_term]

    if normalized_term in ENTITY_ALIASES:
        return ENTITY_ALIASES[normalized_term]

    for alias, entity in ENTITY_ALIASES.items():
        if alias in normalized_term or normalized_term in alias:
            return entity

    return None


# Uses optional embeddings when explicitly enabled because fuzzy semantic matching is a nice-to-have rather than a boot requirement.
def _embedding_match(normalized_term: str, threshold: float) -> str | None:
    if not _model_available or _model is None or _entity_embeddings is None:
        return None

    try:
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity

        query_embedding = np.asarray(_model.encode([normalized_term]))
        scores = cosine_similarity(query_embedding, _entity_embeddings)[0]
        best_index = int(np.argmax(scores))
        best_score = float(scores[best_index])
        if best_score >= threshold:
            return SCHEMA_ENTITIES[best_index]
    except Exception:
        return None

    return None


# Falls back to lexical similarity because startup-safe matching is better than no hinting at all.
def _lexical_match(normalized_term: str, threshold: float) -> str | None:
    best_entity: str | None = None
    best_score = 0.0

    for entity in SCHEMA_ENTITIES:
        candidate = _normalize_term(entity)
        score = SequenceMatcher(None, normalized_term, candidate).ratio()
        if normalized_term in candidate or candidate in normalized_term:
            score = max(score, 0.9)
        if score > best_score:
            best_score = score
            best_entity = entity

    minimum_score = max(threshold, 0.7)
    if best_entity and best_score >= minimum_score:
        return best_entity

    return None


# Resolves a vague term because users often say things like "bills" or "shipments" instead of exact schema labels.
def resolve_entity(vague_term: str, threshold: float = 0.5) -> str | None:
    normalized_term = _normalize_term(vague_term)
    if not normalized_term:
        return None

    alias_match = _alias_match(normalized_term)
    if alias_match:
        return alias_match

    _load_model_if_enabled()

    embedding_match = _embedding_match(normalized_term, threshold)
    if embedding_match:
        return embedding_match

    return _lexical_match(normalized_term, threshold)
