# CarbonTrace: first live comparison

The six-response development pilot is complete: three functions, two Gemini
models, one response per model/function. Five approved new generations reused the
first saved response. No generation was repeated and no deployment was created.

| Observed metric | Gemini 3.5 Flash-Lite | Gemini 3.8 Flash |
|---|---:|---:|
| Suites meeting the quality gate | 3 / 3 | 3 / 3 |
| Seeded faults detected across three functions | 12 / 12 | 12 / 12 |
| Input tokens | 587 | 587 |
| Generated candidate tokens | 1,186 | 1,916 |
| Total tokens | 1,773 | 2,503 |
| Uncached catalog estimate, USD | $0.0031411 | $0.0152505 |

Every suite passed against the correct reference and detected all four seeded
faults for its function. This gate measures these known faults; it does not prove
complete correctness or general equivalence between models.

## Individual suites

| Function | Flash-Lite: passing tests / detected faults | Flash: passing tests / detected faults | Flash-Lite estimate | Flash estimate |
|---|---:|---:|---:|---:|
| Clamp | 8 / 4 | 8 / 4 | $0.0006486 | $0.0044055 |
| Discount | 13 / 4 | 9 / 4 | $0.0012413 | $0.0049815 |
| Merge intervals | 11 / 4 | 15 / 4 | $0.0012512 | $0.0058635 |

Costs use the approved uncached catalog rates before promotional credits, taxes
and currency conversion. They are estimates, not a verified Google invoice.
The full experiment's six generations total **USD 0.0183916**, below the USD 0.50
allowance. The allowance is not a provider billing cap.

## What the routing idea demonstrates

An offline replay selects the compact suite when it passes this quality gate and
would include compact-attempt plus strong-attempt costs if escalation were needed.
For these three examples, all compact suites pass, so there are **zero escalations**.

- Strong-only replay: **USD 0.0152505**.
- Compact-first replay: **USD 0.0031411**.
- Estimated inference-cost reduction on these examples: **79.4%**.

The USD 0.0031411 replay cost is not the cost of the comparison experiment: both
models were actually called to establish the pairs, costing USD 0.0183916 overall.
This replay does not measure a deployed router's end-to-end latency, grading
overhead, or behavior on requests that require escalation.

The result supports testing whether a compact-first quality gate can avoid
unnecessary expensive inference. **It does not establish an energy or carbon
reduction.** Provider energy is unmeasured; prices and tokens cannot supply a
calibrated carbon value by themselves.

## Evidence and next step

[Machine-readable results](pilot-results.json) retain raw nullable usage,
explicit `protojson_v2` interpretations, quality evidence, model versions,
prompt hashes, source-ledger digests, and the policy replay. The prior stopped
ledgers remain unchanged. See [integration history](smoke-results.md).

Local verification: **129 offline tests pass**, with **97.28% backend statement
coverage**; strict mypy, Black and Ruff checks pass. All six generated suites were
evaluated in the pinned rootless container image. The 22 broader opt-in container
tests were not rerun for the approval-binding change.

Next, independently review the generated suites and benchmark requirements, then
evaluate more varied development functions that can expose compact-model failures
and escalation overhead. Freeze routing decisions before touching holdout results.
Any further live batch needs a priced plan and approval. The web interface still
uses labelled fixtures; these observations are saved research evidence.
