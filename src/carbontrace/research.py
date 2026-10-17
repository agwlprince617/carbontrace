"""Pinned CLEER session benchmarks; never coefficients for arbitrary prompts."""

from __future__ import annotations

import csv
import hashlib
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from carbontrace.domain import Contract

COMMIT = "c0253b43c50f91e538fecdcd0355a99c62359b78"
CSV_SHA256 = "fa698cdb9f43a54288888a915b4784ac354e990a85a5331ac9c861360b1c4ce8"
BASE = f"https://github.com/sustainableaigroup/CLEER/blob/{COMMIT}"
REPORT = "https://reports.sustainableaigroup.com/CLEER-Tech-Report/"
Workload = Literal[
    "chat.light",
    "chat.typical",
    "chat.heavy",
    "agentic.light",
    "agentic.typical",
    "agentic.heavy",
]
MISSING_MODEL = "Gemini 3.8 Flash"


class ResearchSource(Contract):
    """Immutable attribution and separate dataset/report methodology versions."""

    publisher: str = "Sustainable AI Group"
    title: str = "CLEER Dataset"
    dataset_generated_at: str = "2026-09-09"
    dataset_engine: str = "CLEER-Text-0826"
    related_report_version: str = "CLEER-Text-0926 (29 September 2026)"
    commit: str = COMMIT
    source_url: str = BASE + "/data/v1/cleer-dashboard-data.csv"
    schema_url: str = BASE + "/data/v1/schema.md"
    report_url: str = REPORT
    license_url: str = BASE + "/data/LICENSE"
    license: str = "CC BY-NC 4.0"
    adapted_csv_sha256: str = CSV_SHA256
    modifications: str = (
        "CSV line endings normalized to LF. Published energy mean/SD unchanged. "
        "CarbonTrace scales energy means by session count and separately calculates "
        "operational electricity emissions under the user's grid assumption. "
        "Published carbon/cost fields are not used."
    )
    limitations: list[str] = [
        "Standardized sessions only. No published per-token intensities or workload token recipes; not an estimate for the pasted prompt.",
        "Closed-model figures are modelled, not provider energy measurements. Equal workload does not establish equal quality.",
        "Reported SD describes source model variation, not a validated confidence interval. Session-count scaling does not imply independent errors.",
        "Dataset declares engine 0826; linked report is 0926. Versions are preserved separately, not represented as identical.",
        "Upstream metadata lists 52 models; this pinned CSV contains 51. Only actual CSV records are offered.",
        "CarbonTrace reports operational electricity emissions only, excluding embodied hardware, training, construction, networking, and end-user devices.",
        "Dataset carbon columns are excluded: their scope differs and their operational factor does not match the declared metadata scenario.",
        "Data is licensed for non-commercial use with attribution; commercial reuse requires separate written permission from Sustainable AI Group.",
    ]


class SessionEvidence(Contract):
    """One exact published model/workload record with original numeric precision."""

    model_name: str
    workload: str
    description: str
    estimation_basis: str
    energy_wh_mean: Decimal = Field(ge=0)
    energy_wh_sd: Decimal | None = Field(ge=0)


@lru_cache(maxsize=1)
def records() -> tuple[SessionEvidence, ...]:
    """Read an integrity-checked packaged snapshot without any network access."""
    path = Path(__file__).parent / "resources/cleer-workloads.csv"
    if hashlib.sha256(path.read_bytes()).hexdigest() != CSV_SHA256:
        raise ValueError("CLEER snapshot integrity check failed")
    with path.open(newline="", encoding="utf-8") as handle:
        return tuple(
            SessionEvidence(
                model_name=row["model_name"],
                workload=row["use_case"].lower() + "." + row["tier"].lower(),
                description=row["dashboard_description"],
                estimation_basis=row["estimation_basis"],
                energy_wh_mean=Decimal(row["energy_wh_mean"]),
                energy_wh_sd=(
                    Decimal(row["energy_wh_sd"]) if row["energy_wh_sd"] else None
                ),
            )
            for row in csv.DictReader(handle)
        )


def research_catalog() -> dict[str, object]:
    """Offer actual records and the explicitly unsupported current pilot model."""
    data = records()
    return {
        "source": ResearchSource().model_dump(mode="json"),
        "models": sorted({row.model_name for row in data}) + [MISSING_MODEL],
        "unavailable_models": [MISSING_MODEL],
        "workloads": {row.workload: row.description for row in data},
    }


class ResearchRequest(Contract):
    """Compare two exact names under one standardized session definition."""

    model_a: str = Field(default="Gemini 3.5 Flash-Lite", min_length=1, max_length=120)
    model_b: str = Field(default="Gemini 3.7 Flash", min_length=1, max_length=120)
    workload: Workload = "chat.light"
    sessions: int = Field(default=1000, ge=1, le=1_000_000, strict=True)
    grid_g_per_kwh: Decimal = Field(default=Decimal(400), ge=0, le=2000)

    @model_validator(mode="after")
    def valid_models(self) -> ResearchRequest:
        """Reject unregistered names and comparisons against the same model."""
        allowed = {row.model_name for row in records()} | {MISSING_MODEL}
        if self.model_a == self.model_b:
            raise ValueError("Choose two different models")
        if self.model_a not in allowed or self.model_b not in allowed:
            raise ValueError("Choose a model listed in the pinned snapshot")
        return self


class ResearchModelResult(Contract):
    """Missing model coverage remains null; it is never mapped to a sibling."""

    model_name: str
    available: bool
    evidence: SessionEvidence | None = None
    total_energy_wh: Decimal | None = None
    operational_carbon_g: Decimal | None = None
    note: str


class ResearchResult(Contract):
    """Exportable session arithmetic with no prompt-based or live claim."""

    mode: Literal["published_workload_scenario"] = "published_workload_scenario"
    live_model_calls: Literal[0] = 0
    source: ResearchSource
    request: ResearchRequest
    models: list[ResearchModelResult]
    uncertainty_note: str = (
        "Per-session SD is preserved from the source. No aggregate confidence interval "
        "is calculated; model uncertainty need not average away across sessions."
    )
    carbon_basis: str = (
        "Published facility Wh × sessions ÷ 1000 × user-assumed gCO2e/kWh. "
        "Facility energy already includes overheads: PUE is not applied again. "
        "This is operational electricity only, not CLEER's published lifecycle carbon. "
        "A zero electricity factor does not establish a zero total footprint."
    )


def compare_research(request: ResearchRequest) -> ResearchResult:
    """Scale published session means; no token normalization or savings ranking."""
    models: list[ResearchModelResult] = []
    for name in (request.model_a, request.model_b):
        evidence = next(
            (
                r
                for r in records()
                if r.model_name == name and r.workload == request.workload
            ),
            None,
        )
        total = evidence.energy_wh_mean * request.sessions if evidence else None
        models.append(
            ResearchModelResult(
                model_name=name,
                available=evidence is not None,
                evidence=evidence,
                total_energy_wh=total,
                operational_carbon_g=(
                    total / 1000 * request.grid_g_per_kwh if total is not None else None
                ),
                note=(
                    "Published workload estimate; quality for your task is not established."
                    if evidence
                    else "No record in this snapshot. No sibling model or zero value substituted."
                ),
            )
        )
    return ResearchResult(source=ResearchSource(), request=request, models=models)
