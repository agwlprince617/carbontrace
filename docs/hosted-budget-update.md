# One-click hosted demo — deployed and verified

The deployed implementation replaces the six-run limit with a durable **USD 4.00
model allowance**, including reservations for earlier runs. The approved overall
allowance is **USD 5.00**: USD 4.00 for models and USD 1.00 for one build and light
hosting through **6 November 2026, 11:59 PM IST**. This is not a hard Google Cloud
billing cap. Revision `carbontrace-demo-00004-9wp` served the initial budget update;
the [paired comparison update](hosted-comparison-update.md) is now current. The
[verification receipt](hosted-budget-result.json) records USD 3.843123 remaining,
three prior reservations preserved, and zero agent model/token-count calls.

## Visitor flow

1. Enter a prompt and code. Preview remains free of model and token-count calls.
2. Choose either Gemini model. A signed run option is prepared for free.
3. Click **Run Gemini** once. The short note beside it discloses the sponsor-funded
   reservation, transmission to Google Cloud and private seven-day storage.
4. Inspect the returned text, actual usage and catalog cost. No allowance checkbox,
   separate approval page, automatic retries or generated-code execution.

Fresh custom output is not quality checked. Environmental references remain
published workload context; actual request energy/carbon remain unmeasured.

## Budget controls

The app atomically reserves the full-rate stress scenario before provider-client
creation: 4,096 input tokens and 8,192 generated tokens. Generation still requests
a 4,096-token output limit with LOW thinking. Upward rounding to microdollars gives
USD 0.021709 for Flash-Lite and USD 0.067584 for Flash. Estimates exclude tax/FX
and promotional credits. These use the
[published Google Cloud model rates](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing),
checked 18 October 2026.

All reservations are retained, including failures and short successful responses.
The display is reserved allowance, not invoice spend. A request stops if its
reservation cannot fit in the remaining budget, or after the expiry. Duplicate
IDs never dispatch twice. Accounting anomalies after generation stop new runs.
Other project activity and web hosting are outside the model meter.

Migration preserves the same epoch, prior request IDs and model-specific stress
reservations. It never resets on startup or deployment. Missing or corrupt storage
stops execution. The old revision rejects the migrated schema.

## Deployment scope and verification

The frozen [plan](hosted-budget-plan.json) allows one build (600-second maximum),
one image update and at most one ledger migration write. Existing APIs, IAM,
service accounts, secret, bucket and runtime limits are preserved. No agent
generation or token-count calls, repository push or submission upload are planned.

Local verification: **341 Python tests passed**, **22 optional sandbox tests
skipped**, **97.17% coverage**; strict mypy, Black and Ruff passed. **11 JavaScript
tests passed**, including preview without execution, changed-draft rejection,
duplicate-click protection and receipt-only recovery. The custom-prompt browser
flow was checked locally using a fake provider; this is not fresh Gemini evidence.

The [exact priced plan](hosted-budget-plan.json) was
[approved](hosted-budget-approval.json). Public-page verification confirmed the
enabled one-click action without clicking Run or sending a model request.
