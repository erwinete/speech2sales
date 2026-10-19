"""State machine пайплайна (doc 01 §5.1)."""

from polylog.models.enums import CALL_STATE_ORDER, CallState, advance


def test_advance_moves_forward():
    assert advance(CallState.discovered, CallState.normalized) is CallState.normalized


def test_advance_keeps_later_state():
    assert advance(CallState.transcribed, CallState.normalized) is CallState.transcribed


def test_failed_is_absorbing():
    assert advance(CallState.failed, CallState.done) is CallState.failed
    assert advance(CallState.analyzed, CallState.failed) is CallState.failed


def test_order_covers_all_nonfailed_states():
    assert len(CALL_STATE_ORDER) == len(CallState) - 1  # failed вне линейного порядка
    assert len(set(CALL_STATE_ORDER)) == len(CALL_STATE_ORDER)
