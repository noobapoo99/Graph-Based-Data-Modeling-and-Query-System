"""Stores short in-memory conversation history for session-aware follow-up questions."""

from __future__ import annotations

from threading import Lock


MAX_HISTORY = 5
_history_store: dict[str, list[dict[str, str]]] = {}
_history_lock = Lock()


# Returns recent turns for one session because callers should not need to know how history is stored internally.
def _get_turns(session_id: str) -> list[dict[str, str]]:
    with _history_lock:
        return list(_history_store.get(session_id, []))


# Formats history for prompt injection because the classifier and generator need conversational context for follow-up questions.
def get_history_text(session_id: str) -> str:
    turns = _get_turns(session_id)[-MAX_HISTORY:]
    if not turns:
        return "No prior conversation."

    return "\n".join(
        f"User: {turn['query']}\nAssistant: {turn['answer']}"
        for turn in turns
    )


# Saves one completed turn because later follow-up questions must be grounded in the last few interactions for that session.
def save_turn(session_id: str, query: str, answer: str) -> None:
    with _history_lock:
        turns = _history_store.setdefault(session_id, [])
        turns.append({"query": query, "answer": answer})
        _history_store[session_id] = turns[-MAX_HISTORY:]


# Clears one session because tests need a clean memory state without restarting the whole process.
def clear_history(session_id: str) -> None:
    with _history_lock:
        _history_store.pop(session_id, None)
