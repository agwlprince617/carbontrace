# Approved live smoke CLI

The user explicitly approved quote
`b12276de602c9314c206828d3a8154f306e1a3c26d7c7c227d7ec05c259fcd8f`:
six generations, six free prompt counts, two metadata reads, no retries or
deployment, and a proposed USD 0.50 allowance before tax/FX. This is not a hard
Google billing cap. `vertex-smoke-approval.json` records that human decision.
Files/flags do not supply authorization for another experiment or a public API.

## Current setup

- `aiplatform.googleapis.com` enabled in `carbontrace-511814`.
- Official Google Cloud CLI **589.0.0** installed in `.tools/google-cloud-sdk`.
  The current ARM64 archive matched published SHA256
  `71b37ca07ab0f9bc43898e42c913e10f143166230ab31e0bbea3632dbc77b010`.
  The versioned download had a different archive digest and was never executed;
  installation used the verified current archive.
- Google Gen AI SDK **2.31.0** pinned in pyproject and uv.lock.
- Google sign-in succeeded; the ADC quota project is `carbontrace-511814`.
- The original attempt stopped on TLS before generation. The explicitly approved
  replacement verified both model names and sent one generation, then stopped on
  omitted thinking/cache counters. See [results](smoke-results.md).
- The user then explicitly approved the remaining five generations under
  `protojson_v2`. That continuation completed, giving six evaluated responses.
  Both models passed the gate on all three functions. See [comparison](pilot-comparison.md).
- Client HTTPS uses pinned Truststore 0.10.5 and existing OS certificate trust.
  Certificate and hostname verification remain enabled.
- No service-account key, API key, IAM expansion, deployment, or budget created.

For a future fresh sign-in, set the approved ADC quota project:

```sh
TMPDIR="$PWD/.tmp" CLOUDSDK_PYTHON="$PWD/.venv/bin/python" \
  CLOUDSDK_CORE_DISABLE_USAGE_REPORTING=true \
  CLOUDSDK_COMPONENT_MANAGER_DISABLE_UPDATE_CHECK=true \
  .tools/google-cloud-sdk/bin/gcloud auth application-default \
  set-quota-project carbontrace-511814
```

No access token should be printed or copied. The runner loads only the normal
local user ADC file and requires the matching quota project; it does not fall
back to ambient API keys. ADC remains outside the repository and container.

All three approved plans are consumed and their ledgers refuse replay. Start
the existing Podman VM and verify the recorded image as described in
`sandbox.md` only before a newly approved experiment. The original command was:

```sh
TMPDIR="$PWD/.tmp" XDG_RUNTIME_DIR="$PWD/.runtime" \
  .venv/bin/python -m carbontrace.live_smoke \
  --plan docs/vertex-smoke-quote.json \
  --approval docs/vertex-smoke-approval.json \
  --image sha256:af50fdb931d09782d5a8aee70ccbaa5856e8661c4af09c64279fc59213cab021 \
  --execute-approved-smoke
```

## What the runner guarantees locally

- It validates the immutable full quote hash, recorded human approval, current
  benchmark hash, request order, model IDs, and every source-only prompt hash.
- Before any metadata/count/generation RPC, it persists a consumed operation
  slot. An exclusive ledger refuses automatic replay after success, error,
  timeout, or interruption. Never delete a ledger to retry a run.
- SDK `attempts=1` disables default retries. `automatic_continuation=False`
  disables extra continuation requests. Automatic function calling is disabled;
  there are no tools, grounding, model fallback, or custom sampling parameters.
- It validates prompt counts, returned model version and usage, candidate/think
  limits, and remaining allowance serially. Missing counters remain null and stop
  further generation under the original `strict_v1` protocol. The separately approved
  five-call continuation used documented ProtoJSON zero defaults for omitted
  thinking/cache/tool scalars; primary counters and reconciled totals remain
  mandatory, and raw values remain available. This is bound to a separate quote
  with its own human approval; it cannot relax an earlier plan.
- Unknown billable outcomes remain unknown in the ledger. Known prior costs are
  preserved separately; failed/incomplete/rejected candidates still count.
- Static input rejection is a quality rejection. Sandbox infrastructure failure
  stops further spending. Generated code executes only in the restricted container.
- Complete pairs support a labelled offline policy replay. Carbon is unavailable
  without provider-energy calibration, regardless of cost/token differences.

The ledger is saved to `data/live-ledgers/<plan-sha256>.json` with original response
text, sanitized telemetry, quality results, cost estimates, and stop reasons.
It contains no credentials or HTTP headers. Protect it as local experiment data.
A stopped run exits nonzero. A timeout does not prove no provider work occurred.

The web live endpoint still returns 423, including when an environment or request
flag says `approved=true`. This local single-operator design is not public auth:
the filesystem owner can edit receipts/code/ledgers. Public deployment needs a
separate authorization and execution design.

## Offline validation

129 offline tests pass, with 97.28% backend statement coverage. Strict mypy,
Black, Ruff, and JavaScript syntax checks pass. SDK HTTP requests are intercepted
with a mock transport: a retryable 503 produces one request. No test loads the
user's real credentials or contacts a model. The previous 22 opt-in container
checks cover the existing runner; they were not repeated for this adapter-only
change. The six actual generated suites were evaluated in the rootless container,
passing references and detecting all four faults for each function/model pair.
