# Copyright 2026 anchored-vwam-backtest contributors
"""Verify real Streamlit controls and embedded GEX margin charts in Chromium."""

import re
from typing import TYPE_CHECKING, cast

import pytest
from playwright.sync_api import expect
from shared.validation import object_list, object_mapping, string

from tests.frontend.accessibility import assert_accessible

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.e2e
PHONE_WIDTH = 390


def select(page: Page, label: str, option: str) -> None:
    """Choose a named Streamlit selectbox using its accessible browser roles."""
    control = page.get_by_role("combobox", name=label, exact=True)
    control.scroll_into_view_if_needed()
    expect(control).to_be_in_viewport()
    control.fill(option)
    expect(page.get_by_role("option", name=option, exact=True)).to_be_visible()
    control.press("ArrowDown")
    control.press("Enter")
    expect(control).to_have_value(option)


def test_backtester_theme_and_controls(
    browser_page: Page, calculator_url: str, calculator_theme: str
) -> None:
    """Verify charts, controls and contrast in both themes."""
    page = browser_page
    _ = page.goto(calculator_url + "/?archive=1")
    expect(
        page.get_by_role("heading", name="Anchored VWAP Backtester")
    ).to_be_visible()
    expect(page.get_by_test_id("stMetricValue").first).to_be_visible()
    expect(page.get_by_test_id("stException")).to_have_count(0)
    expect(page.get_by_test_id("stPlotlyChart").first).to_be_visible()
    expected_background = {
        "light": "rgb(255, 255, 255)",
        "dark": "rgb(14, 17, 23)",
    }[calculator_theme]
    expect(page.get_by_test_id("stApp")).to_have_css(
        "background-color", expected_background
    )
    expect(
        page.get_by_role("combobox", name="Strategy", exact=True)
    ).to_be_disabled()
    expect(page.get_by_label("Open order VWAP", exact=False)).to_have_count(0)
    expect(page.get_by_test_id("stMetricValue").first).to_be_visible()
    page.get_by_test_id("stSidebar").hover()
    collapse = page.get_by_test_id("stSidebarCollapseButton").get_by_role(
        "button", include_hidden=True
    )
    expect(collapse).to_have_attribute("aria-expanded", "true")
    collapse.click()
    expand = page.get_by_test_id("stExpandSidebarButton")
    expect(expand).to_be_visible()
    expect(expand).to_have_attribute("aria-expanded", "false")
    expand.click()
    expect(collapse).to_have_attribute("aria-expanded", "true")
    assert_accessible(page)


