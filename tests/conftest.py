"""Offline-only test fixtures."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from carbontrace.app import create_app
from carbontrace.domain import HardwareScenario, Interval


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject actual socket connections while allowing in-process HTTP tests."""

    def blocked(*_args: Any, **_kwargs: Any) -> None:
        """Prevent an accidental external request."""
        raise AssertionError("Tests must not make network connections")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """Run the app against a fresh, temporary evidence store."""
    with TestClient(create_app(tmp_path)) as test_client:
        yield test_client


@pytest.fixture
def scenario() -> HardwareScenario:
    """Use explicitly synthetic allocated-power assumptions."""
    return HardwareScenario(
        compact_power_w=Interval(low=30, high=60),
        strong_power_w=Interval(low=120, high=180),
        pue=1.2,
        grid_g_per_kwh=400,
    )
