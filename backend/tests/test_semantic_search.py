from unittest.mock import Mock

import numpy as np

from app.services import semantic_search


# Verifies similarity-based resolution because vague business terms should map to the nearest schema entity when embeddings are available.
def test_resolve_entity_returns_best_matching_schema_label(monkeypatch) -> None:
    fake_model = Mock()
    fake_model.encode.return_value = np.asarray([[1.0, 0.0]])
    fake_embeddings = np.vstack(
        [np.asarray([1.0, 0.0])]
        + [np.asarray([0.0, 1.0])] * (len(semantic_search.SCHEMA_ENTITIES) - 1)
    )

    monkeypatch.setattr(semantic_search, "_model", fake_model)
    monkeypatch.setattr(semantic_search, "_entity_embeddings", fake_embeddings)
    monkeypatch.setattr(semantic_search, "_model_available", True)

    assert semantic_search.resolve_entity("customer-like phrase", threshold=0.5) == semantic_search.SCHEMA_ENTITIES[0]


# Verifies startup fallback because the backend should still boot when the embedding model cannot load.
def test_resolve_entity_returns_none_when_model_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(semantic_search, "_model_available", False)
    monkeypatch.setattr(semantic_search, "_model", None)
    monkeypatch.setattr(semantic_search, "_entity_embeddings", None)

    assert semantic_search.resolve_entity("invoice") is None