@pytest.mark.parametrize("width", [PHONE_WIDTH, 1280])
def test_gex_shared_oscillator_timeline(
    browser_page: Page, calculator_url: str, width: int
) -> None:
    """Verify all four real Plotly panels share ranges, zoom and reset."""
    page = browser_page
    page.set_viewport_size({"width": width, "height": 1200})
    _ = page.goto(calculator_url + "/?analytics=1")
    page.get_by_role("button", name="Calculate", exact=True).click()
    expect(
        page.get_by_role("heading", name="BTC · GEX terminal")
    ).to_be_visible()
    page.get_by_text("Show snapshot oscillators", exact=True).click()
    chart = (
        page.get_by_test_id("stPlotlyChart")
        .filter(has_text="BTC · snapshot oscillators")
        .locator(".js-plotly-plot")
    )
    expect(chart).to_be_visible()
    assert chart.evaluate("""plot => {
        const cutoff = Date.parse(plot.layout.xaxis.range[1]);
        const reference = Date.parse(plot.layout.shapes[0].x0);
        const margin = plot.data.find(trace =>
            trace.name === 'Margin loan growth momentum');
        return cutoff > reference && margin.x.some((time, index) =>
            Date.parse(time) > reference && margin.y[index] !== null);
    }""")
    select(page, "Oscillator data time", "Selected options snapshot")
    expect(
        page.get_by_text("Mode: Selected options snapshot.", exact=False)
    ).to_be_visible()
    assert chart.evaluate("""plot => {
        const reference = Date.parse(plot.layout.shapes[0].x0);
        const margin = plot.data.find(trace =>
            trace.name === 'Margin loan growth momentum');
        return Date.parse(plot.layout.xaxis.range[1]) === reference
            && margin.x.every(time => Date.parse(time) <= reference);
    }""")
    select(page, "Oscillator data time", "Latest available")
    expect(
        page.get_by_text("Mode: Latest available.", exact=False)
    ).to_be_visible()
    assert chart.evaluate("""plot => {
        return plot.data.every(trace => trace.xaxis === 'x')
            && ['yaxis', 'yaxis2', 'yaxis3', 'yaxis4'].every(key =>
                plot._fullLayout[key].anchor === 'x')
            && new Set(plot.data.map(trace => trace.yaxis)).size === 4
            && plot.layout.shapes.some(shape => shape.yref === 'paper'
                && shape.y0 === 0 && shape.y1 === 1 && shape.x0 === shape.x1);
    }""")
    # Move through each panel at the same horizontal position. The cursor must
    # span the entire figure, including panels with different sampling times.
    for axis in ("yaxis", "yaxis2", "yaxis3", "yaxis4"):
        position = object_mapping(
            cast(
                "object",
                chart.evaluate(
                    """(plot, key) => {
                    const layout = plot._fullLayout;
                    return {x: layout.xaxis._offset + layout.xaxis._length / 2,
                        y: layout[key]._offset + layout[key]._length / 2};
                }""",
                    axis,
                ),
            )
        )
        x, y = position["x"], position["y"]
        assert isinstance(x, (int, float))
        assert isinstance(y, (int, float))
        chart.hover(position={"x": x, "y": y})
        expect(chart.locator("line.spikeline")).to_have_count(2)
        assert chart.evaluate("""plot => {
            const lines = [...plot.querySelectorAll('line.spikeline')];
            const size = plot._fullLayout._size;
            return lines.every(line =>
                Math.abs(+line.getAttribute('y1') - size.t) < 1
                && Math.abs(+line.getAttribute('y2') - size.t - size.h) < 1
                && line.getAttribute('x1') === line.getAttribute('x2'));
        }""")
    # Playwright returns Any; validate its untrusted result as a mapping.
    baseline_ranges = object_mapping(
        cast(
            "object",
            chart.evaluate("""plot =>
        Object.fromEntries(Object.entries(plot._fullLayout)
            .filter(([key]) => /[xy]axis/.test(key))
            .map(([key, axis]) => [key, axis.range]))
    """),
        )
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    chart.hover(position={"x": 10, "y": 10})
    baseline = chart.screenshot(animations="disabled")
    chart.scroll_into_view_if_needed()
    bounds = chart.bounding_box()
    assert bounds is not None
    page.mouse.move(bounds["x"] + bounds["width"] * 0.4, bounds["y"] + 160)
    page.mouse.down()
    page.mouse.move(
        bounds["x"] + bounds["width"] * 0.65, bounds["y"] + 230, steps=8
    )
    page.mouse.up()
    assert (
        chart.evaluate("plot => plot._fullLayout.xaxis.range")
        != baseline_ranges["xaxis"]
    )
    assert chart.evaluate("""plot => plot.data.every(
        trace => trace.xaxis === 'x')""")
    page.get_by_role("button", name="Reset axes").last.click()
    chart.hover(position={"x": 10, "y": 10})
    assert (
        chart.evaluate(
            "plot => Object.fromEntries(\n       "
            " Object.entries(plot._fullLayout).filter(([key]) =>"
            " /[xy]axis/.test(key))\n        .map(([key, axis]) => [key,"
            " axis.range]))"
        )
        == baseline_ranges
    )
    assert chart.screenshot(animations="disabled") == baseline
    expect(page.get_by_test_id("stException")).to_have_count(0)
    assert_accessible(page)


def test_snapshot_tunnel_controls(
    browser_page: Page, calculator_url: str
) -> None:
    """Expose the single local strategy and its independent confirmations."""
    page = browser_page
    _ = page.goto(calculator_url)
    expect(
        page.get_by_role("combobox", name="Strategy", exact=True)
    ).to_have_value("Snapshot tunnel")
    expect(
        page.get_by_role("combobox", name="Strategy", exact=True)
    ).to_be_disabled()
    select(page, "Tunnel state", "State 3: both")
    cap = page.get_by_label(
        "Negative-GEX long TP below gamma flip, %", exact=True
    )
    page.get_by_text(
        "Cap negative-GEX long TP below gamma flip", exact=True
    ).click()
    expect(cap).to_be_disabled()
    page.get_by_text(
        "Cap negative-GEX long TP below gamma flip", exact=True
    ).click()
    expect(cap).to_be_enabled()
    page.get_by_text("Confirm with margin-loan oscillator", exact=True).click()
    expect(page.get_by_text("Active sources: 2.", exact=False)).to_be_visible()
    page.get_by_text("Confirm with OI oscillator", exact=True).click()
    expect(page.get_by_text("Active sources: 3.", exact=False)).to_be_visible()
    select(page, "Required agreeing oscillators", "3")
    expect(
        page.get_by_label("OI confirmation regime", exact=True)
    ).to_be_disabled()
    expect(
        page.get_by_text(
            "Enabled oscillators use stored receipts.", exact=False
        )
    ).to_be_visible()
    expect(page.get_by_test_id("stFileUploader")).to_have_count(0)
    expect(
        page.get_by_role("button", name="Confirm and load data", exact=True)
    ).to_have_count(0)
    expect(page.get_by_test_id("stException")).to_have_count(0)
    assert_accessible(page)


def test_child_assets_mirror_btc_in_real_ui(
    browser_page: Page, calculator_url: str
) -> None:
    """Select both children and render separate accounts in both themes."""
    page = browser_page
    _ = page.goto(calculator_url + "/?archive=1")
    expect(
        page.get_by_role("combobox", name="Workspace", exact=True)
    ).to_have_count(0)
    expect(
        page.get_by_role("switch", name="Load local GEX archive")
    ).to_be_checked()
    expect(
        page.get_by_role("textbox", name="Local GEX archive path")
    ).to_have_value(re.compile(r".*tunnel_inputs\.sqlite$"))
    page.get_by_text("Confirm with GEX state", exact=True).click()
    children = (
        page.get_by_test_id("stMultiSelect")
        .filter(has=page.get_by_text("Child Assets", exact=True))
        .get_by_role("combobox")
    )
    for symbol in ("DOGEUSDT", "XRPUSDT"):
        children.fill(symbol)
        page.get_by_role("option", name=symbol, exact=True).click()
        children.press("Escape")
    expect(
        page.get_by_role("heading", name="Child Assets", exact=True)
    ).to_be_visible()
    expect(
        page.get_by_role("button", name="Download child trades CSV", exact=True)
    ).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("stException")).to_have_count(0)
    expect(
        page.get_by_text("Cannot simulate Child Assets:", exact=False)
    ).to_have_count(0)
    assert_accessible(page)
    page.get_by_text("Simulate trades", exact=True).click()
    expect(children).to_be_disabled()
    expect(
        page.get_by_role("heading", name="Child Assets", exact=True)
    ).to_have_count(0)


