"""Published sessions remain separate from custom tokens and provider telemetry."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from carbontrace import research
from carbontrace.research import ResearchRequest, compare_research, records


def test_published_mean_scaling_and_operational_carbon(client: TestClient) -> None:
    """Check exact published arithmetic, provenance, and no duplicate PUE."""
    response = client.post("/api/research/compare", json={})
    assert response.status_code == 200
    result = response.json()
    first = result["models"][0]
    assert Decimal(first["evidence"]["energy_wh_mean"]) == Decimal("0.062106712990")
    assert Decimal(first["evidence"]["energy_wh_sd"]) == Decimal("0.047052759722")
    assert Decimal(first["total_energy_wh"]) == Decimal("62.106712990000")
    assert Decimal(first["operational_carbon_g"]) == Decimal("24.842685196")
    assert result["live_model_calls"] == 0
    assert result["source"]["commit"] == research.COMMIT
    assert result["source"]["dataset_engine"] == "CLEER-Text-0826"
    assert "0926" in result["source"]["related_report_version"]
    assert result["source"]["license"] == "CC BY-NC 4.0"
    assert "PUE is not applied again" in result["carbon_basis"]
    assert "confidence interval" in result["uncertainty_note"]
    assert client.get("/api/history").json() == []
    assert client.post("/api/live-runs", json=result).status_code == 423


def test_snapshot_has_all_workloads_and_preserves_missing_sd(
    client: TestClient,
) -> None:
    """Keep all actual model records, including lower-energy competitors."""
    rows = records()
    assert len(rows) == 306
    assert len({row.model_name for row in rows}) == 51
    assert len({(row.model_name, row.workload) for row in rows}) == 306
    assert all(row.energy_wh_mean >= 0 for row in rows)
    assert any(row.energy_wh_sd is None for row in rows)
    catalog = client.get("/api/research/catalog").json()
    assert len(catalog["workloads"]) == 6
    assert catalog["unavailable_models"] == ["Gemini 3.8 Flash"]
    assert "Claude Haiku 4.5" in catalog["models"]
    assert "GPT-4.1 mini" in catalog["models"]


@pytest.mark.parametrize(
    "workload",
    [
        "chat.light",
        "chat.typical",
        "chat.heavy",
        "agentic.light",
        "agentic.typical",
        "agentic.heavy",
    ],
)
def test_every_standardized_workload_is_calculable(
    client: TestClient, workload: str
) -> None:
    """Only workload and volume affect published energy, never pasted prompt text."""
    result = client.post(
        "/api/research/compare", json={"workload": workload, "sessions": 1}
    ).json()
    assert all(row["available"] for row in result["models"])
    for row in result["models"]:
        assert row["evidence"]["workload"] == workload
        assert Decimal(row["total_energy_wh"]) == Decimal(
            row["evidence"]["energy_wh_mean"]
        )


def test_uncovered_model_is_not_substituted_or_zeroed() -> None:
    """The pilot's newer Flash must not inherit the 3.7 Flash estimate."""
    result = compare_research(
        ResearchRequest(model_b="Gemini 3.8 Flash", grid_g_per_kwh=Decimal(0))
    )
    supported, missing = result.models
    assert supported.total_energy_wh is not None and supported.total_energy_wh > 0
    assert supported.operational_carbon_g == 0
    assert not missing.available
    assert missing.evidence is None
    assert missing.total_energy_wh is None
    assert missing.operational_carbon_g is None
    assert "No sibling" in missing.note


@pytest.mark.parametrize(
    "changes",
    [
        {"sessions": 0},
        {"sessions": 1_000_001},
        {"sessions": True},
        {"sessions": 1.5},
        {"grid_g_per_kwh": -1},
        {"grid_g_per_kwh": 2001},
        {"model_a": "unknown"},
        {"model_b": "Gemini 3.5 Flash-Lite"},
        {"workload": "custom.prompt"},
        {"prompt": "must not be converted to energy"},
        {"approved": True},
    ],
)
def test_invalid_or_prompt_based_research_requests_rejected(
    client: TestClient, changes: dict[str, object]
) -> None:
    """Volume bounds and contracts prevent invented request-level conversions."""
    assert client.post("/api/research/compare", json=changes).status_code == 422


def test_altered_snapshot_fails_integrity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Changed benchmark data cannot silently retain the source citation."""
    records.cache_clear()
    monkeypatch.setattr(research, "CSV_SHA256", "unexpected")
    try:
        with pytest.raises(ValueError, match="integrity"):
            records()
    finally:
        records.cache_clear()
