"""Public preview never relies on local files or offers execution authority."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from carbontrace.app import create_app
from carbontrace.server import main


def test_hosted_preview_is_stateless(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CARBONTRACE_MODE", "hosted-preview")
    directory = tmp_path / "must-not-be-created"
    with TestClient(
        create_app(directory), base_url="https://carbontrace-demo.run.app"
    ) as client:
        assert client.get("/").status_code == 200
        assert 'data-deployment-mode="hosted-preview"' in client.get("/").text
        assert client.get("/api/health").json()["deployment_mode"] == "hosted-preview"
        assert client.get("/api/demo-comparison").json()["read_only"] is True
        assert client.get("/api/demo-comparison/export").status_code == 200
        assert (
            client.get("/api/health", headers={"host": "attacker.example"}).status_code
            == 400
        )
        preview = client.post(
            "/api/preflight", json={"prompt": "Write tests for double(x)."}
        )
        assert preview.status_code == 200
        assert preview.headers["cache-control"] == "no-store"
        assert (
            client.post(
                "/api/research/compare",
                json={
                    "model_a": "Gemini 3.5 Flash-Lite",
                    "model_b": "Gemini 3.7 Flash",
                    "workload": "chat.light",
                    "sessions": 1,
                    "grid_g_per_kwh": 400,
                },
            ).status_code
            == 200
        )
        for route in (
            "/api/compare",
            "/api/selected-runs/prepare",
            "/api/live-comparisons/prepare",
            "/api/live-runs",
        ):
            assert client.post(route, json={"approved": True}).status_code == 423
        for route in (
            "/api/history",
            "/api/runs/private/export",
            "/api/live-comparisons/private/export",
        ):
            assert client.get(route).status_code == 423
        assert client.get("/api/health").json()["live_calls"] == 0
    assert not directory.exists()


def test_cloud_run_defaults_to_preview_and_cannot_enable_local_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CARBONTRACE_MODE", raising=False)
    monkeypatch.setenv("K_SERVICE", "carbontrace-demo")
    with TestClient(create_app()) as client:
        assert client.get("/api/health").json()["deployment_mode"] == "hosted-preview"
    monkeypatch.setenv("CARBONTRACE_MODE", "local")
    with pytest.raises(ValueError, match="requires hosted-preview"):
        create_app()


def test_invalid_deployment_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARBONTRACE_MODE", "public-live")
    with pytest.raises(
        ValueError, match="must be local, hosted-preview or hosted-live"
    ):
        create_app()


@pytest.mark.parametrize("port", [None, "9000"])
def test_server_uses_cloud_run_port(
    port: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PORT", raising=False)
    if port:
        monkeypatch.setenv("PORT", port)
    with patch("carbontrace.server.uvicorn.run") as run:
        main()
    run.assert_called_once_with(
        "carbontrace.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=int(port or "8080"),
        access_log=False,
    )


@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_server_rejects_invalid_port(
    port: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PORT", port)
    with patch("carbontrace.server.uvicorn.run") as run, pytest.raises(ValueError):
        main()
    run.assert_not_called()
