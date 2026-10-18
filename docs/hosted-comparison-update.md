# Paired hosted comparison — deployed and verified

Revision `carbontrace-demo-00005-l9k` adds **Compare Flash-Lite + Flash** alongside the
selected-model action. One click sends the same frozen prompt and context to
Gemini 3.5 Flash-Lite and Gemini 3.7 Flash, with the same generation settings.

The result shows both returned texts, actual input/output/thinking usage, catalog
cost, completion status and individual response times. A summary identifies the
lower observed API cost only when both responses are complete. This is one
sequential observation per model, not a controlled latency benchmark.

This optional experiment incurs both models' costs. It collects comparison
evidence; it does not itself save resources over making one request. Any future
net-savings claim must include the cost and impact of prior evaluation.

Developers can inspect both outcomes to choose a model. Fresh custom quality is
not automatically graded, and generated code is never executed. The comparison
does not claim equal quality or measured carbon savings. CLEER workload means,
per-session SD and source links remain separate published context.

## Funding and execution

The existing USD 4 shared model allowance and 6 November 2026, 11:59 PM IST expiry
are unchanged. The app atomically reserves both stress amounts before creating
the provider client: **USD 0.089293 per pair**, before tax/FX. The full-rate
4,096-input/4,096-output estimate is **USD 0.0483328**. Reservations use twice the
requested output cap as a stress scenario, rounded upward to microdollars.

One signed approval covers both models. Both must fit in the remaining allowance;
the app does not spend on one model when it cannot reserve the pair. Existing
usage and IDs are preserved. Failures retain reservations, stop subsequent calls
and preserve partial output. Duplicate submissions never dispatch again.

Saved-result links reopen the private receipt by its unguessable ID without any
new inference. Anyone holding the link can read it until scheduled deletion;
requests and responses remain subject to the existing seven-day lifecycle.

## Publication and live verification

The [approved frozen plan](hosted-comparison-plan.json) used one build (600-second
maximum) and one Cloud Run image update, using the same runtime settings, APIs,
IAM, secret and private bucket. No ledger reset or new resources are planned.
The new infrastructure estimate is USD 0.05–0.25 within the existing USD 1 hosting
allowance. The overall USD 5 allowance is unchanged, not a hard Google billing cap.

After publication, the shipping-fee verification completed two generations and two
token counts: identical frozen prompt/source, LOW thinking, requested 4,096 output
tokens per model, no retries or paid grading. Both finished with STOP. The pair's
USD 0.089293 reservation is included in the existing USD 4 meter. USD 3.753830
remained afterward. No code was pushed to GitHub or uploaded to the submission.

| Observed result | Gemini 3.5 Flash-Lite | Gemini 3.7 Flash |
| --- | ---: | ---: |
| Input tokens | 209 | 209 |
| Output tokens | 379 | 431 |
| Thinking tokens, documented optional-zero defaults | 0 | 0 |
| Generation response time | 1.67 s | 2.89 s |
| Full-rate catalog estimate, USD | 0.0010102 | 0.0035460 |

The combined catalog estimate was USD 0.0045562, before tax/FX/credits; it is not
an invoice. Flash-Lite's observed catalog cost was 71.5% lower in this pair. This
does not establish equal quality, a general model ranking or carbon savings.

[Open the saved comparison](https://carbontrace-demo-683634661093.us-central1.run.app/?hosted=592fc8d97aca4ea5a96ac2cd94c144f6),
[raw responses and usage](hosted-comparison-live-results.json),
[deployment receipt](hosted-comparison-result.json), and
[manual inspection](hosted-comparison-review.md). Saved private receipts are
scheduled for deletion after seven days; the public app's judging window is unchanged.

Local verification: **347 Python tests passed**, **22 optional sandbox checks
skipped**, **97.22% coverage**; strict mypy, Black and Ruff passed. **13 JavaScript
tests passed**. Browser verification used a fake provider to check custom paired
output, published uncertainty, and reopening a saved result without inference.
Public browser verification reopened this completed result without dispatching
another generation or token count. Both model outputs and published reference
means/SD rendered correctly.
