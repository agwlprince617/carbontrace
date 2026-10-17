# Vertex AI setup and priced smoke test

Status on 2026-10-16: **six-response pilot complete; both models passed all three functions**.
See [observed comparison](pilot-comparison.md) and [attempt history](smoke-results.md).
The local app remains offline and `/api/live-runs` remains blocked.

## Verified environment

- Project `carbontrace-511814` is selected in Chrome.
- Its linked billing account is active/paid and uses INR. The console currently
  displays ₹0.00 for the current month; billing reporting can be delayed.
- The `aiplatform.googleapis.com` service is now **enabled** after approval. The console
  labels it **Agent Platform API**; it is the service used for this integration.
- No budget is listed in the linked account's Budgets & caps view.
- Google Cloud CLI 589.0.0 is installed under `.tools/google-cloud-sdk`, verified
  against the published ARM64 archive checksum. Google Gen AI SDK 2.31.0 is pinned.
- User ADC creation succeeded through the local loopback callback. The quota
  project is `carbontrace-511814`; credentials remain outside the repository.
- API enablement is the only cloud configuration change. No IAM, billing,
  deployment, or budget-notification settings have been changed.

## Proposed small comparison

Use `gemini-3.5-flash-lite` as the compact candidate and `gemini-3.8-flash` as the
baseline candidate, on the **global** endpoint with Standard PayGo. Both are GA in
Google's catalog. Authenticated metadata reads succeeded for both exact model IDs;
all six approved generations succeeded. Do not infer hardware size or carbon from their names. The benchmark
must establish their relative quality.

Sources: [Flash-Lite](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite),
[Flash](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash),
[lifecycle](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions).
Gemini 2.5 is approaching retirement on October 20, 2026, so it is excluded.

The three prompts are the frozen clamp, discount, and merge development prompts.
They contain 767, 850, and 1,021 UTF-8 bytes respectively. These are byte lengths,
not provider token counts. Each model receives the same prompt, one repeat,
one candidate, LOW thinking, and requested `max_output_tokens=4096`. Do not set
custom sampling parameters: Flash-Lite ignores those settings. No tools,
grounding, automatic continuation, model fallback, or automatic retries.

## Cost for review

All rates are **USD per million tokens**, for text-only global Standard PayGo.
The estimate uses 4,096 input tokens per request as a conservative allowance.

| Model | Input | Generated text + reasoning | Three generations at 4,096 input + 4,096 generated tokens each |
|---|---:|---:|---:|
| Gemini 3.5 Flash-Lite | $0.30 | $2.50 | $0.0344064 |
| Gemini 3.8 Flash, before promotional credits | $1.50 | $7.50 | $0.1105920 |
| **Combined estimate** | | | **$0.1449984, approximately $0.15** |

The listed Flash introductory net rates are $0.75/$3.75 through December 31,
2026, provided via credits. This estimate does not rely on receiving credits.
Source: [official pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing),
checked 2026-10-16. INR SKU prices, taxes, and currency conversion can differ.

Requested output limits must not be represented as an account-wide billing cap.
Reasoning-token accounting needs explicit verification on the first response.
There are conflicting firsthand reports about combined output-limit behavior:
[Google developer forum discussion](https://discuss.ai.google.dev/t/gemini-3-8-flash-high-does-maxoutputtokens-include-thinking-tokens/181077).
For review, a stress allowance of **8,192 generated tokens per request** produces
**$0.2678784** before credits/tax/FX. This is a planning allowance, not a guaranteed
provider ceiling. Proposed run allowance: **$0.50 before tax/FX**, with no further
generation after missing usage or an observed limit breach. The allowance is not
permission to add calls, retries, new models, or larger requested output limits.

Before generation, allow at most six `CountTokens` requests to validate the exact
prompts and reject inputs above 4,096 tokens. Google documents token counting as
free: [CountTokens pricing](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/get-token-count#pricing_and_quota).
Allow at most two read-only model-metadata checks. If either preflight operation
fails, stop without guessing access or silently switching models.

## Setup and execution order after approval

Approval is recorded in `vertex-smoke-approval.json` for the immutable quote hash.
The original quote remains unchanged for audit. The one-shot CLI and mocked
transport checks are implemented; see [operation](live-smoke.md).

1. Enable `aiplatform.googleapis.com` for this project. Review any terms/consent
   shown at the final action. Do not enable unrelated services.
2. Install the official Google Cloud CLI locally. Have the user complete the
   Google consent/sign-in step for Application Default Credentials. No API key
   needs to be pasted into chat. ADC credentials belong in the normal local
   credential store, outside the repository; do not export them into the browser.
3. Set the ADC quota project to `carbontrace-511814`. Verify that the user identity
   has access; quota-project selection does not restrict an identity's IAM access.
   Do not create service-account keys or broaden IAM automatically.
   See [ADC instructions](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/start/gcp-auth).
4. Optionally set a small project-scoped billing alert (suggested ₹100/month,
   subject to user approval). A budget alert is not a hard spending cap and this
   document does not authorize creating notifications or billing settings.
5. Implement the Gemini adapter with an explicit live-only CLI, a one-shot run
   ledger, zero SDK/application retries, and no implicit continuation. No app
   startup, test, UI switch, environment variable, or `approved=true` file is
   sufficient authorization. Bind the manual approval to the exact priced plan.
6. Verify authentication/model metadata and prompt counts; then send one of the
   six approved generations. Verify returned model version, input, candidate,
   thinking, cache, finish status, and actual usage before sending the next.
   Unknown usage remains unknown and stops the batch. Timeouts may have incurred
   provider work; record uncertainty and do not retry them automatically.
7. Save raw text and sanitized usage locally. Evaluate suites only in the existing
   rootless container runner. Include rejected attempts and escalation overhead.
   Carbon remains uncalibrated; this run measures quality and usage only.

The 80-generation experiment, deployment, hosted databases, and other paid
services are outside this approval scope and need separate cost review.
