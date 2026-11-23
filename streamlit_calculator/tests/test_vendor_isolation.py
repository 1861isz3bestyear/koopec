# Copyright 2026 Koopec contributors
"""Verify the calculator resolves its local Python dependencies."""

from importlib.util import find_spec
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "package", ["shared", "snapshot_tunnel", "market_storage"]
)
def test_reference_package_is_local(package: str) -> None:
    """Resolve the package supplied by this checkout."""
    spec = find_spec(package)
    assert spec is not None
    assert spec.origin is not None
    vendor = Path(__file__).resolve().parents[1] / "vendor"
    assert Path(spec.origin).resolve().parent == vendor / package
