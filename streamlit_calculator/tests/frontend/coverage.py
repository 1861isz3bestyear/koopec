# Copyright 2026 anchored-vwam-backtest contributors
"""Measure executed dashboard JavaScript ranges through Chromium's profiler."""

import json
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, cast

from shared.validation import integer, object_list, object_mapping, string

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import CDPSession

SOURCE = (
    Path(__file__).resolve().parents[2]
    / "gui_calculator/oscillator_dashboard/chart.js"
).read_text()
MINIMUM_COVERAGE = 92


def cdp_command(
    session: CDPSession, method: str, params: dict[str, object] | None = None
) -> object:
    """Validate CDP responses at the boundary of Playwright's untyped mapping.

    Returns:
        An opaque response that callers must validate before reading.

    """
    # Playwright declares CDP mappings without generic arguments. Erase only
    # those transport types; every consumed field is runtime-validated below.
    send = cast(
        "Callable[[str, dict[str, object] | None], object]", session.send
    )
    return send(method, params)


def executed_ranges(functions: list[object]) -> list[tuple[int, int]]:
    """Resolve nested V8 zero-count blocks without inflating byte coverage.

    Returns:
        Non-overlapping executed intervals for one profiler sample.

    """
    ranges: list[tuple[int, int, int]] = []
    for function in functions:
        for raw in object_list(object_mapping(function)["ranges"]):
            item = object_mapping(raw)
            ranges.append((
                integer(item["startOffset"]),
                integer(item["endOffset"]),
                integer(item["count"]),
            ))
    boundaries = sorted(
        {value for start, end, _ in ranges for value in (start, end)}
    )
    executed: list[tuple[int, int]] = []
    for start, end in pairwise(boundaries):
        enclosing = [row for row in ranges if row[0] <= start and row[1] >= end]
        if enclosing and min(enclosing, key=lambda row: row[1] - row[0])[2] > 0:
            executed.append((start, end))
    return executed


@dataclass
class DashboardCoverage:
    """Accumulate executed characters across real browser scenarios."""

    covered: set[int] = field(default_factory=set)
    samples: int = 0

    def collect(self, session: CDPSession) -> None:
        """Read precise coverage for the production chart script only."""
        response = cdp_command(session, "Profiler.takePreciseCoverage")
        for raw in object_list(object_mapping(response)["result"]):
            script = object_mapping(raw)
            result = cdp_command(
                session,
                "Debugger.getScriptSource",
                {"scriptId": string(script["scriptId"])},
            )
            source = string(object_mapping(result)["scriptSource"])
            if source.strip() != SOURCE.strip():
                continue
            offset = source.index("'use strict';")
            for start, end in executed_ranges(object_list(script["functions"])):
                self.covered.update(
                    range(
                        max(0, start - offset), min(len(SOURCE), end - offset)
                    )
                )
            self.samples += 1

    def assert_threshold(self) -> None:
        """Persist the report and require executed coverage above 91%."""
        percentage = 100 * len(self.covered) / len(SOURCE)
        report = Path("test-results/frontend-coverage.json")
        report.parent.mkdir(parents=True, exist_ok=True)
        _ = report.write_text(
            json.dumps(
                {
                    "source": "gui_calculator/oscillator_dashboard/chart.js",
                    "metric": (
                        "V8 executed character ranges (not Python or branch"
                        " coverage)"
                    ),
                    "covered": len(self.covered),
                    "total": len(SOURCE),
                    "percentage": percentage,
                    "minimum": MINIMUM_COVERAGE,
                    "samples": self.samples,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        assert self.samples, "No production dashboard scripts were measured."
        assert (
            percentage >= MINIMUM_COVERAGE
        ), f"Chart JS coverage: {percentage:.2f}% < {MINIMUM_COVERAGE}%"
