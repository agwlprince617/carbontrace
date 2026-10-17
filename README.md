# CarbonTrace

An original, offline-first **environmental comparison and pre-send model advisor**.
Compare published CLEER session estimates, or plan token/cost scenarios and
historical quality evidence before choosing a test-generation model.
The supporting quality lab demonstrates compact-first escalation when a suite
misses required seeded faults. Every attempted generation counts.

This is a new standalone application. It does **not** depend on, import, copy, or
vendor EcoLogits code, regression coefficients, model architecture guesses, or its
model catalog. The earlier EcoLogits checkout is a separate research reference.

## What works now

- A [task-decision view](docs/task-decision.md) that combines original saved suite
  checks and provider usage with a separate CLEER reference. Missing paired
  evidence blocks a recommendation; a failing suite cannot win on energy alone.
- A recorded Gemini workflow inside Task decision: exact shared prompt, completed
  cloud operations, generation settings, inline checked suites, isolated quality
  results and model choice. Viewing this completed run makes no new provider calls.
- A completed [six-response 3.5/3.7 comparison](docs/decision-trial-results.md):
  every suite passed the reference and detected four seeded faults for its task.
  Recorded-usage catalog total USD 0.01010385; checked suites are downloadable as
  text. This is limited development evidence, not measured carbon savings.

- A default environmental comparison for the 51 models and six standardized
  workloads actually present in a pinned CLEER dataset. Original energy means
  and SDs, volume arithmetic, explicit operational-carbon assumptions, attribution,
  limitations, and provenance are visible and exportable. See
  [the research guide](docs/cleer-comparison.md). Data is CC BY-NC 4.0; commercial
  reuse needs separate permission from its publisher.

- A pre-send prompt/context editor, output-plus-reasoning scenarios, model
  selection for the plan, and JSON export without draft text or live execution.
- CLEER references inside the pre-send panel, using an explicitly selected
  workload and electricity assumption. Published energy and source uncertainty
  stay independent of custom-prompt tokens; unavailable model coverage stays null.
- An explicit custom prompt/code workflow with automatic local updates after a
  typing pause, a manual-preview option, visible assumption values, and a worked
  impact calculation. These are local scenarios, not live provider measurements.
- An explicit distinction between identical-prompt pilot observations and rough
  planning scenarios for edited prompts. Editable illustrative carbon scenarios
  show their assumptions; actual provider carbon stays unmeasured.
  See [the advisor guide](docs/pre-send-advisor.md).
- Twenty original Python functions in five families, with 80 seeded defects.
  Fourteen development exercises are available in the local web interface;
  six held-out functions are reserved for final model evaluation.
- Actual local assertion checks against the correct and defective functions.
- Two scripted fixture profiles; an explicit escalation example that increases
  total illustrative usage rather than always claiming a saving.
- A configurable minimum fault-detection threshold plus correct-function checks.
- Runnable pytest-suite and reference-function downloads.
- SQLite history, complete JSON evidence exports, and an offline CLI.
- An original optional operational-energy scenario calculator, including interval
  arithmetic and every failed/escalated attempt.
- The web live endpoint stays blocked. An explicit one-shot CLI supports the
  approved Gemini smoke plan using Google Gen AI SDK 2.31.0; imports and tests
  make no live calls.
- A container-only CLI for candidate pytest suites, with rootless Podman,
  no network, resource limits, bounded output, and cleanup on timeout.
- A frozen benchmark manifest and six-call / 80-call offline run plans.

## Evidence boundaries

**Observed pilot:** six real Gemini responses were evaluated in containers across
three development functions. The advisor shows their historical quality and usage
only when labelled as such; these observations do not predict a new response.

**Pre-send scenarios:** identical payloads can reuse a previously observed input
count. Other drafts use a rough UTF-8 heuristic. Generated-token scenarios are
user assumptions; cost uses a dated catalog snapshot before credits, tax and FX.

**Fixture lab:** candidate suites are hand-authored, duration is assumed (compact
2 s; thorough 8 s), and tokens use `ceil(characters / 4)` per fixture input/output.
This is not a tokenizer, provider telemetry, or evidence about Gemini capability.

The custom-prompt advisor's **illustrative carbon scenario is disabled by default**.
It remains explicitly opt-in, separate from the CLEER workload comparison.
API callers must
explicitly supply `carbon_scenario` to obtain scenario numbers. Actual provider
carbon remains null and separate from the assumed results in exports. This does
not establish Gemini emissions or real savings. See [methodology](docs/methodology.md).
The dataset has a frozen
split; the three-function real-model pilot is exploratory and still needs
independent quality review. Provider energy remains unmeasured.

## Run locally

Requires Python 3.11+ and uv; tested with Python 3.14.5.

```sh
uv sync --locked --cache-dir .uv-cache --no-managed-python
mkdir -p .tmp
.venv/bin/uvicorn carbontrace.app:create_app --factory --host 127.0.0.1 --port 8765
```

Open **http://127.0.0.1:8765**. VS Code has a configured interpreter and two
tasks under **Terminal → Run Task**: start the app and run tests. Stop the server
with Ctrl+C. No credentials or Google Cloud changes are needed.

Start in **Environmental comparison**: select two models and a standard workload,
set the number of sessions and electricity assumption, then calculate and export.
These are published workload estimates, not measurements of an arbitrary prompt.
Gemini 3.8 Flash has no record in the snapshot and remains explicitly unavailable.

