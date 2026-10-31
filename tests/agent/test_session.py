from agent.session import SessionState


def test_confirm_requires_a_new_user_turn():
    s = SessionState()
    s.start_turn()
    s.register_pending("P1", "block_card")
    assert s.can_confirm("P1") == (False, "same_turn")
    s.start_turn()
    assert s.can_confirm("P1") == (True, "ok")


def test_unknown_token_and_single_use():
    s = SessionState()
    s.start_turn()
    s.register_pending("P1", "block_card")
    assert s.can_confirm("NOPE") == (False, "unknown_token")
    s.start_turn()
    s.consume_pending("P1")
    assert s.can_confirm("P1") == (False, "unknown_token")


def test_retrieval_counters_total_vs_consecutive():
    s = SessionState()
    s.record_retrieval("no_relevant_result")
    s.record_retrieval("no_relevant_result")
    assert s.failed_retrievals == 2
    assert s.consecutive_failed_retrievals == 2
    s.record_retrieval("ok")
    assert s.failed_retrievals == 2
    assert s.consecutive_failed_retrievals == 0


def test_invalid_query_is_not_a_failed_retrieval():
    s = SessionState()
    s.record_retrieval("invalid_query")
    assert s.failed_retrievals == 0
    assert s.consecutive_failed_retrievals == 0


def test_tool_error_and_failed_verification_counters():
    s = SessionState()
    s.record_tool_error()
    s.record_tool_error()
    s.record_failed_verification()
    assert s.tool_error_count == 2
    assert s.failed_verifications == 1


def test_token_never_appears_in_repr_or_str():
    s = SessionState()
    s.set_verified("SECRET123", "Ada")
    assert "SECRET123" not in repr(s)
    assert "SECRET123" not in str(s)
    assert s.verified is True
    s.clear_verified()
    assert s.verified is False


def test_turn_starts_at_zero_and_session_ids_are_unique():
    a = SessionState()
    b = SessionState()
    assert a.turn == 0
    assert a.session_id != b.session_id
