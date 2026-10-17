"""Local-only FastAPI application; intentionally contains no model client."""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware

from carbontrace import __version__
from carbontrace.benchmark import manifest, prompt
from carbontrace.benchmarks import EXERCISES
from carbontrace.decision import (
    DecisionRequest,
    DecisionResult,
    DecisionTask,
    ModelId,
    build_decision,
    saved_evidence,
)
from carbontrace.domain import CompareRequest, Comparison, TaskId
from carbontrace.engine import build_comparison
from carbontrace.preflight import PreflightRequest, PreflightResult, build_preflight
from carbontrace.quality import Profile, render_suite
from carbontrace.research import (
    ResearchRequest,
    ResearchResult,
    compare_research,
    research_catalog,
)
from carbontrace.store import EvidenceStore
from carbontrace.workflow import TaskWorkflow, workflow_for_task

PACKAGE = Path(__file__).resolve().parent


def create_app(data_dir: Path | None = None) -> FastAPI:
    """Create an offline app with an explicit, configurable local evidence store."""
    store = EvidenceStore(
        (data_dir or Path(os.environ.get("CARBONTRACE_DATA_DIR", "data")))
        / "evidence.sqlite3"
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Initialize disk storage off the event loop."""
        await asyncio.to_thread(store.initialize)
        yield

    app = FastAPI(title="CarbonTrace", version=__version__, lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )
    app.mount("/static", StaticFiles(directory=PACKAGE / "static"), name="static")
    templates = Jinja2Templates(directory=PACKAGE / "templates")

    @app.middleware("http")
    async def browser_headers(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Restrict the local interface to its own assets and disable framing."""
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> Response:
        """Serve the original CarbonTrace interface."""
        return templates.TemplateResponse(
            request=request, name="index.html", context={"version": __version__}
        )

    @app.get("/api/health")
    async def health() -> dict[str, str | int | bool]:
        """Expose the offline execution boundary without inspecting credentials."""
        return {
            "status": "ok",
            "version": __version__,
            "live_enabled": False,
            "live_calls": 0,
            "project": "carbontrace-511814",
        }

    @app.get("/api/tasks")
    async def tasks() -> list[dict[str, str | int]]:
        """List curated exercises rather than accepting arbitrary executable input."""
        return [
            {
                "id": item.id,
                "title": item.title,
                "category": item.category,
                "description": item.description,
                "source": item.source,
                "mutations": len(item.mutations),
            }
            for item in EXERCISES.values()
            if item.split == "development"
        ]

    @app.get("/api/benchmark")
    async def benchmark() -> dict[str, object]:
        """Return frozen catalog metadata; holdout fixtures stay outside the UI."""
        return manifest()

    @app.post("/api/compare", response_model=Comparison)
    async def compare(request: CompareRequest) -> Comparison:
        """Evaluate fixtures and persist evidence, with no network inference."""
        result = await asyncio.to_thread(build_comparison, request)
        await asyncio.to_thread(store.save, result)
        return result

    @app.get("/api/preflight/examples")
    async def preflight_examples() -> list[dict[str, str]]:
        """Offer only development prompts; no holdout source or oracle is exposed."""
        return [
            {"id": item.id, "title": item.title, "prompt": prompt(item)}
            for item in EXERCISES.values()
            if item.split == "development"
        ]

    @app.post("/api/preflight", response_model=PreflightResult)
    async def preflight(request: PreflightRequest) -> PreflightResult:
        """Preview visible-request scenarios locally, without persisting the draft."""
        return build_preflight(request)

    @app.get("/api/history", response_model=list[Comparison])
    async def history() -> list[Comparison]:
        """Read recent local comparisons."""
        return await asyncio.to_thread(store.recent)

    @app.get("/api/decision/tasks")
    async def decision_tasks() -> list[dict[str, str]]:
        """List only owned development tasks with original saved pilot evidence."""
        return [
            {"id": task_id, "title": EXERCISES[task_id].title}
            for task_id in ("clamp", "discount", "merge")
        ]

    @app.post("/api/decision", response_model=DecisionResult)
    async def task_decision(request: DecisionRequest) -> DecisionResult:
        """Read saved suite checks; no code execution, provider client, or persistence."""
        return build_decision(request)

    @app.get("/api/decision/tasks/{task_id}/workflow", response_model=TaskWorkflow)
    async def recorded_workflow(task_id: DecisionTask) -> TaskWorkflow:
        """Show original completed cloud operations without invoking a provider."""
        return workflow_for_task(task_id)

    @app.get("/api/decision/tasks/{task_id}/suite/{model_id}")
    async def saved_suite(task_id: DecisionTask, model_id: ModelId) -> Response:
        """Download exact checked suite bytes as text; never execute supplied code."""
        evidence = next(
            (
                row
                for row in saved_evidence().records
                if row.task_id == task_id and row.model_id == model_id
            ),
            None,
        )
        if evidence is None:
            raise HTTPException(404, "Saved suite unavailable")
        content = (
            PACKAGE / "resources/decision-suites" / f"{task_id}-{model_id}.txt"
        ).read_bytes()
        if hashlib.sha256(content).hexdigest() != evidence.suite_sha256:
            raise HTTPException(503, "Saved suite integrity check failed")
        return Response(
            content,
            media_type="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="{task_id}-{model_id}.txt"'
            },
        )

    @app.get("/api/decision/tasks/{task_id}/suite/{model_id}/preview")
    async def suite_preview(task_id: DecisionTask, model_id: ModelId) -> dict[str, str]:
        """Read the same integrity-checked suite as inert JSON text for inspection."""
        response = await saved_suite(task_id, model_id)
        content = bytes(response.body)
        return {
            "source_code": content.decode("utf-8"),
            "sha256": hashlib.sha256(content).hexdigest(),
            "note": "Saved Gemini output, evaluated in the isolated runner. Viewing does not execute it.",
        }

    @app.get("/api/research/catalog")
    async def published_workloads() -> dict[str, object]:
        """Serve only the locally pinned CLEER session data and attribution."""
        return research_catalog()

    @app.post("/api/research/compare", response_model=ResearchResult)
    async def published_comparison(request: ResearchRequest) -> ResearchResult:
        """Compare standardized sessions, without executing or persisting a prompt."""
        return compare_research(request)

    @app.get("/api/runs/{run_id}", response_model=Comparison)
    async def get_run(run_id: str) -> Comparison:
        """Return one saved comparison."""
        result = await asyncio.to_thread(store.get, run_id)
        if result is None:
            raise HTTPException(404, "Comparison not found")
        return result

    @app.get("/api/runs/{run_id}/export")
    async def export_run(run_id: str) -> Response:
        """Download evidence with provenance and all attempted generations."""
        result = await get_run(run_id)
        return Response(
            result.model_dump_json(indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="carbontrace-{result.id}.json"'
            },
        )

    @app.get("/api/tasks/{task_id}/source")
    async def source(task_id: TaskId) -> Response:
        """Download the self-contained reference implementation."""
        return Response(
            EXERCISES[task_id].source,
            media_type="text/x-python",
            headers={"Content-Disposition": 'attachment; filename="subject.py"'},
        )

    @app.get("/api/tasks/{task_id}/suite/{profile}")
    async def suite(task_id: TaskId, profile: Profile) -> Response:
        """Download runnable pytest code generated from the literal fixtures."""
        return Response(
            render_suite(task_id, profile),
            media_type="text/x-python",
            headers={
                "Content-Disposition": f'attachment; filename="test_{task_id}_{profile}.py"'
            },
        )

    @app.post("/api/live-runs")
    async def live_run() -> None:
        """Fail closed: configuration flags cannot enable a missing live provider."""
        raise HTTPException(
            423,
            "Web live execution is disabled. The separate local CLI requires an exact cost plan, recorded human approval, and a one-shot ledger; UI flags cannot authorize calls.",
        )

    return app
