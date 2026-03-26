from app.services.memory import clear_history, get_history_text, save_turn


# Verifies history trimming because follow-up prompts should only include the last five turns instead of growing forever.
def test_save_turn_keeps_last_five_turns() -> None:
    session_id = "memory-test-session"
    clear_history(session_id)

    for index in range(6):
        save_turn(session_id, f"question-{index}", f"answer-{index}")

    history_text = get_history_text(session_id)

    assert "question-0" not in history_text
    assert "question-1" in history_text
    assert "question-5" in history_text

    clear_history(session_id)
