# Copyright 2026 anchored-vwam-backtest contributors
"""Typed accessors for dynamically recorded test and mock values."""

from __future__ import annotations

from inspect import unwrap
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pandas as pd
import plotly.graph_objects as go
from shared.testing_support import ignoring_arguments as ignoring_arguments
from shared.validation import object_list, object_mapping

if TYPE_CHECKING:
    from collections.abc import Callable


def mock_child(parent: Mock, name: str) -> Mock:
    """Return mock child.

    Returns:
        The computed result.

    """
    value = cast("object", getattr(parent, name))
    assert isinstance(value, Mock)
    return value


def mock_result(parent: Mock) -> Mock:
    """Return mock result.

    Returns:
        The computed result.

    """
    value = cast("object", parent.return_value)
    assert isinstance(value, Mock)
    return value


def set_return(parent: Mock, value: object) -> None:
    """Return set return."""
    parent.return_value = value


def set_side_effect(parent: Mock, value: object) -> None:
    """Return set side effect."""
    parent.side_effect = value


def call_args_at(parent: Mock, index: int) -> tuple[object, ...]:
    """Return call args at.

    Returns:
        The computed result.

    """
    return cast("tuple[object, ...]", parent.call_args_list[index].args)


def call_kwargs_at(parent: Mock, index: int) -> dict[str, object]:
    """Return call kwargs at.

    Returns:
        The computed result.

    """
    return object_mapping(cast("object", parent.call_args_list[index].kwargs))


def call_args(parent: Mock) -> tuple[object, ...]:
    """Return call args.

    Returns:
        The computed result.

    """
    call = parent.call_args
    assert call is not None
    return cast("tuple[object, ...]", call.args)


def call_kwargs(parent: Mock) -> dict[str, object]:
    """Return call kwargs.

    Returns:
        The computed result.

    """
    call = parent.call_args
    assert call is not None
    return object_mapping(cast("object", call.kwargs))


def frame(value: object) -> pd.DataFrame:
    """Return frame.

    Returns:
        The computed result.

    """
    assert isinstance(value, pd.DataFrame)
    return value


def figure(value: object) -> go.Figure:
    """Return figure.

    Returns:
        The computed result.

    """
    assert isinstance(value, go.Figure)
    return value


def trace_name(value: object) -> str:
    """Return trace name.

    Returns:
        The computed result.

    """
    assert isinstance(value, (go.Scatter, go.Bar, go.Candlestick))
    name = value.name
    assert isinstance(name, str)
    return name


def mock_results(parent: Mock) -> list[Mock]:
    """Return mock results.

    Returns:
        The computed result.

    """
    results = object_list(cast("object", parent.return_value))
    assert all(isinstance(item, Mock) for item in results)
    return [item for item in results if isinstance(item, Mock)]


def clicked(label: str) -> Callable[..., bool]:
    """Return clicked.

    Returns:
        The computed result.

    """

    def press(value: str, **_kwargs: object) -> bool:
        return value == label

    return press


# Streamlit preserves a cached function's signature via __wrapped__, but its
# CachedFunc annotations omit that standard functools attribute.


def uncached[**P, T](function: Callable[P, T]) -> Callable[P, T]:
    """Return uncached.

    Returns:
        The computed result.

    """
    return cast("Callable[P, T]", unwrap(function))


def scatter(value: object) -> go.Scatter:
    """Return scatter.

    Returns:
        The computed result.

    """
    assert isinstance(value, go.Scatter)
    return value


def attribute(value: object, name: str) -> object:
    """Read a runtime-checked value from a third-party object with dynamic.

    stubs.

    Returns:
        The computed result.

    """
    return cast("object", getattr(value, name))
