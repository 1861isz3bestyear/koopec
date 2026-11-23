# Copyright 2026 anchored-vwam-backtest contributors
"""Strict, browser-computed accessibility and text contrast assertions."""

from importlib.resources import files
from typing import TYPE_CHECKING, cast

from shared.validation import number, object_list, object_mapping, string

if TYPE_CHECKING:
    from playwright.sync_api import Frame, Page


AAA_CONTRAST = 7
AXE = files("axe_playwright_python").joinpath("axe.min.js").read_text()


def assert_accessible(page: Page | Frame) -> None:
    """Fail on every WCAG A/AA/AAA violation, including text contrast."""
    _ = page.add_script_tag(content=AXE)
    result = cast(
        "object",
        page.evaluate("""async () => await axe.run(document, {
          runOnly: {type: 'tag', values: [
            'wcag2a','wcag2aa','wcag2aaa','wcag21a','wcag21aa',
            'wcag21aaa','wcag22aa'
          ]}
        })"""),
    )
    violations = object_list(object_mapping(result)["violations"])
    messages = [
        string(object_mapping(item)["id"])
        + ": "
        + "; ".join(
            str(object_mapping(node)["target"])
            + " "
            + string(object_mapping(node)["failureSummary"])
            for node in object_list(object_mapping(item)["nodes"])
        )
        for item in violations
    ]
    assert not violations, "\n".join(messages)


def assert_canvas_contrast(page: Page) -> None:
    """Require AAA 7:1 text contrast against rendered canvas pixels."""
    result = cast(
        "object",
        page.evaluate("""() => {
      const luminance = rgb => rgb.map(value => {
        const v = value / 255;
        return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
      }).reduce((sum, value, index) =>
        sum + value * [.2126,.7152,.0722][index], 0);
      return window.canvasTextSamples.map(sample => {
        if (!sample.foreground) return {...sample, ratio: 0};
        const a = luminance(sample.foreground);
        const b = luminance(sample.background);
        return {...sample, ratio: (Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
      });
    }"""),
    )
    samples = object_list(result)
    assert samples, "The browser did not record any canvas text."
    failures = [
        sample
        for sample in samples
        if number(object_mapping(sample)["ratio"]) < AAA_CONTRAST
    ]
    assert not failures, str(failures[:10])
