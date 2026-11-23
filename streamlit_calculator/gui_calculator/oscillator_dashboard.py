# Copyright 2026 anchored-vwam-backtest contributors
"""Render the standalone oscillator dashboard using recorded chart data."""

from pathlib import Path

import plotly.graph_objects as go


def oscillator_dashboard_html(chart: go.Figure) -> str:
    """Embed real observations in the local Canvas dashboard.

    Returns:
        Self-contained HTML with no external scripts or simulated observations.

    """
    assets = Path(__file__).with_suffix("")
    template = (assets / "index.html").read_text(encoding="utf-8")
    if any(
        isinstance(trace, go.Scatter)
        and trace.name == "margin_loan_oscillator_rate"
        for trace in chart.data
    ):
        template = (
            template.replace("Limit Orders", "Margin Loan")
            .replace("LIMIT ORDERS", "MARGIN LOAN")
            .replace("ORDER BOOK INTELLIGENCE", "MARGIN BORROWING")
            .replace(
                "resting limit-order pressure", "margin borrowing composition"
            )
            .replace(
                "uploaded resting bid/ask liquidity",
                "uploaded margin loan balances",
            )
            .replace("limit order oscillator", "margin loan oscillator")
            .replace(
                "limit_order_oscillator_rate", "margin_loan_oscillator_rate"
            )
            .replace(">30</b> Ask dominant", ">38</b> Base borrowing")
            .replace(">70</b> Bid dominant", ">62</b> Quote borrowing")
            .replace(
                "Recorded order-book depth", "Recorded margin loan balances"
            )
        )
    if isinstance(chart.layout.meta, dict) and (
        chart.layout.meta.get("margin_source") == "bitget_growth"
    ):
        template = (
            template.replace(
                "margin borrowing composition", "loan growth momentum"
            )
            .replace(
                "uploaded margin loan balances", "public Bitget loan growth"
            )
            .replace(
                "Recorded margin loan balances", "Bitget public loan growth"
            )
            .replace("Base borrowing", "Lower momentum")
            .replace("Quote borrowing", "Higher momentum")
        )
    style = (assets / "style.css").read_text(encoding="utf-8")
    script = (assets / "chart.js").read_text(encoding="utf-8")
    # JSON is embedded as script text: escape HTML delimiters so data cannot
    # terminate the element, even if a future market label contains markup.
    payload = chart.to_json().replace("<", "\\u003c").replace(">", "\\u003e")
    return (
        template.replace("__STYLE__", style)
        .replace("__SCRIPT__", script)
        .replace("__DATA__", payload)
    )