def test_tunnel_export_from_local_archive(
    browser_page: Page, calculator_url: str
) -> None:
    """Export the only supported strategy directly from the local archive."""
    page = browser_page
    _ = page.goto(calculator_url)
    expect(
        page.get_by_role("combobox", name="Strategy", exact=True)
    ).to_have_value("Snapshot tunnel")
    expect(
        page.get_by_role("combobox", name="Tunnel state", exact=True)
    ).to_be_visible()
    expect(
        page.get_by_role(
            "combobox", name="Required agreeing oscillators", exact=True
        )
    ).to_have_value("1")
    page.get_by_text("Confirm with limit-order oscillator", exact=True).click()
    expect(
        page.get_by_role("button", name="Save paper bot config", exact=True)
    ).to_be_enabled()
    expect(
        page.get_by_role("button", name="Download paper bot config", exact=True)
    ).to_be_enabled()
    expect(
        page.get_by_role("button", name="Confirm and load data", exact=True)
    ).to_have_count(0)
    expect(page.get_by_test_id("stException")).to_have_count(0)
    assert_accessible(page)


def test_margin_refresh_replaces_cached_data_without_new_options(
    browser_page: Page, calculator_url: str
) -> None:
    """Show newly published lending while keeping historical cutoffs causal."""
    page = browser_page
    _ = page.goto(calculator_url + "/?analytics=1&growth_refresh=1")
    page.get_by_role("button", name="Calculate", exact=True).click()
    page.get_by_text("Show snapshot oscillators", exact=True).click()
    select(page, "Oscillator history", "24 hours")
    chart = (
        page.get_by_test_id("stPlotlyChart")
        .filter(has_text="BTC · snapshot oscillators")
        .locator(".js-plotly-plot")
    )
    expect(chart).to_be_visible()
    reference = string(
        cast(
            "object",
            page.wait_for_function("""() => {
        for (const plot of document.querySelectorAll('.js-plotly-plot')) {
            const margin = plot.data?.find(trace =>
                trace.name === 'Margin loan growth momentum');
            const reference = plot.layout?.shapes?.[0]?.x0;
            if (margin && reference && margin.x.at(-1) === reference)
                return reference;
        }
        return false;
    }""").json_value(),
        )
    )
    page.get_by_role("button", name="Refresh margin data", exact=True).click()
    _ = page.wait_for_function(
        """expected =>
        [...document.querySelectorAll('.js-plotly-plot')].some(plot => {
            const margin = plot.data?.find(trace =>
                trace.name === 'Margin loan growth momentum');
            const reference = plot.layout?.shapes?.[0]?.x0;
            return margin && reference === expected
                && Date.parse(margin.x.at(-1)) > Date.parse(reference)
                && margin.y.at(-1) !== null;
        })
    """,
        arg=reference,
    )
    select(page, "Oscillator data time", "Selected options snapshot")
    page.get_by_role("button", name="Refresh margin data", exact=True).click()
    expect(
        page.get_by_text("Mode: Selected options snapshot.", exact=False)
    ).to_be_visible()
    _ = page.wait_for_function(
        """expected =>
        [...document.querySelectorAll('.js-plotly-plot')].some(plot => {
            const margin = plot.data?.find(trace =>
                trace.name === 'Margin loan growth momentum');
            const reference = plot.layout?.shapes?.[0]?.x0;
            return margin && reference === expected
                && Date.parse(plot.layout.xaxis.range[1]) ===
                    Date.parse(reference)
                && margin.x.every(time => Date.parse(time) <=
                    Date.parse(reference));
        })
    """,
        arg=reference,
    )
    expect(page.get_by_test_id("stException")).to_have_count(0)
    assert_accessible(page)


