"""Offline benchmark manifest, prompt planning, and explicit container evaluation."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from pathlib import Path

from carbontrace.benchmarks import EXERCISES
from carbontrace.exercise import Exercise
from carbontrace.sandbox import MAX_CODE_BYTES, ContainerRunner, SandboxError

SMOKE_TASKS = ("clamp", "discount", "merge")


def fingerprint(exercise: Exercise) -> str:
    """Freeze source, requirement, split, oracle data, and all seeded defects."""
    payload = {
        "id": exercise.id,
        "split": exercise.split,
        "source": exercise.source,
        "requirements": exercise.description,
        "cases": [
            (
                case.title,
                case.args,
                case.expected,
                case.raises.__name__ if case.raises else None,
            )
            for case in exercise.strong_cases
        ],
        "mutants": [
            (item.name, item.description, inspect.getsource(item.target))
            for item in exercise.mutations
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def manifest() -> dict[str, object]:
    """Expose reproducibility metadata without publishing held-out oracle answers."""
    items = [
        {
            "id": item.id,
            "category": item.category,
            "split": item.split,
            "sha256": fingerprint(item),
            "oracle_cases": len(item.strong_cases),
            "mutations": len(item.mutations),
        }
        for item in EXERCISES.values()
    ]
    digest = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
    return {
        "schema_version": 1,
        "benchmark_id": "python-unit-tests-v1",
        "sha256": digest,
        "review_status": "machine-validated; pending human review",
        "total_functions": len(items),
        "development_functions": sum(
            item.split == "development" for item in EXERCISES.values()
        ),
        "holdout_functions": sum(
            item.split == "holdout" for item in EXERCISES.values()
        ),
        "items": items,
        "live_model_calls": 0,
    }


def prompt(exercise: Exercise) -> str:
    """Use identical source-only prompts for both models; exclude oracle and bugs."""
    return (
        "Write a pytest test suite for the Python function below. Return only Python code, "
        "without Markdown fences. Import the function from subject. Use only pytest, math, "
        "and subject imports. Include normal cases, boundaries, and required invalid-input "
        "exceptions. Do not read files, inspect implementation internals, use private attributes, "
        "perform I/O, or skip tests. Requirements apply to the annotated input types.\n\n"
        f"Requirements: {exercise.description}\n\n{exercise.source}"
    )


def run_plan(full: bool = False) -> dict[str, object]:
    """Prepare bounded requests; this plan cannot execute or authorize model calls."""
    tasks = tuple(EXERCISES) if full else SMOKE_TASKS
    repeats = 2 if full else 1
    requests = [
        {
            "task_id": task,
            "split": EXERCISES[task].split,
            "model_role": role,
            "repeat": repeat,
            "prompt_sha256": hashlib.sha256(
                prompt(EXERCISES[task]).encode()
            ).hexdigest(),
        }
        for repeat in range(repeats)
        for task in tasks
        for role in ("compact", "strong")
    ]
    return {
        "status": "draft; not approved or executable",
        "stage": "full" if full else "smoke",
        "benchmark_sha256": manifest()["sha256"],
        "generation_calls": len(requests),
        "models": {"compact": None, "strong": None},
        "max_input_tokens_per_request": 4096,
        "max_generated_tokens_including_thinking": 4096,
        "automatic_retries": 0,
        "paid_grading_calls": 0,
        "cost_estimate": None,
        "cost_status": "Pending exact available model IDs, current official pricing, and token-budget enforcement. Show estimate and obtain explicit approval before any live call.",
        "quality_gate": "Reference passes, no skipped/error/empty tests, all four seeded faults detected; infrastructure failures remain inconclusive.",
        "evaluation": "Use the same prompt and settings for both models; evaluate separately, then replay compact-first escalation including every failed generation. Freeze settings on development items before holdout runs.",
        "reuse": "Reuse smoke results only when model version, configuration, prompt hash, benchmark hash, and usage record match the final protocol.",
        "interpretation": "Exploratory benchmark only. Two repeats are insufficient to establish statistical significance or real carbon savings.",
        "requests": requests,
        "live_model_calls": 0,
    }


def main(argv: list[str] | None = None) -> None:
    """Write offline plans, or evaluate a local suite only in a prepared container."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("manifest", "plan", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("--output", type=Path, required=True)
        if name == "plan":
            command.add_argument("--full", action="store_true")
        elif name == "evaluate":
            command.add_argument("--task", choices=tuple(EXERCISES), required=True)
            command.add_argument("--suite", type=Path, required=True)
            command.add_argument("--image", required=True)
            command.add_argument("--include-holdout", action="store_true")
    args = parser.parse_args(argv)
    result: dict[str, object]
    if args.command == "manifest":
        result = manifest()
    elif args.command == "plan":
        result = run_plan(args.full)
    else:
        exercise = EXERCISES[args.task]
        if exercise.split == "holdout" and not args.include_holdout:
            parser.error(
                "Holdout is reserved for final evaluation; use --include-holdout explicitly"
            )
        try:
            with args.suite.open("rb") as handle:
                raw = handle.read(MAX_CODE_BYTES + 1)
            if len(raw) > MAX_CODE_BYTES:
                raise SandboxError("Suite exceeds 32 KiB")
            runner = ContainerRunner(args.image, Path(".tmp/sandbox"))
            result = runner.evaluate(exercise, raw.decode("utf-8"))
        except (OSError, UnicodeError, SandboxError) as error:
            parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Saved {args.command} to {args.output}. Live model calls: 0.")


if __name__ == "__main__":  # pragma: no cover
    main()
