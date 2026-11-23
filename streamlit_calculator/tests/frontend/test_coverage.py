# Copyright 2026 anchored-vwam-backtest contributors
"""Prevent broad V8 function ranges from hiding unexecuted nested branches."""

from tests.frontend.coverage import executed_ranges


def test_unexecuted_nested_ranges_are_excluded() -> None:
    """An executed parent must not mark an untaken child block as covered."""
    functions: list[object] = [
        {
            "ranges": [
                {"startOffset": 0, "endOffset": 100, "count": 1},
                {"startOffset": 20, "endOffset": 60, "count": 0},
                {"startOffset": 30, "endOffset": 40, "count": 1},
            ]
        },
        {"ranges": [{"startOffset": 70, "endOffset": 90, "count": 0}]},
    ]
    assert executed_ranges(functions) == [
        (0, 20),
        (30, 40),
        (60, 70),
        (90, 100),
    ]