def test_local_archive_default_path(
    browser_page: Page, calculator_url: str
) -> None:
    """Load real SQLite inputs with scoped dates and visible GEX traces."""
    page = browser_page
    _ = page.goto(calculator_url + "/?archive=1")
    expect(
        page.get_by_role("combobox", name="Workspace", exact=True)
    ).to_have_count(0)
    expect(
        page.get_by_role("switch", name="Load local GEX archive")
    ).to_be_checked()
    expect(
        page.get_by_role("textbox", name="Local GEX archive path")
    ).to_have_value(re.compile(r".*tunnel_inputs\.sqlite$"))
    expect(
        page.get_by_role("combobox", name="Strategy", exact=True)
    ).to_have_value("Snapshot tunnel")
    expect(
        page.get_by_role("combobox", name="Strategy", exact=True)
    ).to_be_disabled()
    expect(
        page.get_by_text("Archived BTC strategy window (UTC):", exact=False)
    ).to_be_visible()
    expect(page.get_by_text("Duration:", exact=False)).to_be_visible()
    coverage = page.get_by_text(
        "Archived BTC strategy window (UTC):", exact=False
    ).inner_text()
    for label in ("History start", "History end"):
        date = (
            page.get_by_test_id("stDateInput")
            .filter(has=page.get_by_text(label, exact=True))
            .locator("input")
            .input_value()
            .replace("/", "-")
        )
        assert date in coverage

    expect(page.get_by_label("Execution depth CSV", exact=True)).to_have_count(
        0
    )
    expect(
        page.get_by_text("Options GEX snapshots CSV (optional)", exact=True)
    ).to_have_count(0)
    expect(
        page.get_by_role("button", name="Confirm and load data", exact=True)
    ).to_have_count(0)
    expect(page.get_by_test_id("stException")).to_have_count(0)
    expect(page.get_by_test_id("stPlotlyChart").last).to_be_visible(
        timeout=30000
    )
    chart = page.locator(".js-plotly-plot").last
    names = [
        string(value)
        for value in object_list(
            cast(
                "object",
                chart.evaluate(
                    "element => element.data.map(trace => trace.name)"
                ),
            )
        )
    ]
    assert "Limit-order confirms long" in names
    assert "Limit-order confirms short" in names
    assert "Margin-loan confirms long" not in names
    assert "OI divergence confirms long" not in names
    assert "Anchored VWAP" not in names
    for label in (
        "Show VWAP \N{GREEK SMALL LETTER SIGMA} bands",
        "Paper bot VWAP reset, weeks",
        "Anchor before strategy start",
    ):
        expect(page.get_by_text(label, exact=True)).to_have_count(0)
    assert "Close (levels)" not in names
    assert "Net GEX" in names
    assert "Gamma flip" in names
    assert "Put 1" in names
    assert "Put 2" in names
    assert "Call 1" in names
    assert "Call 2" in names
    _ = page.wait_for_function("""() => {
        const figures = document.querySelectorAll('.js-plotly-plot');
        const element = figures[figures.length - 1];
        if (!element) return false;
        const gex = element.data.find(trace => trace.name === 'Net GEX');
        const book = element.data.find(trace =>
            trace.name === 'Limit-order oscillator');
        const margin = element.data.find(trace =>
            trace.name === 'Margin-loan oscillator');
        const oi = element.data.find(trace => trace.name === 'OI momentum');
        const state = element.data.find(trace =>
            trace.name === 'OI divergence state');
        return gex && book && margin && oi && state &&
            gex.mode === 'lines' && gex.line.shape === 'linear' &&
            book.yaxis !== margin.yaxis &&
            gex.x.length >= 4 &&
            Date.parse(gex.x[1]) - Date.parse(gex.x[0]) === 300000 &&
            [book, margin, oi, state].every(trace =>
                trace.mode === 'lines' && trace.connectgaps === false) &&
            ['Gamma flip', 'Call 1', 'Call 2', 'Put 1', 'Put 2'].every(
                name => element.data.find(trace => trace.name === name)
                    .yaxis === 'y') &&
            element.layout.yaxis5 == null &&
            element.layout.title.text !== 'undefined';
    }""")
    assert page.locator(".js-plotly-plot").evaluate_all("""figures => {
        const history = figures.find(figure =>
            (figure.layout.title?.text || '').includes(
                'GEX history · recorded observations'));
        if (!history) return false;
        const spot = history.data.find(trace =>
            trace.name === 'BTC snapshot spot');
        const flip = history.data.find(trace => trace.name === 'Gamma flip');
        const book = history.data.find(trace =>
            trace.name === 'Limit-order oscillator');
        const margin = history.data.find(trace =>
            trace.name === 'Margin-loan oscillator');
        return spot.yaxis === 'y2' && flip.yaxis === 'y2' &&
            ['Call 1', 'Call 2', 'Put 1', 'Put 2'].every(name =>
                history.data.find(trace => trace.name === name)
                    .yaxis === 'y2') &&
            book.yaxis === 'y3' && margin.yaxis === 'y4' &&
            history._fullLayout.yaxis2.range[0] <=
                Math.min(...history.calcdata[history.data.indexOf(spot)]
                    .map(point => point.y).filter(Number.isFinite)) &&
            history._fullLayout.yaxis2.range[1] >=
                Math.max(...history.calcdata[history.data.indexOf(flip)]
                    .map(point => point.y).filter(Number.isFinite)) &&
            history.layout.yaxis3.matches == null &&
            history.data.find(trace => trace.name === 'Call 2')
                .line.dash === 'dot';
    }""") is True
    assert page.locator(".js-plotly-plot").evaluate_all(r"""figures => {
            const prices = figures.find(figure =>
                (figure.layout.title?.text || '').includes(
                        'Ranked call/put levels'));
            const exposure = figures.find(figure =>
                (figure.layout.annotations || []).some(annotation =>
                    annotation.text.startsWith('<b>P1 · CALL')));
            if (!prices || !exposure) return false;
            return [['Call 1', 'P1'], ['Call 2', 'P2'],
                    ['Put 1', 'N1'], ['Put 2', 'N2']].every(([name, rank]) => {
                const trace = prices.data.find(item => item.name === name);
                const badge = exposure.layout.annotations.find(item =>
                    item.text.startsWith('<b>' + rank + ' ·'));
                if (!trace || !badge || trace.fill) return false;
                const value = badge.text.match(/\$([\d,]+)/);
                return value && Math.round(trace.y[0]) ===
                    Number(value[1].replaceAll(',', ''));
            });
        }""") is True
    assert_accessible(page)


