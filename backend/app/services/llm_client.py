"""Centralizes all LLM access so fallback, timeout, and logging behavior stay consistent."""

from __future__ import annotations

import os
from typing import Callable

import requests

from app.utils.logger import log


LLM_TEMPERATURE = 0
LLM_MAX_TOKENS = 500
LLM_TIMEOUT_SEC = 15


# Reads one required environment variable because missing API keys should fail clearly instead of producing confusing provider errors.
def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# Calls the configured providers in fallback order because the pipeline should survive one provider being unavailable.
def call_llm(system_prompt: str, user_message: str, request_id: str) -> str:
    providers: list[tuple[str, Callable[[str, str], str]]] = [
        ("groq", _call_groq),
        ("gemini", _call_gemini),
    ]
    last_error: Exception | None = None

    for provider_name, provider_function in providers:
        try:
            log("llm.call.started", request_id, provider=provider_name)
            result = provider_function(system_prompt, user_message).strip()
            if not result:
                raise RuntimeError("Provider returned an empty response.")
            log(
                "llm.call.succeeded",
                request_id,
                provider=provider_name,
                response_chars=len(result),
            )
            return result
        except Exception as exc:
            last_error = exc
            log(
                "llm.call.failed",
                request_id,
                provider=provider_name,
                error=str(exc),
            )

    raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")


# Calls Groq because it is the primary provider for deterministic low-latency prompt execution.
def _call_groq(system_prompt: str, user_message: str) -> str:
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {_require_env('GROQ_API_KEY')}",
            "Content-Type": "application/json",
        },
        json={
            "model": "llama-3.1-8b-instant",
            "temperature": LLM_TEMPERATURE,
            "max_tokens": LLM_MAX_TOKENS,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        },
        timeout=LLM_TIMEOUT_SEC,
    )
    if response.status_code != 200:
        error_detail = response.text
        try:
            error_detail = response.json()
        except Exception:
            pass
        raise RuntimeError(f"Groq API error ({response.status_code}): {error_detail}")
    payload = response.json()
    return payload["choices"][0]["message"]["content"]


# Extracts plain text from Gemini because its REST payload is nested differently from OpenAI-style chat responses.
def _extract_gemini_text(payload: dict) -> str:
    candidates = payload.get("candidates", [])
    if not candidates:
        raise RuntimeError("Gemini returned no candidates.")

    parts = candidates[0].get("content", {}).get("parts", [])
    text_chunks = [part.get("text", "") for part in parts if part.get("text")]
    if not text_chunks:
        raise RuntimeError("Gemini returned no text parts.")

    return "\n".join(text_chunks)


# Calls Gemini because it is the fallback provider when Groq is unavailable or fails.
def _call_gemini(system_prompt: str, user_message: str) -> str:
    response = requests.post(
        (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-1.5-pro:generateContent?key={_require_env('GEMINI_API_KEY')}"
        ),
        headers={"Content-Type": "application/json"},
        json={
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                f"System instructions:\n{system_prompt}\n\n"
                                f"User message:\n{user_message}"
                            )
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": LLM_TEMPERATURE,
                "maxOutputTokens": LLM_MAX_TOKENS,
            },
        },
        timeout=LLM_TIMEOUT_SEC,
    )
    if response.status_code != 200:
        error_detail = response.text
        try:
            error_detail = response.json()
        except Exception:
            pass
        raise RuntimeError(f"Gemini API error ({response.status_code}): {error_detail}")
    return _extract_gemini_text(response.json())


# Probes the LLM path because the health endpoint must confirm at least one provider can actually answer a tiny prompt.
def check_llm_health(request_id: str) -> bool:
    try:
        response = call_llm(
            "Reply with ONLY OK",
            "ping",
            request_id,
        )
        return response.strip().upper() == "OK"
    except Exception:
        return False
