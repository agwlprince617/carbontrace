"""The proposed experiment stays unapproved; provider behavior is stubbed offline."""

import asyncio
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from carbontrace import live_smoke
from carbontrace.exercise import Exercise
from carbontrace.live_smoke import (
    Generation,
    Ledger,
    Plan,
    RunError,
    Usage,
    check_prior_evidence,
    execute,
    load_approved_plan,
)

QUOTE = Path(__file__).parents[1] / "docs/decision-trial-quote.json"


def test_proposed_quote_is_hashed_priced_and_not_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = json.loads(QUOTE.read_text())
    digest = raw.pop("plan_sha256")
    assert (
        digest
        == hashlib.sha256(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert raw["status"] == "awaiting explicit approval; not executable"
    assert len(raw["requests"]) == 6
    assert raw["models"]["strong"]["id"] == "gemini-3.7-flash"
    for output_cap, key in [
        (4096, "requested_limit_estimate_usd"),
        (8192, "stress_allowance_estimate_usd"),
    ]:
        total = sum(
            (
                Decimal(model["calls"])
                * (
                    Decimal(4096) * Decimal(model["input_usd_per_million"])
                    + Decimal(output_cap) * Decimal(model["generated_usd_per_million"])
                )
                / 1_000_000
                for model in raw["models"].values()
            ),
            Decimal(0),
        )
        assert total == Decimal(raw["cost"][key])
    monkeypatch.delitem(live_smoke.APPROVAL_REPLIES, digest, raising=False)
    receipt = tmp_path / "not-human-consent.json"
    receipt.write_text(
        json.dumps(
            {
                "plan_sha256": digest,
                "decision": "approved",
                "human_reply": "synthetic unit test",
            }
        )
    )
    with pytest.raises(RunError, match="differs"):
        load_approved_plan(QUOTE, receipt)


class OfflineProvider:
    """Synthetic responses; never create credentials or a network client."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def model(self, model_id: str) -> str:
        self.calls.append("metadata")
        return model_id

    async def count(self, model_id: str, text: str) -> int:
        self.calls.append("count")
        return 100

    async def generate(self, model_id: str, text: str) -> Generation:
        self.calls.append("generate")
        return Generation(
            "def test_example():\n    assert True\n",
            model_id,
            "STOP",
            Usage(input_tokens=100, candidate_tokens=200, total_tokens=300),
            0.1,
        )


def test_full_protojson_plan_uses_six_slots_without_importing_prior_responses(
    tmp_path: Path,
) -> None:
    plan = Plan.model_validate_json(QUOTE.read_text())
    check_prior_evidence(plan, tmp_path)
    assert Usage(input_tokens=100, candidate_tokens=200, total_tokens=300).checked(
        plan.usage_policy
    ) == (100, 200)
    provider = OfflineProvider()

    def quality(_exercise: Exercise, _code: str) -> dict[str, object]:
        return {"accepted": True, "provenance": "synthetic_unit_test_stub"}

    result = asyncio.run(execute(plan, provider, Ledger(tmp_path, plan), quality))
    assert result["status"] == "completed"
    assert provider.calls.count("generate") == provider.calls.count("count") == 6
    assert provider.calls.count("metadata") == 2
    assert len(result["generations"]) == 6  # type: ignore[arg-type]
    with pytest.raises(RunError, match="prior evidence"):
        check_prior_evidence(
            plan.model_copy(update={"prior_catalog_cost_usd": Decimal("0.01")}),
            tmp_path,
        )
