# Copyright 2026 anchored-vwam-backtest contributors
"""Independent recorded oscillator lines without resampling or filling."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Literal

import pandas as pd
from snapshot_tunnel.archived_market import ArchivedRate
from snapshot_tunnel.local_archive import divergence_votes
from snapshot_tunnel.tunnel import OiConfirmationMode

from gui_calculator.observed_history import OscillatorLine, visible_observations

if TYPE_CHECKING:
    from snapshot_tunnel.archived_market import ArchivedOscillators


def _rate_line(
    name: str,
    rates: tuple[ArchivedRate, ...],
    *,
    candles: pd.DataFrame,
    maximum_gap: timedelta,
    panel: Literal[4, 5, 6, 7] = 4,
) -> OscillatorLine:
    """Clip an independent series and preserve missing receipts.

    Returns:
        A native-time oscillator line with explicit breaks across gaps.

    """
    history = pd.DataFrame({
        "time": pd.to_datetime([point.available for point in rates], utc=True),
        "value": [point.value for point in rates],
    })
    return OscillatorLine(
        name=name,
        data=visible_observations(history, candles, maximum_gap=maximum_gap),
        panel=panel,
    )


def oscillator_lines(
    streams: ArchivedOscillators, candles: pd.DataFrame
) -> tuple[OscillatorLine, ...]:
    """Expose book, margin, OI momentum and both OI states as lines.

    Returns:
        Series with real receipt times and source-specific gap limits.

    """
    momentum = tuple(
        ArchivedRate(
            observed=point.sample.interest.timestamp,
            available=point.available,
            value=point.rate,
        )
        for point in streams.oi.points
    )
    states = tuple(
        ArchivedRate(
            observed=point.observed,
            available=point.available,
            value=state,
        )
        for point, state in zip(momentum, streams.oi.states, strict=True)
    )
    convergence = tuple(
        ArchivedRate(
            observed=point.sample.interest.timestamp,
            available=vote.available,
            value=float(vote.direction != 0) if vote.calculatable else None,
        )
        for point, vote in zip(
            streams.oi.points,
            divergence_votes(streams.oi, mode=OiConfirmationMode.CONVERGENCE),
            strict=True,
        )
    )
    return (
        _rate_line(
            "Limit-order oscillator",
            streams.order_book,
            candles=candles,
            maximum_gap=timedelta(minutes=7, seconds=30),
        ),
        _rate_line(
            "Margin-loan oscillator",
            streams.margin,
            candles=candles,
            maximum_gap=timedelta(minutes=90),
            panel=5,
        ),
        _rate_line(
            "OI momentum",
            momentum,
            candles=candles,
            maximum_gap=timedelta(minutes=7, seconds=30),
            panel=6,
        ),
        _rate_line(
            "OI divergence state",
            states,
            candles=candles,
            maximum_gap=timedelta(minutes=7, seconds=30),
            panel=7,
        ),
        _rate_line(
            "OI convergence state",
            convergence,
            candles=candles,
            maximum_gap=timedelta(minutes=7, seconds=30),
            panel=7,
        ),
    )
