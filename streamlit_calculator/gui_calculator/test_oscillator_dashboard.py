# Copyright 2026 anchored-vwam-backtest contributors
"""Verify the Canvas dashboard embeds recorded data safely and locally."""

import plotly.graph_objects as go

from gui_calculator.live_oscillators import oscillator_chart
from gui_calculator.oscillator_dashboard import oscillator_dashboard_html


def test_dashboard_uses_real_traces_and_local_assets() -> None:
    """Preserve uploaded observations without demo generation or CDN access."""
    chart = oscillator_chart(title="ETH recorded depth", price_label="ETHUSDT")
    _ = chart.add_trace(
        go.Scatter(x=["2026-11-04T12:00:00Z"], y=[3123], name="Price"),
        row=1,
        col=1,
    )
    html = oscillator_dashboard_html(chart)
    assert '"y":[3123]' in html
    assert 'id="market-data"' in html
    assert "new ResizeObserver(draw)" in html
    assert "REAL DATA" in html
    assert "Synthetic" not in html
    assert "makeData" not in html
    assert "__DATA__" not in html
    assert 'src="' not in html


def test_dashboard_escapes_script_delimiters() -> None:
    """A chart label cannot terminate the embedded JSON script element."""
    chart = oscillator_chart(
        title="</script><script>alert(1)</script>", price_label="BTCUSDT"
    )
    html = oscillator_dashboard_html(chart)
    assert "</script><script>alert(1)" not in html
    assert r"\u003c" in html
    assert r"\u003e" in html


def test_margin_dashboard_uses_loan_labels_and_observations() -> None:
    """Render margin balances with their own identity and threshold labels."""
    chart = oscillator_chart(
        title="BTC margin_loan_oscillator_rate",
        price_label="BTCUSDT",
        thresholds=(38, 62),
    )
    _ = chart.add_trace(
        go.Scatter(
            x=["2026-11-04T12:00:00Z"],
            y=[65],
            name="margin_loan_oscillator_rate",
        ),
        row=2,
        col=1,
    )
    html = oscillator_dashboard_html(chart)
    assert '"y":[65]' in html
    assert "<title>Margin Loan Oscillator</title>" in html
    assert ">38</b> Base borrowing" in html
    assert ">62</b> Quote borrowing" in html
    assert "Recorded margin loan balances" in html
    assert "ORDER BOOK INTELLIGENCE" not in html
    assert "Recorded order-book depth" not in html
    assert (
        "const rateTrace = payload.data.find(trace => trace.name === rateName)"
        in html
    )
