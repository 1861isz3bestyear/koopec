# Copyright 2026 anchored-vwam-backtest contributors
"""Verify line histories retain independent oscillator publication times."""

from dataclasses import replace
from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from shared.validation import json_object, object_list, object_mapping
from snapshot_tunnel.archived_market import ArchivedOscillators, ArchivedRate
from snapshot_tunnel.oi_divergence import (
    DivergenceSeries,
    DivergenceSettings,
    InterestSample,
    MarketSample,
    MomentumPoint,
    divergence_series,
)
from snapshot_tunnel.options_model import parse_snapshots

from gui_calculator.observed_chart import (
    add_observed_oscillators,
    style_observed_chart,
)
from gui_calculator.observed_history import RecordedCharts
from gui_calculator.observed_oscillators import oscillator_lines
from gui_calculator.options_gex import EXAMPLE
from gui_calculator.test_oi_divergence import PRICES, market_samples


def test_source_cadence_gaps_and_warmup_are_preserved() -> None:
    """Hourly margin never becomes five-minute values or zero warmup votes."""
    now = parse_snapshots(EXAMPLE)[0].timestamp
    book = tuple(
        ArchivedRate(
            observed=now + timedelta(minutes=m),
            available=now + timedelta(minutes=m),
            value=60,
        )
        for m in (0, 10)
    )
    margin = tuple(
        ArchivedRate(
            observed=now + timedelta(hours=h),
            available=now + timedelta(hours=h),
            value=70,
        )
        for h in (0, 1)
    )
    point = MomentumPoint(
        sample=MarketSample(
            interest=InterestSample(timestamp=now, value=100),
            price=80000,
            received=now,
        ),
        rate=None,
    )
    streams = ArchivedOscillators(
        order_book=book,
        margin=margin,
        oi=DivergenceSeries(points=(point,), states=(None,), signals=()),
    )
    candles = pd.DataFrame({"time": [now, now + timedelta(hours=1)]})
    lines = oscillator_lines(streams, candles)
    assert lines[0].data["value"].isna().sum() == 1
    assert list(lines[1].data["time"]) == [p.available for p in margin]
    assert not lines[1].data["value"].isna().any()
    assert lines[2].data["value"].isna().all()
    assert lines[3].data["value"].isna().all()
    assert lines[4].data["value"].isna().all()
    chart = go.Figure()
    add_observed_oscillators(
        chart, RecordedCharts(gex=pd.DataFrame(), oscillators=lines)
    )
    payload = json_object(chart.to_json())
    traces = [object_mapping(trace) for trace in object_list(payload["data"])]
    assert [trace["name"] for trace in traces] == [line.name for line in lines]
    assert [trace["yaxis"] for trace in traces] == [
        "y6",
        "y7",
        "y8",
        "y9",
        "y9",
    ]
    assert all(trace["mode"] == "lines" for trace in traces)
    assert all(trace["connectgaps"] is False for trace in traces)
    assert object_mapping(traces[3]["line"])["dash"] == "solid"
    assert object_mapping(traces[4]["line"])["dash"] == "dash"
    themed = object_mapping(
        json_object(style_observed_chart(chart).to_json())["layout"]
    )
    assert themed["plot_bgcolor"] == "#ffffff"
    assert object_mapping(themed["xaxis"])["griddash"] == "dot"


def test_convergence_and_divergence_can_overlap() -> None:
    """Plot independent momentum divergence and raw OI convergence."""
    template = market_samples()[0]
    random = np.random.default_rng(12)
    warmup = 146
    value = 1000.0
    samples: list[MarketSample] = []
    for index in range(warmup + len(PRICES) * 4):
        price = 90 if index < warmup else PRICES[(index - warmup) % len(PRICES)]
        value += random.uniform(-3, 3) + (price - 90) * 0.1
        timestamp = template.interest.timestamp + timedelta(minutes=5 * index)
        samples.append(
            replace(
                template,
                price=200 + price,
                interest=replace(
                    template.interest, value=value, timestamp=timestamp
                ),
                received=timestamp,
            )
        )
    series = divergence_series(
        tuple(samples),
        settings=DivergenceSettings(interval=timedelta(minutes=5)),
    )
    streams = ArchivedOscillators(order_book=(), margin=(), oi=series)
    candles = pd.DataFrame(
        {"time": [samples[0].received, samples[-1].received]}
    )
    lines = oscillator_lines(streams, candles)
    divergence = lines[3].data["value"]
    convergence = lines[4].data["value"]
    assert ((divergence == 1) & (convergence == 1)).any()
    assert ((divergence == 0) & (convergence == 0)).any()
    assert convergence.isna().iloc[0]
    assert (convergence == 0).any()
