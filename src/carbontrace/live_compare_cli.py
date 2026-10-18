"""Interactive, one-shot execution of an exact browser-prepared Gemini quote.

The web server never imports this module. The terminal owner reviews the full
payload and price, then types the exact plan hash before any credentials or RPC.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from google import genai
from google.oauth2.credentials import Credentials

from carbontrace.benchmarks import EXERCISES
from carbontrace.decision import MODELS, GateExecution
from carbontrace.exercise import Exercise
from carbontrace.live_comparison import (
    ALLOWANCE,
    RATES,
    LiveComparisonStore,
    quote_task,
)
from carbontrace.live_smoke import (
    GeminiProvider,
    Provider,
    RunError,
    client_http_options,
)
from carbontrace.sandbox import ContainerRunner, SandboxError, validate_suite

IMAGE = "sha256:af50fdb931d09782d5a8aee70ccbaa5856e8661c4af09c64279fc59213cab021"
Evaluator = Callable[[Exercise, str], dict[str, object]]


def checked_quality(
    exercise: Exercise, code: str, report: dict[str, Any]
) -> dict[str, Any]:
    """Check provenance and strict quality gates, not the evaluator's accepted flag."""
    if (
        report.get("task_id") != exercise.id
        or report.get("image_id") != IMAGE
        or report.get("suite_sha256") != hashlib.sha256(code.encode()).hexdigest()
    ):
        raise RunError("Quality report provenance mismatch")
    fields = ("status", "tests", "failures", "errors", "skipped")
    reference = GateExecution.model_validate(
        {k: report["reference"][k] for k in fields}
    )
    mutations = report.get("mutations", {})
    expected = {m.name for m in exercise.mutations}
    gates = {
        name: GateExecution.model_validate({k: row[k] for k in fields})
        for name, row in mutations.items()
    }
    accepted = (
        reference.clean_pass
        and set(gates) == expected
        and all(g.detected and g.tests == reference.tests for g in gates.values())
    )
    return {
        **report,
        "status": "evaluated",
        "accepted": accepted,
        "detected": sum(g.detected for g in gates.values()),
        "total_mutations": len(expected),
    }


async def execute(
    store: LiveComparisonStore,
    run_id: str,
    state: dict[str, Any],
    provider: Provider,
    evaluate: Evaluator | None,
) -> dict[str, Any]:
    """Exactly two metadata/count/generation slots; no retry or host execution."""
    quote = store.load(run_id)
    if state.get("status") != "reserved" or store.view(run_id)["result"] != state:
        raise RunError("A matching one-shot reservation is required")
    rows = cast(list[dict[str, str]], quote["models"])
    text = str(quote["exact_payload"])
    task = quote_task(quote)
    operations: list[dict[str, Any]] = state["operations"]
    responses: list[dict[str, Any]] = state["responses"]

    def dispatch(kind: str, model: str) -> dict[str, Any]:
        if sum(op["kind"] == kind for op in operations) >= len(rows):
            raise RunError("Operation allowance exhausted")
        operation = {"kind": kind, "model_id": model, "status": "dispatched"}
        operations.append(operation)
        if kind == "generate":
            state["billing_uncertain"] = True
        store.save(run_id, state)
        return operation

    try:
        state["status"] = "running"
        store.save(run_id, state)
        # Validate both models and both exact input counts before any generation.
        for row in rows:
            model = row["model_id"]
            operation = dispatch("metadata", model)
            name = await provider.model(model)
            if not name or name.split("/")[-1] != model:
                raise RunError("Model metadata identity differs from approved model")
            operation.update(status="completed", name=name)
            store.save(run_id, state)
            operation = dispatch("count", model)
            count = await provider.count(model, text)
            if count is None or not 1 <= count <= 4096:
                raise RunError(
                    "Input count missing or above 4096 tokens; no generation"
                )
            operation.update(status="completed", input_tokens=count)
            store.save(run_id, state)
        total = Decimal(0)
        for row in rows:
            model = row["model_id"]
            rates = RATES[MODELS.index(cast(Any, model))]
            reserve = (4096 * rates[0] + 8192 * rates[1]) / 1_000_000
            if total + reserve > ALLOWANCE:
                raise RunError(
                    "Insufficient estimated allowance for another generation"
                )
            operation = dispatch("generate", model)
            generated = await provider.generate(model, text)
            response: dict[str, Any] = {
                "model_id": model,
                "model_name": row["model_name"],
                "model_version": generated.model_version,
                "finish_reason": generated.finish_reason,
                "source_text": generated.text,
                "elapsed_seconds": generated.elapsed_seconds,
                "usage": generated.usage.model_dump(),
                "catalog_cost_usd": None,
                "suite_sha256": hashlib.sha256(generated.text.encode()).hexdigest(),
                "quality": {
                    "status": "pending" if task else "not_evaluated",
                    "accepted": None,
                },
            }
            responses.append(response)
            operation["status"] = "response_received"
            store.save(run_id, state)
            inputs, outputs = generated.usage.checked("protojson_full_v3")
            effective = generated.usage.effective("protojson_full_v3")
            if effective.cached_tokens != 0:
                raise RunError("Unexpected cached tokens; billing needs review")
            if not generated.model_version or not (
                generated.model_version == model
                or generated.model_version.startswith(model + "-")
            ):
                raise RunError("Response model version missing or mismatched")
            cost = (inputs * rates[0] + outputs * rates[1]) / 1_000_000
            total += cost
            response.update(
                catalog_cost_usd=str(cost),
                effective_usage=effective.model_dump(),
                usage_policy="protojson_full_v3",
                raw_usage_preserved=True,
            )
            state.update(known_catalog_cost_usd=str(total), billing_uncertain=False)
            store.save(run_id, state)
            if total > ALLOWANCE:
                raise RunError("Observed allowance exceeded")
            if generated.finish_reason != "STOP" or not generated.text.strip():
                response["quality"] = {"status": "incomplete", "accepted": False}
            elif task:
                if evaluate is None:
                    raise RunError("Reviewed task requires the isolated runner")
                try:
                    validate_suite(generated.text)
                except SandboxError as error:
                    response["quality"] = {
                        "status": "rejected",
                        "accepted": False,
                        "reason": str(error),
                    }
                else:
                    quality = await asyncio.to_thread(
                        evaluate, EXERCISES[task], generated.text
                    )
                    response["quality"] = checked_quality(
                        EXERCISES[task], generated.text, quality
                    )
            operation["status"] = "completed"
            store.save(run_id, state)
        passed = [r for r in responses if r["quality"].get("accepted") is True]
        # Both passing: choose the lower published reference, never infer carbon
        # from observed tokens. Custom requests cannot acquire a quality ranking.
        if passed and len(rows) == 2:
            research = cast(dict[str, Any], quote["research"])
            energy = {
                r["model_name"]: Decimal(r["total_energy_wh"])
                for r in research["models"]
            }
            candidate = min(passed, key=lambda r: energy[r["model_name"]])
            state["recommended_model"] = candidate["model_id"]
        state["status"] = "completed"
    except (asyncio.CancelledError, KeyboardInterrupt):
        state.update(
            status="stopped",
            stop_reason="Interrupted; dispatched work may be billed; no retry",
        )
        raise
    except Exception as error:
        state.update(
            status="stopped",
            stop_reason=(
                str(error)
                if isinstance(error, (RunError, SandboxError))
                else f"{type(error).__name__}; stopped without retry"
            ),
        )
    finally:
        if state["status"] == "stopped":
            for response in responses:
                if response["quality"]["status"] == "pending":
                    response["quality"] = {
                        "status": "inconclusive",
                        "accepted": False,
                        "reason": "Runner stopped before the quality gate completed",
                    }
        store.save(run_id, state)
    return state


