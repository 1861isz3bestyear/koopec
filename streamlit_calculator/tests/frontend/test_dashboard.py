# Copyright 2026 anchored-vwam-backtest contributors
"""Exercise actual canvas rendering, causality, input behavior and contrast."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast

import plotly.graph_objects as go
import pytest
from playwright.sync_api import expect

from gui_calculator.oscillator_charts import oscillator_chart
from gui_calculator.oscillator_dashboard import oscillator_dashboard_html
from tests.frontend.accessibility import (
    assert_accessible,
    assert_canvas_contrast,
)

if TYPE_CHECKING:
    from playwright.sync_api import Page

START = datetime(2026, 11, 5, tzinfo=UTC)
pytestmark = pytest.mark.e2e


def dashboard_html(scenario: str) -> str:
    """Prepare realistic production traces, including gaps and empty feeds.

    Returns:
        The unchanged production HTML template, styles and renderer.

    """
    margin = scenario != "limit"
    days = 7 if scenario == "limit" else 1
    chart = oscillator_chart(title="BTC recorded", price_label="BTCUSDT")
    times = [START + timedelta(hours=index) for index in range(25)]
    values: list[float | None] = [20, 25, 50, 80, 50] * 5
    if scenario == "empty":
        times, values = [], []
    elif scenario == "single":
        times, values = times[-1:], values[-1:]
    elif scenario == "bitget":
        values[-2] = None
    _ = chart.add_trace(
        go.Scatter(
            x=times,
            y=[80000 + index for index in range(len(times))],
            name="Price",
        )
    )
    _ = chart.add_trace(
        go.Scatter(
            x=times,
            y=[
                value if value is not None else float("nan") for value in values
            ],
            name=(
                "margin_loan_oscillator_rate"
                if margin
                else "limit_order_oscillator_rate"
            ),
        )
    )
    _ = chart.update_xaxes(range=[START, START + timedelta(days=days)])
    if scenario == "bitget":
        _ = chart.update_layout(
            meta={"margin_source": "bitget_growth", "growth_period": "24h"}
        )
    return oscillator_dashboard_html(chart)


@pytest.mark.parametrize(
    "scenario", ["limit", "margin", "bitget", "single", "empty"]
)
@pytest.mark.parametrize("width", [390, 1440])
def test_canvas_interactions(
    browser_page: Page, scenario: str, width: int
) -> None:
    """Render every source at phone/desktop widths and restore exact pixels."""
    page = browser_page
    page.set_viewport_size({"width": width, "height": 1200})
    _ = cast(
        "object",
        page.evaluate(
            Path(__file__).with_name("canvas_contrast.js").read_text()
        ),
    )
    page.set_content(dashboard_html(scenario))
    chart = page.locator("#chart")
    expect(chart).to_be_visible()
    baseline = chart.screenshot()
    box = chart.bounding_box()
    assert box is not None
    x, y = box["x"] + box["width"] * 0.6, box["y"] + 120
    page.mouse.move(x, y)
    expect(page.locator("#tooltip")).to_be_visible()
    expect(page.locator("#tooltip")).to_contain_text("UTC")
    if scenario in {"empty", "single"}:
        expect(page.locator("#tooltip")).to_contain_text("No observation")
        if scenario == "empty":
            expect(page.locator("#last-price")).to_have_text("Unavailable")
    else:
        expect(page.locator("#tooltip")).to_contain_text("80,0")
    page.mouse.wheel(0, -600)
    page.mouse.down()
    page.mouse.move(x - 50, y)
    page.mouse.up()
    assert chart.screenshot() != baseline
    page.get_by_role("button", name="Reset view").click()
    expect(page.locator("#tooltip")).to_be_hidden()
    assert chart.screenshot() == baseline
    page.mouse.move(x, y)
    page.mouse.wheel(0, -500)
    page.mouse.dblclick(x, y)
    assert chart.screenshot() == baseline
    assert_accessible(page)
    assert_canvas_contrast(page)
    overflow = cast(
        "object",
        page.evaluate("document.documentElement.scrollWidth > innerWidth"),
    )
    assert overflow is False


def test_reset_keyboard_focus(browser_page: Page) -> None:
    """Reset is keyboard reachable and visibly focused."""
    page = browser_page
    page.set_content(dashboard_html("margin"))
    reset = page.get_by_role("button", name="Reset view")
    reset.focus()
    expect(reset).to_be_focused()
    page.keyboard.press("Tab")
    page.keyboard.press("Shift+Tab")
    expect(reset).to_be_focused()
    expect(reset).to_have_css("outline-style", "solid")
    page.keyboard.press("Enter")
    expect(page.locator("#tooltip")).to_be_hidden()


def test_low_contrast_is_rejected(browser_page: Page) -> None:
    """Prove the audit fails when text approaches its background brightness."""
    page = browser_page
    page.set_content(dashboard_html("margin"))
    _ = page.add_style_tag(content=".subtitle {color: #e0e0e0}")
    with pytest.raises(AssertionError, match="color-contrast"):
        assert_accessible(page)
