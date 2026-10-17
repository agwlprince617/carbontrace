# Next milestone: validate beyond the three-function pilot

The six-response pilot is complete. Both models passed the gate on all three
functions. Compact-first policy replay used 79.4% less estimated inference cost,
with no escalation on these examples. The six-generation experiment's catalog
estimate is USD 0.0183916 before credits, tax and FX. See
[results and limitations](pilot-comparison.md).

All three consumed plan ledgers refuse replay. No further live calls or deployment
are authorized. The web interface continues to use labelled fixtures.

1. **Review quality independently.** Inspect the actual saved suites and reference
   contracts. Passing four seeded faults is a useful gate, not complete correctness.
   Check missing edge cases, redundant assertions, and opportunities to game the
   evaluator. Keep generated Python inside the container execution boundary.
2. **Use the existing broader development set.** The catalog already has 20
   original functions, 80 seeded bugs, and a 14/6 development/holdout split.
   Evaluate the remaining development functions to learn where compact-first
   fails and how much escalation costs. First audit the diversity and difficulty
   already available.
3. **Freeze and price the next experiment.** Record exact prompt/model/config
   hashes, repeats, reuse eligibility, all failed-attempt costs, token limits,
   timeout rules, and zero retries. Reuse only matching responses. Present the
   new batch estimate and obtain explicit approval before live execution.
4. **Freeze routing before holdout evaluation.** Select thresholds using only
   development data. Holdout results should test the frozen policy, not tune it.
   Report quality failures and escalation overhead, as well as cost and tokens.
   These three pilot examples do not establish a general model ranking.
5. **Show measured evidence clearly.** A future read-only results view can load
   the saved pilot report, separating provider observations from synthetic
   fixtures and policy replay. Keep the web live endpoint blocked until a separate
   execution/authorization design is approved. No deployment is needed for review.
6. **Research environmental attribution separately.** Prices, tokens and response
   duration do not measure electricity or carbon. Source and validate an impact
   method before displaying provider emissions or carbon-saving percentages.
   Keep unavailable values explicit rather than inventing model coefficients.

Supporting material: [evaluation protocol](benchmark-protocol.md),
[execution boundary](sandbox.md), [integration history](smoke-results.md),
and [machine-readable pilot evidence](pilot-results.json).