async def run(store: LiveComparisonStore, run_id: str, approval: str) -> dict[str, Any]:
    """Consent and reservation precede sandbox/auth/provider setup."""
    state = store.reserve(run_id, approval)
    try:
        quote = store.load(run_id)
        task = quote_task(quote)
        runner = ContainerRunner(IMAGE, Path(".tmp/sandbox")) if task else None
        if runner:
            await asyncio.to_thread(runner.preflight)
        load = cast(Callable[[str], Credentials], Credentials.from_authorized_user_file)
        credentials = load(
            str(Path.home() / ".config/gcloud/application_default_credentials.json")
        )
        if credentials.quota_project_id != "carbontrace-511814":
            raise RunError("ADC quota project must be carbontrace-511814")
        async with genai.Client(
            enterprise=True,
            project="carbontrace-511814",
            location="global",
            credentials=credentials,
            http_options=client_http_options(),
        ).aio as client:
            return await execute(
                store,
                run_id,
                state,
                GeminiProvider(client),
                runner.evaluate if runner else None,
            )
    except (asyncio.CancelledError, KeyboardInterrupt):
        state.update(status="stopped", stop_reason="Interrupted; no automatic replay")
        store.save(run_id, state)
        raise
    except Exception as error:
        state.update(
            status="stopped",
            stop_reason=(
                str(error)
                if isinstance(error, (RunError, SandboxError))
                else f"{type(error).__name__}; setup failed without retry"
            ),
        )
        store.save(run_id, state)
        return state


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("data/live-comparisons"))
    parser.add_argument("--id", required=True)
    args = parser.parse_args(argv)
    try:
        store = LiveComparisonStore(args.directory)
        quote = store.load(args.id)
        print(json.dumps(quote, indent=2))
        print(
            f"{quote['generation_calls']} generation(s), {quote['token_count_calls']} token count(s), {quote['metadata_reads']} metadata read(s). Zero retries. No deployment."
        )
        print(
            "Review the exact payload and price above. This sends source text to Google Cloud."
        )
        if not sys.stdin.isatty():
            raise RunError(
                "Approval must be typed interactively in your terminal; no piped approvals"
            )
        approval = input(
            f"Type APPROVE {quote['plan_sha256']} to run once, or anything else to cancel:\n"
        )
        result = asyncio.run(run(store, args.id, approval))
    except (OSError, ValueError, RunError) as error:
        parser.error(str(error))
    print(f"Comparison {result['status']}. Refresh the browser for recorded results.")
    if result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
