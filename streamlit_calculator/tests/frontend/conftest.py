# Copyright 2026 anchored-vwam-backtest contributors
"""Launch isolated Streamlit servers and fail on browser runtime failures."""

import importlib
import multiprocessing
import os
import socket
import time
from http import HTTPStatus
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, cast
from urllib.parse import urlsplit

import pytest
import requests
from playwright.sync_api import sync_playwright
from shared.validation import integer
from streamlit.web import bootstrap

from tests.frontend.coverage import DashboardCoverage, cdp_command

if TYPE_CHECKING:
    from collections.abc import Generator

    from playwright.sync_api import (
        Browser,
        ConsoleMessage,
        Page,
        Playwright,
        Response,
        Route,
    )

ROOT = Path(__file__).resolve().parents[2]


def run_server(port: int, theme: str) -> None:
    """Run only the production app's deterministic browser-test entrypoint."""
    # Finish imports before Streamlit starts concurrent script sessions.
    # Python 3.14 dataclasses need their defining module registered.
    _ = importlib.import_module("unittest.mock")
    _ = importlib.import_module("streamlit.runtime.scriptrunner.magic_funcs")
    _ = importlib.import_module("gui_calculator.app")
    options = {
        "server.port": port,
        "server.address": "127.0.0.1",
        "server.headless": True,
        "server.fileWatcherType": "none",
        "browser.gatherUsageStats": False,
        "theme.base": theme,
    }
    with TemporaryDirectory(prefix="calculator-browser-") as directory:
        os.environ["GUI_CALCULATOR_BROWSER_CACHE"] = str(
            Path(directory) / "candles.sqlite"
        )
        bootstrap.load_config_options(options)
        bootstrap.run(
            str(ROOT / "tests/frontend/app_fixture.py"),
            is_hello=False,
            args=[],
            flag_options=options,
        )


def wait_for_server(url: str) -> None:
    """Poll the local health endpoint with a bounded startup timeout.

    Raises:
        AssertionError: If the local server does not become healthy.

    """
    with requests.Session() as session:
        session.trust_env = False
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                response = session.get(url + "/_stcore/health", timeout=1)
            except requests.ConnectionError:
                time.sleep(0.1)
                continue
            if response.ok:
                return
    msg = "Streamlit failed to become healthy within 30 seconds."
    raise AssertionError(msg)


@pytest.fixture(scope="session", params=["light", "dark"])
def calculator_theme(request: pytest.FixtureRequest) -> str:
    """Return the explicitly selected application theme.

    Returns:
        The validated Streamlit theme name.

    """
    theme = cast("object", request.param)
    assert isinstance(theme, str)
    return theme


@pytest.fixture(scope="session")
def calculator_url(calculator_theme: str) -> Generator[str]:
    """Serve the real UI in both application themes without external APIs.

    Yields:
        A healthy local Streamlit server URL.

    """
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = integer(cast("object", listener.getsockname()[1]))
    process = multiprocessing.get_context("spawn").Process(
        target=run_server, args=(port, calculator_theme), daemon=True
    )
    process.start()
    url = f"http://127.0.0.1:{port}"
    try:
        wait_for_server(url)
        yield url
    finally:
        process.terminate()
        process.join(timeout=10)
        if process.is_alive():
            process.kill()
            process.join()


@pytest.fixture
def playwright() -> Generator[Playwright]:
    """Stop Playwright's loop before unrelated asyncio.run-based tests execute.

    Yields:
        A browser driver owned exclusively by the current test.

    """
    with sync_playwright() as driver:
        yield driver


@pytest.fixture
def browser(playwright: Playwright, browser_name: str) -> Generator[Browser]:
    """Keep Chromium and its event loop within the same test lifetime.

    Yields:
        A real Chromium instance with V8 profiler support.

    """
    assert browser_name == "chromium", "Frontend coverage requires Chromium."
    instance = playwright.chromium.launch()
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture
def browser_context_args() -> dict[str, object]:
    """Require strict selectors and prevent service-worker network bypasses.

    Returns:
        Context options that do not create a session-scoped Playwright loop.

    """
    return {"strict_selectors": True, "service_workers": "block"}


@pytest.fixture(scope="session")
def dashboard_coverage() -> Generator[DashboardCoverage]:
    """Aggregate browser coverage and enforce the separate chart threshold.

    Yields:
        A collector shared by every frontend scenario.

    """
    coverage = DashboardCoverage()
    yield coverage
    coverage.assert_threshold()


@pytest.fixture
def browser_page(
    page: Page, dashboard_coverage: DashboardCoverage
) -> Generator[Page]:
    """Require clean runtime/network behavior and record chart execution.

    Yields:
        A desktop browser page with strict timeouts and local-only requests.

    """
    failures: list[str] = []

    def console(message: ConsoleMessage) -> None:
        if message.type == "error":
            failures.append(message.text)

    def check_response(response: Response) -> None:
        if response.status >= HTTPStatus.BAD_REQUEST:
            failures.append(f"HTTP {response.status}: {response.url}")

    def local_only(route: Route) -> None:
        if urlsplit(route.request.url).hostname not in {
            "localhost",
            "127.0.0.1",
            None,
        }:
            failures.append("Unexpected external request: " + route.request.url)
            route.abort()
        else:
            route.continue_()

    page.on("console", console)
    page.on("response", check_response)
    page.on(
        "requestfailed",
        lambda request: failures.append(
            f"Request failed: {request.url}: {request.failure}"
        ),
    )
    page.on("pageerror", lambda error: failures.append(str(error)))
    _ = page.route("**/*", local_only)
    page.set_viewport_size({"width": 1440, "height": 1200})
    page.set_default_timeout(10000)
    session = page.context.new_cdp_session(page)
    _ = cdp_command(session, "Debugger.enable")
    _ = cdp_command(session, "Profiler.enable")
    _ = cdp_command(
        session,
        "Profiler.startPreciseCoverage",
        {"callCount": True, "detailed": True},
    )
    try:
        yield page
    finally:
        dashboard_coverage.collect(session)
        session.detach()
        assert not failures, "\n".join(failures)