In **Before you send**, load **Clamp a value**, and compare the model cost
scenarios and saved quality evidence. Edit the prompt to see exact-match evidence
removed, then export a local plan. This interface does not send requests to models.

In **Task decision**, select a development function and a CLEER reference workload,
then click **Show saved Gemini workflow**. Inspect the exact prompt, recorded API
steps, generated tests, isolated quality results and task-scoped model choice.
This replays the included completed evidence and requires no cloud credentials.

In **Unit test lab**, try **Clamp a value** for a passing compact fixture, then **Merge closed
intervals** for escalation. Inspect the fault evidence, download both suites,
and open saved comparisons. Energy remains uncalibrated unless you explicitly
enable an illustrative scenario.

To run a downloaded suite, save its accompanying function as `subject.py` in the
same folder and run `python -m pytest test_<exercise>_<profile>.py` using an
environment with pytest. Only project-authored fixtures are executed by our tests.
Never run uploaded/model-generated Python on the host. Use the separate
[container runner](docs/sandbox.md) for those suites.

Export the three original demonstrations without starting a server:

```sh
.venv/bin/python -m carbontrace --output data/demo-evidence.json
```

Prepare the benchmark manifest and six-call draft without model access:

```sh
.venv/bin/python -m carbontrace.benchmark manifest --output data/benchmark-manifest.json
.venv/bin/python -m carbontrace.benchmark plan --output data/smoke-plan.json
```

Add `--full` to the plan command for the proposed 80-call exploratory run.
Neither command calls a model. Exact model IDs and cost estimates remain pending;
these files cannot authorize spending. See [the evaluation protocol](docs/benchmark-protocol.md).

## Verify

```sh
.venv/bin/pytest --cov=carbontrace --cov-report=term-missing --basetemp=.tmp/pytest
.venv/bin/mypy --strict src tests
.venv/bin/black --check src tests
.venv/bin/ruff check src tests
node --check src/carbontrace/static/app.js
node --test tests/test_api_client.mjs
```

The tests block real socket connections in-process and use temporary databases.
Six subprocess checks verify our own exported pytest suites actually run.
Container integration tests are opt-in; setup and commands are in
[sandbox.md](docs/sandbox.md). They verify every reference/mutant bundle plus
effective filesystem, network, user, memory, and process restrictions.

## Structure

```text
src/carbontrace/
  app.py             local HTTP interface and fail-closed live endpoint
  benchmarks.py      original demo catalog plus expanded exercises
  expanded_catalog.py explicit cases, seeded fault catalog, frozen split
  extra_functions.py seventeen original functions and their seeded defects
  benchmark.py       manifest, source-only prompts, draft plans, evaluation CLI
  sandbox.py         restricted rootless-container runner; no host fallback
  live_smoke.py      approved one-shot Gemini CLI, usage validation, cost ledger
  preflight.py       offline pre-send cost scenarios and historical quality evidence
  decision.py        quality-gated saved model comparison and checked suite access
  workflow.py        hash-checked trace of the completed Gemini experiment
  resources/         sanitized original pilot and dated price snapshot
  quality.py         assertions, mutation detection, pytest rendering
  engine.py          baseline and escalation policy comparison
  impact.py          original allocated-power scenario arithmetic
  domain.py          validated request/result contracts
  store.py           local SQLite persistence
  static/            original CSS, JavaScript, and SVG mark
  templates/         server-rendered interface
tests/               offline contracts, policy, arithmetic, export, HTTP tests
docs/                methodology, architecture decisions, next integration steps
```

Local history is in `data/evidence.sqlite3` (ignored by Git). Override the directory
with `CARBONTRACE_DATA_DIR`. The development server accepts localhost/loopback
hostnames only. It is not configured for public hosting or multi-user access.
Cloud Run deployment will need explicit host configuration and durable external
storage; local SQLite is not a deployment persistence strategy.

Keep the local server running while using the browser. If the page reports that it
cannot reach CarbonTrace, run the VS Code task **CarbonTrace: start local app**,
then click **Reconnect local app**. Reconnecting preserves the draft already in
the page. Selecting any of the 14 development examples automatically loads its
local preview; **Reset example** restores it after edits. Only clamp, discount,
and merge have saved live-pilot observations. Other examples remain usable for
planning and fixture checks, with quality marked unestablished.

## Next milestone

See [the live integration plan](docs/next-steps.md) and [observed smoke results](docs/smoke-results.md).
The [six-response pilot](docs/pilot-comparison.md) is complete. Both models passed
the gate on all three functions. Compact-first policy replay used 79.4% less
estimated inference cost on those examples, with no escalation. The experiment's
catalog estimate is USD 0.0183916 before credits/tax/FX. This small development
pilot does not establish carbon savings or a general model ranking.
No credentials are needed for the offline benchmark.

The [Vertex AI setup review](docs/vertex-setup.md) and
[priced six-generation proposal](docs/vertex-smoke-quote.json) record the current
setup findings and cost estimate. The user approved the six-generation plan;
the API is enabled, local tools and credentials are ready, and six responses have
been evaluated. Both stopped ledgers and the completed continuation ledger remain
intact. No further live work is authorized. See [live CLI operation](docs/live-smoke.md).

The Cloud project `carbontrace-511814` is a reference identifier only. This app
does not read credentials or call it on startup. The approved local CLI loads
user ADC only when explicitly executed; the web interface stays offline.
