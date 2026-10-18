# Bounded live custom comparison


Open **Live comparison**, or use **Compare this draft with live Gemini** in
Before you send. This feature prepares an exact request for Gemini 3.5 Flash-Lite
and Gemini 3.7 Flash; the browser itself has no provider client or execution route.

## Demo steps

1. Choose one of the three reviewed functions, or paste custom code. Write a test
   generation instruction and optional visible context. Select a separate CLEER
   reference workload and electricity assumption.
2. Confirm local storage, then **Prepare exact request and cost**. Preparation
   makes no Google calls. Inspect the frozen payload, source hash, price, model IDs
   and limits. It saves the exact request locally under ignored `data/`.
3. From the CarbonTrace folder, activate your virtual environment and run
   `python -m carbontrace.live_compare_cli --id <run-id>` in your terminal.
   For a custom store, add `--directory <configured-store>`.
   The CLI prints the full plan and asks you to type `APPROVE <full-plan-sha256>`.
   No piped approvals, environment unlocks, browser approvals or automatic retries.
   Cancel by typing anything else. A chat assistant still needs explicit human
   approval of the particular priced plan before typing that phrase for you.
4. For reviewed functions, ensure the existing pinned rootless Podman runner is
   available first; see [sandbox setup](sandbox.md). The CLI verifies it before
   creating a provider client. Custom code is text only and is never executed.
5. Watch real operation states and responses in the browser, or click **Refresh
   runner results**. Polling reads local files only, pauses on hidden screens,
   stops after completion/error and is bounded to ten minutes per follow action.
6. Inspect actual returned Python, raw and interpreted usage, elapsed API response
   time, usage-based catalogue cost and any isolated quality outcomes. Export
   explicitly includes the original request and response text. Use **Reopen frozen
   comparison** to revisit after a reload; the link contains only the local run ID.

## Exact execution boundary

Each immutable quote expires after 24 hours and permits two metadata reads, two
token-count checks and two generations. Both metadata identities and prompt counts
are checked before any generation. Inputs must be between 1 and 4,096 tokens;
each generation requests one candidate, LOW thinking and a 4,096-token output cap.
No tools, grounding, automatic continuation, retries, model fallback, paid grading
or deployment. Both models receive exactly the same full payload. Counts are
actual Google values, not the planner's local heuristic.

Terminal approval must match the full quote hash. The runner exclusively reserves
the result before credentials or RPC, and cannot replay a consumed quote after a
crash, timeout or setup failure. Three run slots are available in this checkout's
local store; a failure also consumes its slot. The web offers no reset or approval
endpoint. These files protect against accidental repeat execution; the local
filesystem owner is trusted and can modify the application, so this is not an
account-wide billing control or a multi-user authorization service.

The global Standard PayGo pricing snapshot was checked on 2026-10-17: Flash-Lite
USD 0.30/2.50 and Flash USD 1.50/7.50 per million input/generated tokens. Flash uses
full rates without depending on promotional credits. Per comparison, conservative
planning cost is USD 0.0483328 at 4,096 input plus 4,096 generated tokens per model;
stress cost is USD 0.0892928 at 8,192 generated tokens per model. The proposed
allowance is USD 0.10 before credits/tax/FX, not a hard provider billing cap.
[Official pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing).

Primary input/candidate/total usage is required. Omitted thinking/cache/tool scalar
counters use the documented proto3 zero-default policy `protojson_full_v3`, retaining
raw nulls. Inconsistent usage, a missing model version, nonzero cache/tool usage or
observed token-limit breach stops later calls. Transport errors may already have
incurred work: the dispatched operation and billing uncertainty remain visible,
and the known total is not presented as the complete bill. No retry is attempted.

## What the evidence supports

Reviewed source must equal the original function exactly. The evaluator uses the
pinned restricted runner against its correct implementation and four seeded bugs.
The result must match task, suite hash and runner image. A clean nonempty reference
pass and all four clean mutation detections are required; errors, skips, changed
test counts or missing checks do not qualify. These checks cover those contracts,
not all correctness or adversarial integrity. Generated code never runs on the
host. Editing source automatically selects **Custom** and the server rejects a
false reviewed-source claim.

Custom requests produce actual model outputs and usage but **quality not evaluated**,
with no recommendation. For reviewed tasks, passing candidates are considered
first; among passing candidates, use the lower published CLEER mean for the chosen
standardized workload. Reference energy/SD, editable operational-carbon arithmetic,
source versions and licence are displayed separately. No tokens, API duration or
price are converted to measured request carbon, and selecting an agentic benchmark
does not execute an agentic workload. Actual request energy/carbon remain null.

## Current validation status

The transport and evaluator have offline tests with explicitly synthetic doubles,
including failure and replay cases. The first exact approved Clamp plan
(`317e3391ea97…`) also completed through the user's own terminal after agent terminal
input was blocked by automatic approval review. Both real model responses passed
the reference and detected all four seeded faults; total recorded-usage catalog
cost was USD 0.0046848 before credits/tax/FX. Chrome verified real generated text,
quality outcomes, recommendation and the exact downloaded export.
See [completed live evidence](live-comparison-results.md). Each further live run
still needs its own exact priced approval. The packaged recorded comparison is available from Run & validate as a demo fallback.

API surface:

- `POST /api/live-comparisons/prepare`: local quote preparation, same-origin check.
- `GET /api/live-comparisons/{id}`: read-only local status/results.
- `GET /api/live-comparisons/{id}/export`: explicit request/results export.
- `POST /api/live-runs`: remains HTTP 423; there is no browser execution endpoint.

Credentials stay in the existing user ADC store outside the repo and browser.
The quota project must be `carbontrace-511814`; no keys or IAM changes are created.
This feature is localhost-only and is not a public hosted execution design.
