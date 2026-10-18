"""Offline planner with an explicitly bounded, separately approved hosted runner."""

from __future__ import annotations

import asyncio
import hashlib
import json
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

from carbontrace import __version__, hosted_cloud
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
from carbontrace.hosted import (
    HostedApproval,
    HostedDraft,
    HostedError,
    PoolExhausted,
    check_approval,
    execute_hosted,
    issue_quote,
)
from carbontrace.live_comparison import LiveComparisonStore, LiveDraft
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
    mode = os.environ.get(
        "CARBONTRACE_MODE", "hosted-preview" if os.environ.get("K_SERVICE") else "local"
    )
    if mode not in {"local", "hosted-preview", "hosted-live"}:
        raise ValueError(
            "CARBONTRACE_MODE must be local, hosted-preview or hosted-live"
        )
    hosted_preview = mode != "local"
    hosted_live = mode == "hosted-live"
    if os.environ.get("K_SERVICE") and not hosted_preview:
        raise ValueError("Cloud Run requires hosted-preview or hosted-live mode")
    hosts = ["localhost", "127.0.0.1", "testserver"]
    if hosted_preview:
        hosts += ["*.run.app"]
    store = EvidenceStore(
        (data_dir or Path(os.environ.get("CARBONTRACE_DATA_DIR", "data")))
        / "evidence.sqlite3"
    )
    live_store = LiveComparisonStore(
        (data_dir or Path(os.environ.get("CARBONTRACE_DATA_DIR", "data")))
        / "live-comparisons"
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Initialize disk storage off the event loop."""
        if not hosted_preview:
            await asyncio.to_thread(store.initialize)
        yield

    app = FastAPI(title="CarbonTrace", version=__version__, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    app.mount("/static", StaticFiles(directory=PACKAGE / "static"), name="static")
    templates = Jinja2Templates(directory=PACKAGE / "templates")

    @app.middleware("http")
    async def browser_headers(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Restrict the local interface to its own assets and disable framing."""
        local_records = (
            request.url.path == "/api/history"
            or request.url.path.startswith(("/api/runs/", "/api/live-comparisons/"))
        )
        writes = request.method not in {"GET", "HEAD"} and request.url.path not in {
            "/api/preflight",
            "/api/research/compare",
            *({"/api/hosted/quote", "/api/hosted/execute"} if hosted_live else set()),
        }
        if hosted_preview and (local_records or writes):
            response = Response(
                json.dumps(
                    {"detail": "This endpoint is unavailable in the hosted demo."}
                ),
                status_code=423,
                media_type="application/json",
            )
        else:
            response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> Response:
        """Serve the original CarbonTrace interface."""
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "version": __version__,
                "hosted_preview": hosted_preview,
                "hosted_live": hosted_live,
                "deployment_mode": mode,
            },
        )

    @app.get("/api/health")
    async def health() -> dict[str, str | int | bool | None]:
        """Expose the offline execution boundary without inspecting credentials."""
        return {
            "status": "ok",
            "version": __version__,
            "live_enabled": hosted_live,
            "live_calls": None if hosted_live else 0,
            "project": "carbontrace-511814",
            "deployment_mode": mode,
        }

    def require_hosted(request: Request, write: bool = False) -> None:
        if not hosted_live:
            raise HTTPException(423, "Hosted execution is disabled")
        if write:
            from urllib.parse import urlsplit

            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                raise HTTPException(403, "Use this site's approved run form")

    @app.exception_handler(HostedError)
    async def hosted_error(_request: Request, exc: HostedError) -> Response:
        return Response(
            json.dumps({"detail": str(exc)}),
            status_code=429 if isinstance(exc, PoolExhausted) else 503,
            media_type="application/json",
        )

    @app.get("/api/hosted/status")
    async def hosted_status(request: Request) -> dict[str, object]:
        require_hosted(request)
        config = hosted_cloud.settings()
        budget = await asyncio.to_thread(hosted_cloud.cloud_ledger().status)
        return {
            **budget,
            "expires_at": config.expires_at.isoformat(),
            "scope": "Sponsor-funded model budget shared across visitors. Stress reservations are retained, including failures; not an invoice or Google billing cap.",
        }

    @app.post("/api/hosted/quote")
    async def hosted_quote(request: Request, draft: HostedDraft) -> object:
        require_hosted(request, True)
        try:
            return issue_quote(
                PreflightRequest.model_validate(
                    draft.model_dump(exclude={"compare_models"})
                ),
                hosted_cloud.settings(),
                compare_models=draft.compare_models,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/api/hosted/execute")
    async def hosted_execute(request: Request, approval: HostedApproval) -> object:
        require_hosted(request, True)
        quote = check_approval(approval, hosted_cloud.settings())
        return await execute_hosted(
            quote, hosted_cloud.cloud_ledger(), hosted_cloud.cloud_provider
        )

    @app.get("/api/hosted/runs/{run_id}")
    async def hosted_receipt(request: Request, run_id: str) -> object:
        require_hosted(request)
        result = await asyncio.to_thread(hosted_cloud.cloud_ledger().receipt, run_id)
        if result is None:
            raise HTTPException(404, "No receipt is available for this run")
        return result

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

    @app.post("/api/live-comparisons/prepare")
    async def prepare_live_comparison(
        draft: LiveDraft, request: Request
    ) -> dict[str, object]:
        """Freeze text and estimate cost locally; never start the provider runner."""
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Prepare comparisons from the local app origin")
        return await asyncio.to_thread(live_store.create, draft)

    @app.get("/api/demo-comparison")
    @app.get("/api/demo-comparison/export")
    async def recorded_demo() -> Response:
        """Serve the packaged, immutable live evidence without local run files."""
        return Response(
            (PACKAGE / "resources/demo-comparison.json").read_text(),
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="carbontrace-recorded-comparison.json"'
            },
        )

    @app.get("/api/live-comparisons/{run_id}")
    async def live_comparison_result(run_id: str) -> dict[str, object]:
        """Read CLI progress/results only; browser flags cannot authorize calls."""
        try:
            return await asyncio.to_thread(live_store.view, run_id)
        except FileNotFoundError as error:
            raise HTTPException(404, "Live comparison not found") from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.post("/api/selected-runs/prepare")
    async def prepare_selected_run(
        draft: PreflightRequest, request: Request
    ) -> dict[str, object]:
        """Freeze one selected model and the exact advisor text without inference."""
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Prepare runs from the local app origin")
        try:
            return await asyncio.to_thread(live_store.create_selected, draft)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get("/api/live-comparisons/{run_id}/export")
    async def export_live_comparison(run_id: str) -> Response:
        """Explicit export includes locally saved request text and model outputs."""
        result = await live_comparison_result(run_id)
        return Response(
            json.dumps(result, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="carbontrace-live-{run_id}.json"'
            },
        )

    return app
