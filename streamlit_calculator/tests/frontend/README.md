# GUI Calculator browser checks

These are Python Playwright tests against real Chromium, the production
Streamlit UI, and the production embedded HTML/CSS/JavaScript dashboard.
Only exchange feeds and persistence destinations are replaced in the isolated
Streamlit fixture. Tests use deterministic data, a temporary candle database,
and local-only browser requests; no live exchange availability is required.

## Install and run

From the repository root:

```bash
uv sync --locked
uv run playwright install --with-deps chromium
uv run pytest
```

The full run enforces **92% combined Python line/branch coverage** over the
existing production scope. Browser failures are mandatory failures, including a
missing Chromium installation. Formatting, lint, and type checks remain strict:

```bash
uv run black --check .
uv run ruff check .
uv run basedpyright
```

For a focused browser run (Python coverage requires the full test suite):

```bash
uv run pytest tests/frontend --no-cov
```

## What is enforced

- Backtester controls, result metrics, and Plotly rendering in both light and
  dark Streamlit themes.
- GEX collection through real controls, the current and historical margin modes,
  and Reset view inside the actual Streamlit iframe.
- Phone and desktop dashboard layouts; empty, single-point, recorded margin,
  recorded limit-order, and Bitget growth feeds, including data gaps.
- Real pointer input for hover, zoom, drag, double-click reset, and exact canvas
  pixel restoration after Reset view. Keyboard access and visible reset focus.
- No uncaught browser exceptions, console errors, failed HTTP requests,
  HTTP error responses, or unexpected external browser requests.
- All available axe WCAG A, AA, and AAA rule violations fail, without impact
  filters or disabled rules. This includes text foreground/background contrast.
- Canvas text, which axe cannot read, is checked separately against rendered
  background pixels using WCAG relative luminance and the **AAA 7:1** minimum.
- **92% V8 executed-character coverage** for the complete production
  `gui_calculator/oscillator_dashboard/chart.js`. Nested unexecuted blocks are
  excluded, then coverage is combined across browser scenarios. This is a
  separate JavaScript metric, not Python line/branch coverage. Chromium's
  profiler is required, so this suite targets Chromium explicitly.

The JavaScript coverage report is written to
`test-results/frontend-coverage.json`. On browser failures, pytest-playwright
retains a full-page screenshot and trace under `test-results/`. Inspect a trace
with `uv run playwright show-trace <path-to-trace.zip>`.

Automated accessibility checks do not establish complete WCAG conformance.
Canvas graphics, screen-reader usability, and visual meaning still benefit
from manual review. The tests exercise the views above, not every calculator
strategy or external exchange protocol.