def test_oscillator_only_confirmation_controls(
    browser_page: Page, calculator_url: str
) -> None:
    """Trade from book votes alone and expose independent OI regimes."""
    page = browser_page
    _ = page.goto(calculator_url + "/?archive=1")
    expect(
        page.get_by_role("combobox", name="Workspace", exact=True)
    ).to_have_count(0)
    expect(
        page.get_by_role("switch", name="Load local GEX archive")
    ).to_be_checked()
    expect(
        page.get_by_role("textbox", name="Local GEX archive path")
    ).to_have_value(re.compile(r".*tunnel_inputs\.sqlite$"))
    expect(page.get_by_test_id("stPlotlyChart").last).to_be_visible()
    page.get_by_text("Confirm with GEX state", exact=True).click()
    chart = page.locator(".js-plotly-plot").last
    _ = page.wait_for_function("""() => {
        const figures = document.querySelectorAll('.js-plotly-plot');
        const plot = figures[figures.length - 1];
        if (!plot) return false;
        const book = plot.data.find(trace =>
            trace.name === 'Limit-order confirms long');
        return book && book.x.length > 0 &&
            !plot.data.some(trace => trace.name === 'GEX state confirms long');
    }""")
    trades = (
        page.get_by_test_id("stMetric")
        .filter(has=page.get_by_text("Trades", exact=True))
        .get_by_test_id("stMetricValue")
    )
    expect(trades).not_to_have_text("0")
    page.get_by_text("Confirm with limit-order oscillator", exact=True).click()
    expect(
        page.get_by_text(
            "Enable at least one oscillator to authorize trades.", exact=True
        )
    ).to_be_visible()
    expect(trades).to_have_text("0")
    page.get_by_text("Confirm with OI oscillator", exact=True).click()
    select(page, "OI confirmation regime", "Convergence")
    _ = page.wait_for_function("""() => {
        const figures = document.querySelectorAll('.js-plotly-plot');
        const plot = figures[figures.length - 1];
        return plot && plot.data.some(trace =>
            trace.name === 'OI convergence confirms long') &&
            !plot.data.some(trace =>
                trace.name === 'OI divergence confirms long');
    }""")
    select(page, "OI confirmation regime", "Momentum")
    _ = page.wait_for_function("""() => {
        const figures = document.querySelectorAll('.js-plotly-plot');
        const plot = figures[figures.length - 1];
        return plot && plot.data.some(trace => trace.name ===
            'High OI momentum (either direction) confirms either breakout') &&
            !plot.data.some(trace =>
                trace.name === 'OI convergence confirms long');
    }""")
    expect(chart).to_be_visible()
    expect(page.get_by_test_id("stException")).to_have_count(0)
    assert_accessible(page)


