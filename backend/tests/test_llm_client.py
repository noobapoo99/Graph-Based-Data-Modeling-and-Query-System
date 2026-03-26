from unittest.mock import Mock

from app.services import llm_client


# Verifies provider fallback because the query pipeline should survive a Groq outage by retrying against Gemini.
def test_call_llm_falls_back_to_gemini(monkeypatch) -> None:
    groq_mock = Mock(side_effect=RuntimeError("groq unavailable"))
    gemini_mock = Mock(return_value="OK")

    monkeypatch.setattr(llm_client, "_call_groq", groq_mock)
    monkeypatch.setattr(llm_client, "_call_gemini", gemini_mock)

    result = llm_client.call_llm("system", "user", "request-1")

    assert result == "OK"
    groq_mock.assert_called_once()
    gemini_mock.assert_called_once()
