# Live integration evidence

**Completed:** six responses are now evaluated. Both models passed all three
functions and detected all 12 seeded faults. The six-generation catalog estimate
is USD 0.0183916. See [the comparison and its limits](pilot-comparison.md) and
[machine-readable evidence](pilot-results.json).

Google sign-in succeeded, and the local ADC quota project is `carbontrace-511814`.
The API is enabled. No deployment, API key, service-account key, or IAM expansion
was created. The web app continues to use labelled fixtures.

## Attempts on 2026-10-16

| Attempt | Metadata reads dispatched | Token counts | Generations | Outcome |
|---|---:|---:|---:|---|
| Original approved plan | 1 | 0 | 0 | TLS connection failure; no retry |
| Explicitly approved replacement | 2 | 1 | 1 | Both model names verified; stopped on omitted usage counters |
| Explicitly approved five-call continuation | 2 | 5 | 5 | Completed; all five suites met the quality gate |

Both stopped ledgers remain intact in `data/live-ledgers/`. Neither can be replayed.
The TLS issue was reproduced with an unauthenticated HEAD request to the endpoint
root. Using macOS system trust succeeded with HTTP 404. The SDK now uses pinned
`truststore==0.10.5` for its client SSL context, with certificate and hostname
verification enabled. No root certificate was installed and verification was
never disabled. See [Truststore](https://truststore.readthedocs.io/en/latest/).

## First real candidate

Gemini `gemini-3.5-flash-lite` returned a complete Python suite for `clamp` in
approximately **1.69 seconds**. A separate local evaluation of that saved response
passed **8 tests** against the reference and detected **all 4 seeded faults**.
It used the pinned rootless container image and made no additional model calls.
This is one simple development example, not a model ranking or general quality claim.

| Provider counter | Raw value |
|---|---:|
| Input | 162 |
| Candidate output | 240 |
| Total | 402 |
| Thinking | omitted |
| Cached input | omitted |

The original protocol required every counter to be present, so it stopped before
automatic quality evaluation. Google's v1 protobuf defines thinking/cache counters
as implicit-presence int32 scalars; ProtoJSON can omit default zero values.
The revised `protojson_v2` policy resolves only omitted thinking/cache/tool
counters to zero, retains raw nullable values, requires input/candidate/total
counters, and rejects negative values, nonzero tool usage, or unreconciled totals.
Sources: [Google schema](https://raw.githubusercontent.com/googleapis/googleapis/master/google/cloud/aiplatform/v1/prediction_service.proto),
[ProtoJSON rules](https://protobuf.dev/programming-guides/json/#presence-and-default-values),
[usage semantics](https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/rest/v1/GenerateContentResponse).

Using that explicit interpretation, the first call's uncached catalog estimate is
**USD 0.0006486**, before credits, tax and FX. This is not a verified Google billing
charge. The original ledger is unchanged; derived quality/accounting is saved in
`data/live-evaluations/first-response-quality.json`.

## Completed comparison

Three compact and three strong responses are now available. The compact-first
policy replay costs USD 0.0031411 versus USD 0.0152505 for strong-only, a 79.4%
reduction on these three examples with the same seeded-fault gate passed.
No energy or carbon reduction is established; provider energy remains uncalibrated.

The [continuation quote](vertex-smoke-continuation-quote.json) covered only the
five previously unsent generations, reusing the saved compact clamp response. It included
five free token counts and two metadata reads, no retries or deployment.
Additional requested-limit estimate: **USD 0.1335296**; stress estimate:
**USD 0.2461696**. Including the saved response gives USD 0.1341782 / 0.2468182.
The proposed allowance remains **USD 0.50 before tax/FX for the six-response pilot**,
not a hard provider billing cap. [Explicit continuation approval](vertex-smoke-continuation-approval.json)
authorized this revised interpretation and the five new calls. The continuation
ledger is complete and cannot be replayed; no further live work is authorized.
