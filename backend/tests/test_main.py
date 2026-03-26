import asyncio
from unittest.mock import AsyncMock, Mock

import main


# Verifies startup seeding is skipped when the graph already has data because normal restarts should stay fast and idempotent.
def test_maybe_seed_database_skips_when_graph_is_not_empty(monkeypatch) -> None:
    load_all_mock = Mock()

    monkeypatch.setattr(main, "graph_has_data", Mock(return_value=True))
    monkeypatch.setattr(main, "load_all", load_all_mock)

    asyncio.run(main._maybe_seed_database("request-1"))

    load_all_mock.assert_not_called()


# Verifies startup seeding runs when the graph is empty because `docker-compose up` should produce a queryable database automatically.
def test_maybe_seed_database_loads_when_graph_is_empty(monkeypatch) -> None:
    load_all_mock = Mock(return_value={"customers": 1})

    monkeypatch.setattr(main, "graph_has_data", Mock(return_value=False))
    monkeypatch.setattr(main, "load_all", load_all_mock)
    monkeypatch.setattr(main, "_default_csv_dir", Mock(return_value=main.Path("/tmp/data")))
    monkeypatch.setattr(main, "_default_jsonl_dir", Mock(return_value=main.Path("/tmp/sap-o2c-data")))

    asyncio.run(main._maybe_seed_database("request-2"))

    load_all_mock.assert_called_once()


# Verifies the Render health payload because the root endpoint is used as a lightweight service check.
def test_root_returns_ok_payload() -> None:
    assert asyncio.run(main.root()) == {"status": "ok", "service": "Graph Query System API"}


# Verifies graceful warmup because the app should not crash when Aura is temporarily unreachable.
def test_run_startup_warmup_skips_index_creation_and_seeding_when_neo4j_is_unreachable(monkeypatch) -> None:
    create_indexes_mock = Mock()
    maybe_seed_database_mock = AsyncMock()

    monkeypatch.setattr(main, "_wait_for_neo4j", AsyncMock(return_value=False))
    monkeypatch.setattr(main, "create_indexes", create_indexes_mock)
    monkeypatch.setattr(main, "_maybe_seed_database", maybe_seed_database_mock)

    asyncio.run(main._run_startup_warmup("request-3"))

    create_indexes_mock.assert_not_called()
    maybe_seed_database_mock.assert_not_called()
