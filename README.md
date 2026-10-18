# CarbonTrace

**Choose an appropriate AI model before sending your request.** CarbonTrace helps
developers compare cost scenarios, task-specific quality evidence and published
environmental benchmarks when generating Python unit tests.

[Open the Cloud Run demo](https://carbontrace-demo-683634661093.us-central1.run.app/)

## Try the demo

1. **Before you send:** choose the Clamp example, select a CLEER workload, and
   inspect the model suggestion. The preview makes no Gemini calls. Edit the prompt
   to see why the original task's evidence no longer supports a recommendation.
2. **Run & validate:** inspect the included recorded Gemini comparison. Hosted live
   execution lets you review one selected model's frozen request and price, then
   explicitly approve that run.
3. **Environmental evidence:** compare published standardized workloads and inspect
   the technical report, original dataset, uncertainty and electricity assumptions.

The public application now runs fresh Gemini requests. Four of the six shared
reservations remained after verification on 18 October 2026. The pool expires
25 October 2026 at 23:59 UTC. The demo project funds these runs. See
[the verified integration](docs/hosted-live.md).

## What the numbers mean

| Evidence | What CarbonTrace can say |
| --- | --- |
| Pre-call token and cost scenarios | Unknown prompts use a rough input estimate; output and reasoning length are assumptions. Identical pilot prompts can reuse historical input counts. |
| Saved quality results | Six real Gemini responses across three development functions passed the reference and detected four seeded faults each in an isolated runner. This small pilot does not establish general model quality. |
| Fresh hosted responses | Actual provider tokens, model version, elapsed time and a catalog-based cost estimate. Returned code is text only and is not quality evaluated. |
| CLEER environmental references | Published modelled energy for a standardized session; operational carbon uses an explicit electricity assumption. These are not measurements of the visitor's prompt. |

Actual request energy and carbon remain **unmeasured**. CarbonTrace does not derive
carbon from token counts, API price or response latency, and does not claim measured
carbon savings. Recommendations require matching quality evidence; custom prompts
without such evidence remain a manual choice.

## Google Cloud integration

The FastAPI application runs as a non-root container on **Cloud Run**. Gemini
requests use **Google Gen AI SDK 2.31.0** and the Cloud Run service identity through
Google Cloud's Agent Platform API, without browser API keys. Cloud Build and
Artifact Registry build and store the image.

The hosted runner uses signed, ten-minute quotes and a private **Cloud Storage**
ledger. Six reservations are shared globally, including verification calls. Atomic
storage preconditions prevent races and repeated dispatch; restarts and deployments
do not replenish the pool. Failed reservations are consumed. Each generation has
one candidate, LOW thinking, a 4,096-token output request, no tools and no automatic
retries. Token counting rejects inputs over 4,096 tokens before generation.

**Secret Manager** holds the quote-signing key. Runtime permissions are scoped to
inference, the private ledger bucket and that secret. Visitor approval sends the
exact text to Google Cloud. Requests and responses are stored privately, with
deletion scheduled after seven days; run IDs act as unguessable receipt links.
The budget counter is retained so deleting old receipts cannot reset the pool.

Run counts and output settings are safeguards, **not a hard Google billing cap**.
The free planner and recorded results remain available after the pool expires or
is exhausted. Hosted execution never runs generated Python. Local evaluation uses
the separate [isolated container runner](docs/sandbox.md).

## Run locally

Requires Python 3.11+ and uv; verified with Python 3.14.5.

~~~sh
uv sync --locked --cache-dir .uv-cache --no-managed-python
mkdir -p .tmp
.venv/bin/uvicorn carbontrace.app:create_app --factory --host 127.0.0.1 --port 8765
~~~

Open http://127.0.0.1:8765/. Local planning and recorded results require no cloud
credentials. VS Code tasks provide app startup and verification. Cloud deployments
and model calls require a reviewed cost estimate and explicit approval.

The container defaults to hosted-preview, which blocks persistent local routes and
execution. Hosted-live additionally requires the configured private ledger,
signing secret and fixed pool expiry; it has no in-memory spending fallback.
Never place credentials in source, browser code or the container image.

## Verify

~~~sh
TMPDIR="$PWD/.tmp" .venv/bin/pytest --cov=carbontrace --cov-report=term-missing
.venv/bin/mypy src tests
.venv/bin/black --check src tests
.venv/bin/ruff check src tests
node --check src/carbontrace/static/app.js
node --check src/carbontrace/static/hosted-live.mjs
node --test tests/test_api_client.mjs
~~~

Tests block real socket connections and use fake provider responses and temporary
storage. They cover quote tampering, approval, concurrent global reservations,
restart persistence, failures before dispatch and replay prevention. Container
integration checks are opt-in. Tests do not invoke Gemini.

## Sources and implementation

CarbonTrace is an original implementation. Research data is independently
attributed: the pinned **CLEER** dataset contains 51 models and six workloads at
revision c0253b43c50f91e538fecdcd0355a99c62359b78.
[Technical report](https://reports.sustainableaigroup.com/CLEER-Tech-Report/),
[dataset and calculation notes](docs/cleer-comparison.md), and
[CC BY-NC 4.0 data licence](src/carbontrace/resources/CLEER-DATA-LICENSE.txt).
Non-commercial research/demo reuse retains attribution; commercial reuse requires
appropriate permission from the data publisher.

The included research data retains its separate licence. Important modules are preflight.py (decision logic),
research.py (published comparisons), hosted.py (signed approval and global
allowance), and hosted_cloud.py (Google Cloud adapters).

Further evidence: [demo flow](docs/demo-flow.md),
[six-response pilot](docs/decision-trial-results.md),
[recorded live comparison](docs/live-comparison-results.md),
[methodology](docs/methodology.md), and [deployment](docs/cloud-run.md).
