# Copyright 2026 anchored-vwam-backtest contributors
"""UI operations used by the indicator views."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    import pandas as pd
    import plotly.graph_objects as go


class Progress(Protocol):
    """Represent progress."""

    def progress(self, value: float, *, text: str) -> Progress:
        """Handle progress."""
        ...

    def empty(self) -> object:
        """Handle empty."""
        ...


class IndicatorUI(Protocol):
    """Represent indicatorui."""

    def subheader(self, body: str) -> object:
        """Handle subheader."""
        ...

    def caption(self, body: str) -> object:
        """Handle caption."""
        ...

    def info(self, body: str) -> object:
        """Handle info."""
        ...

    def warning(self, body: str) -> object:
        """Handle warning."""
        ...

    def error(self, body: str) -> object:
        """Handle error."""
        ...

    def progress(self, value: float, *, text: str) -> Progress:
        """Handle progress."""
        ...

    def spinner(self, text: str) -> AbstractContextManager[None]:
        """Handle spinner."""
        ...

    def plotly_chart(
        self, figure_or_data: go.Figure, *, use_container_width: bool
    ) -> object:
        """Handle plotly chart."""
        ...

    def dataframe(
        self, data: pd.DataFrame, *, use_container_width: bool, hide_index: bool
    ) -> object:
        """Handle dataframe."""
        ...

    def download_button(
        self, label: str, data: str, *, file_name: str, mime: str
    ) -> object:
        """Handle download button."""
        ...