def test_option_level_range_changes_rendered_levels(
    browser_page: Page, calculator_url: str
) -> None:
    """Apply the range to real profiles and restore levels when disabled."""
    page = browser_page
    _ = page.goto(calculator_url + "/?archive=1")
    expect(
        page.get_by_role("combobox", name="Workspace", exact=True)
    ).to_have_count(0)
    expect(
        page.get_by_role("switch", name="Load local GEX archive")
    ).to_be_checked()
    expect(
        page.get_by_role("textbox", name="Local GEX archive path")
    ).to_have_value(re.compile(r".*tunnel_inputs\.sqlite$"))
    percent = page.get_by_label(
        "Option level range from current price, %", exact=True
    )
    expect(percent).to_have_value("20.00")
    _ = page.wait_for_function("""() => {
        const plot = [...document.querySelectorAll('.js-plotly-plot')]
            .find(plot => plot.data.some(t => t.name === 'Snapshot spot'));
        return plot && plot.data.some(t =>
            /^(Call |Put |Option border )/.test(t.name));
    }""")
    percent.fill("0.01")
    percent.press("Enter")
    _ = page.wait_for_function("""() => {
        const plot = [...document.querySelectorAll('.js-plotly-plot')]
            .find(plot => plot.data.some(t => t.name === 'Snapshot spot'));
        return plot && !plot.data.some(t =>
            /^(Call |Put |Option border )/.test(t.name));
    }""")
    page.get_by_text("Limit option levels to price range", exact=True).click()
    expect(percent).to_be_disabled()
    expect(percent).to_have_value("0.01")
    _ = page.wait_for_function("""() => {
        const plot = [...document.querySelectorAll('.js-plotly-plot')]
            .find(plot => plot.data.some(t => t.name === 'Snapshot spot'));
        return plot && plot.data.some(t =>
            /^(Call |Put |Option border )/.test(t.name));
    }""")
    page.get_by_text("Limit option levels to price range", exact=True).click()
    expect(percent).to_be_enabled()
    expect(percent).to_have_value("0.01")
    percent.fill("35")
    percent.press("Enter")
    expect(percent).to_have_value("35.00")
    expect(page.get_by_test_id("stException")).to_have_count(0)
    assert_accessible(page)


def test_archive_path_error_and_recovery(
    browser_page: Page, calculator_url: str
) -> None:
    """A typed path error remains editable and can restore the archive."""
    page = browser_page
    _ = page.goto(calculator_url + "/?archive=1")
    path = page.get_by_role("textbox", name="Local GEX archive path")
    coverage = page.get_by_text("Archived BTC strategy window (UTC):")
    expect(path).to_have_value(re.compile(r".*tunnel_inputs\.sqlite$"))
    expect(coverage).to_be_visible()
    original = path.input_value()
    path.fill(original + ".missing")
    path.press("Enter")
    expect(
        page.get_by_text("Cannot read local archive", exact=False)
    ).to_be_visible()
    expect(page.get_by_test_id("stException")).to_have_count(0)
    path.fill(original)
    path.press("Enter")
    expect(coverage).to_be_visible()
    expect(
        page.get_by_text("Cannot read local archive", exact=False)
    ).to_have_count(0)
    assert_accessible(page)
