# Hosted Gemini integration

Deployed and verified on 18 October 2026. Revision carbontrace-demo-00002-8j8
serves the approved source snapshot. Both model checks completed through the
public browser form, consuming two of six reservations. Four remained immediately
after verification. The pool expires 25 October 2026 at 23:59 UTC.

[Deployment receipt](hosted-deployment-result.json),
[real responses and usage](hosted-live-results.json),
[HTTP checks](hosted-http-smoke.json), and
[user approval](hosted-deployment-approval.json).

The two fresh responses used 162 input tokens each and 359 / 384 output tokens.
Their combined conservative catalog estimate was USD 0.0040691. This is not the
invoice. Fresh output was not executed or quality evaluated.

![Verified hosted Gemini response](hosted-live-result.jpg)

## One complete decision

Preview an example without model calls → inspect historical quality and separate
CLEER context → choose one model → review a signed exact request and cost → approve
one generation → inspect actual usage and returned text.

Fresh code is never executed on Cloud Run. Saved mutation-test results describe
the saved suites, not a new response. Actual per-request energy/carbon stay null.

## Shared allowance

Six one-generation reservations are shared by everyone, including two verification
runs. The fixed epoch is `carbontrace-public-demo-20261018-v1`; it is not regenerated
on startup, redeployment or receipt expiry. A single private Cloud Storage object
uses generation-match compare-and-swap to reserve capacity before provider-client
creation. Duplicate request IDs return the previous receipt without dispatch.
The operator initializes the meter once; a missing meter stops execution rather
than creating a new allowance.
Errors consume reservations; storage failure stops execution. Quotes expire in
ten minutes. The whole public pool stops at the fixed deployment expiry.

The browser must approve the exact signed plan hash and USD 0.10 allowance. Requests
use only Gemini 3.5 Flash-Lite or 3.7 Flash, global Standard PayGo, one candidate,
LOW thinking, 4,096 input tokens and a requested 4,096 output tokens. One count
operation precedes one generation; no metadata, tools, grounding, fallback, paid
grading or automatic retries are used. These controls are not a billing cap.

Each response preserves raw usage alongside documented optional-zero defaults.
Cost uses conservative full catalog rates: Lite USD 0.30/2.50 and Flash 1.50/7.50
per million input/generated tokens. Flash's current introductory rates may make
the invoice lower. Catalog estimates exclude tax, FX and credits.

## Cloud plan and estimate

Update the existing public service in `carbontrace-511814`, `us-central1`. One build
with a ten-minute timeout, one revision, 1 vCPU / 512 MiB, min 0 / max 1 instance,
concurrency 16 and a 180-second request timeout. Existing build/source resources
remain private. Add one private ledger bucket and one Secret Manager signing key;
enable Secret Manager API. No database or API keys.

Runtime permissions: project custom role containing `aiplatform.endpoints.predict`,
`roles/storage.objectUser` on the ledger bucket, and `roles/secretmanager.secretAccessor`
on the signing secret. The build identity retains its existing limited permissions.
Only the Cloud Run web service is public. Publication follows successful verification.

Proposed first-week allowance: **USD 1.50**, before tax/FX, not a hard billing cap.
Light infrastructure/build/storage/secret use: approximately USD 0.25–1.00.
All six generations at the more expensive model's conservative caps: USD 0.221184;
doubling generated tokens for the stress scenario gives USD 0.405504. The two
verification calls (one per model) are included, not added to those six: combined
estimate USD 0.0483328; stress USD 0.0892928. Actual output is usually much shorter.
One secret version costs about USD 0.06 per full month before shared free quotas.
Traffic and retained infrastructure can continue to incur charges after the
generation pool expires; maximum instances does not cap total web spending.

Approved prompts and responses stay in a bucket with public access prevention and
uniform IAM. A lifecycle rule schedules only `runs/` for deletion after seven days;
the budget object is retained. Receipt IDs are unguessable capabilities; anyone
holding an ID can retrieve that receipt. Do not put sensitive material in the demo.

Sources checked 18 October 2026:
[model pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing),
[Secret Manager pricing](https://cloud.google.com/secret-manager/pricing),
[Cloud Run pricing](https://cloud.google.com/run/pricing),
[storage preconditions](https://docs.cloud.google.com/storage/docs/request-preconditions).
