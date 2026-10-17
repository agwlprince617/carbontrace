"""Read-only replay of a completed Gemini experiment; no provider dependency."""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field

from carbontrace.benchmark import prompt
from carbontrace.benchmarks import EXERCISES
from carbontrace.decision import DecisionTask, ModelId, saved_evidence
from carbontrace.domain import Contract

TRACE_SHA256 = "fbe75446ee6fdd6caf3fed15d0c56883626fe67aab7f8f3db259887194141347"


class RunSummary(Contract):
    """Recorded configuration and full-experiment totals, not a new call budget."""

    plan_sha256: str
    source_report_sha256: str
    source_ledger_sha256: str
    project: str
    region: str
    api_version: str
    recorded_at: datetime
    thinking_level: str
    maximum_generated_tokens: int = Field(ge=1)
    candidate_count: int = Field(ge=1)
    automatic_continuation: bool
    automatic_retries: int = Field(ge=0)
    metadata_reads: int = Field(ge=0)
    token_count_calls: int = Field(ge=0)
    generation_calls: int = Field(ge=0)
    full_run_catalog_cost_usd: Decimal = Field(ge=0)


class RequestTrace(Contract):
    """Completed cloud operations for one exact task/model pair."""

    task_id: DecisionTask
    model_id: ModelId
    prompt_sha256: str
    metadata_name: str
    metadata_status: Literal["completed"]
    token_count_status: Literal["completed"]
    counted_input_tokens: int = Field(ge=1)
    generation_status: Literal["completed"]
    response_model_version: str
    finish_reason: str


class RunLog(RunSummary):
    requests: list[RequestTrace]


@lru_cache(maxsize=1)
def saved_run() -> RunLog:
    """Check the replay against the independently packaged suite evidence."""
    content = (Path(__file__).parent / "resources/decision-workflow.json").read_bytes()
    if hashlib.sha256(content).hexdigest() != TRACE_SHA256:
        raise ValueError("Workflow snapshot integrity check failed")
    run = RunLog.model_validate_json(content)
    evidence = saved_evidence()
    if run.source_report_sha256 != evidence.source_report_sha256:
        raise ValueError("Workflow and decision evidence refer to different reports")
    if (
        run.generation_calls != len(run.requests)
        or run.token_count_calls != len(run.requests)
        or run.metadata_reads != len({row.model_id for row in run.requests})
    ):
        raise ValueError("Workflow operation totals differ from recorded requests")
    expected = {(row.task_id, row.model_id): row for row in evidence.records}
    if len(run.requests) != len(expected) or {
        (r.task_id, r.model_id) for r in run.requests
    } != set(expected):
        raise ValueError("Workflow task/model pairs differ from the saved evidence")
    for row in run.requests:
        record = expected[row.task_id, row.model_id]
        if (
            row.prompt_sha256 != record.prompt_sha256
            or row.response_model_version != record.model_version
            or not row.metadata_name.endswith(row.model_id)
        ):
            raise ValueError("Workflow prompt or model identity differs")
    return run


class TaskWorkflow(Contract):
    """The original prompt and recorded steps; never fake live progress."""

    mode: Literal["saved_run_replay"] = "saved_run_replay"
    new_model_calls: Literal[0] = 0
    task_id: DecisionTask
    exact_prompt: str
    run: RunSummary
    requests: list[RequestTrace]
    note: str = (
        "Recorded Gemini calls were executed by the approved local CLI. Reading this "
        "replay does not call Google, execute Python or grant execution approval. "
        "The run is completed and its one-shot allowance is consumed."
    )


def workflow_for_task(task_id: DecisionTask) -> TaskWorkflow:
    run = saved_run()
    return TaskWorkflow(
        task_id=task_id,
        exact_prompt=prompt(EXERCISES[task_id]),
        run=RunSummary.model_validate(run.model_dump(exclude={"requests"})),
        requests=[row for row in run.requests if row.task_id == task_id],
    )
