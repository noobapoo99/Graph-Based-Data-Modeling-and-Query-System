from unittest.mock import Mock

import pytest

from app.database import neo4j_client


# Verifies retry recovery because Aura cold starts should succeed when connectivity comes back within the retry window.
def test_create_driver_with_retry_succeeds_on_third_attempt(monkeypatch) -> None:
    created_drivers = []
    sleep_mock = Mock()

    def fake_driver(uri: str, auth: tuple[str, str]) -> Mock:
        driver = Mock()
        if len(created_drivers) < 2:
            driver.verify_connectivity.side_effect = RuntimeError("temporary failure")
        created_drivers.append(driver)
        return driver

    monkeypatch.setattr(neo4j_client.GraphDatabase, "driver", fake_driver)
    monkeypatch.setattr(neo4j_client.time, "sleep", sleep_mock)

    driver = neo4j_client._create_driver_with_retry()

    assert driver is created_drivers[-1]
    assert len(created_drivers) == 3
    assert sleep_mock.call_count == 2


# Verifies retry limits because the startup path should stop after the configured number of failed attempts.
def test_create_driver_with_retry_raises_after_three_failures(monkeypatch) -> None:
    created_drivers = []
    sleep_mock = Mock()

    def fake_driver(uri: str, auth: tuple[str, str]) -> Mock:
        driver = Mock()
        driver.verify_connectivity.side_effect = RuntimeError("still down")
        created_drivers.append(driver)
        return driver

    monkeypatch.setattr(neo4j_client.GraphDatabase, "driver", fake_driver)
    monkeypatch.setattr(neo4j_client.time, "sleep", sleep_mock)

    with pytest.raises(RuntimeError, match="Neo4j did not become reachable after 3 attempts."):
        neo4j_client._create_driver_with_retry()

    assert len(created_drivers) == 3
    assert sleep_mock.call_count == 2
