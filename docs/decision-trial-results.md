# Controlled 3.5 Flash-Lite / 3.7 Flash comparison

One fresh response per model/function; three fixed development functions, identical source-only prompts, LOW thinking, 4096-token output limit, no retries. All returned suites ran in the pinned rootless container.

| Function | Flash-Lite: tests / faults detected | 3.7 Flash: tests / faults detected | Flash-Lite catalog cost | 3.7 catalog cost |
|---|---:|---:|---:|---:|
| clamp | 8 / 4 of 4 | 6 / 4 of 4 | $0.0008311 | $0.0016815 |
| discount | 10 / 4 of 4 | 6 / 4 of 4 | $0.0013913 | $0.002442 |
| merge | 10 / 4 of 4 | 13 / 4 of 4 | $0.0011337 | $0.00262425 |

Each suite passed the correct reference and detected every seeded fault. Test counts are not a quality ranking; only these owned requirements and defects were evaluated.

| Recorded metric | Gemini 3.5 Flash-Lite | Gemini 3.7 Flash |
|---|---:|---:|
| Input tokens | 587 | 587 |
| Candidate tokens | 1272 | 1682 |
| Thinking tokens under approved interpretation | 0 | 0 |
| Total tokens | 1859 | 2269 |
| Recorded-usage catalog estimate, USD | $0.0033561 | $0.00674775 |

**Full comparison estimate: USD 0.01010385**, including all six generations. These are reviewed catalog rates, not a verified invoice; credits, tax and FX are excluded. Raw nullable usage and its approved interpretations are preserved in the structured report.

The saved gate supports using Flash-Lite as a candidate for these three tasks. CLEER separately gives it a lower facility-energy mean than 3.7 Flash for the chosen standardized workloads. **This does not establish measured energy or carbon savings for these requests**, general quality equivalence, repeated-run reliability, or end-to-end router savings. Grading overhead is not included in inference cost or carbon.

[Structured results](decision-trial-results.json) · [Exact quote](decision-trial-quote.json) · [Human approval](decision-trial-approval.json) · [Application method](task-decision.md)

Source ledger SHA256: `7eb71fe4091f621a015d0bab0b730d8320d83b75bb5e8eeff3e3a5b9dc5cc4b1`. The original immutable local ledger retains all generated suite text. The packaged text downloads match the evaluated suite hashes.

No retries, paid grading, grounding or deployment. Six generation slots, six token-count slots and two metadata slots are consumed; no further live calls are authorized.
