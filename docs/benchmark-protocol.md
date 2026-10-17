# Benchmark protocol: Python unit-test generation

Question: can a compact-first generation policy meet the same local test-quality
requirement as a stronger-model baseline, with lower total inference resources?
This experiment can measure quality, billed tokens, cost, and latency. A carbon
claim additionally requires a defensible energy attribution method.

## Dataset and split

The benchmark contains **20 original functions**, four each in validation,
arithmetic, collections, strings, and intervals. Each has explicit requirements,
literal expected cases, and four seeded defective implementations: **80 faults**.
The fixtures pass the reference implementations and detect every seeded defect.
These checks are machine validation; independent human review is still pending.

Fourteen development functions are available in the interface. Six functions are
reserved for final evaluation: `normalize_hex`, `weighted_average`, `rotate`,
`mask_email`, `overlaps`, and `interval_gaps`. This split is frozen before model
responses. Every family has at least one holdout item. The source repository
contains the holdout answers, so separation is procedural, not secret or blind.
Do not use holdout outcomes to tune prompts, thresholds, or routing.

`benchmark-manifest.json` records hashes of each function's source, requirements,
split, oracle cases, and mutant implementations. Change the benchmark version and
record the reason if these change. A manifest mismatch invalidates direct result
reuse. The model prompt contains the reference source and requirements only;
oracle cases and mutant implementations are excluded.

## Staged runs

1. **Six-call smoke test:** clamp, discount, merge × compact and strong model ×
   one repeat. Check access, response format, real usage fields, and isolated
   execution. Its purpose is integration validation, not a model ranking.
2. **Full exploratory run:** 20 functions × two models × two repeats = 80 total
   generation calls. Reuse matching smoke results only if exact model versions,
   settings, prompt hashes, benchmark hash, and usage records match. Otherwise
   request a new cost approval. Do not silently expand the approved call count.
3. Tune only on the 14 development functions. Lock the protocol before making
   or inspecting holdout calls. Two repeats and six holdout functions give
   exploratory evidence, not statistical significance or broad generalization.

Both models receive identical prompts. Record exact model IDs, region, generation
settings, response status, model version returned, and input/output/thinking/cache
token metadata. Do not silently equate omitted usage fields with zero. Defaults
in the draft plan are budget proposals; provider-specific enforcement must be
implemented and checked before approval. Automatic retries and paid grading are
zero. Count failed requests and all billable overhead.

## Quality gate and policy comparison

Run each candidate on the correct function and each of its four mutants in
separate containers. Require a nonempty passing reference run, no skipped/error
tests, consistent test count, and detection of all four seeded defects. A pytest
collection error, timeout, empty suite, missing report, or infrastructure failure
is inconclusive and cannot count as detecting a defect. Mutation detection is
limited to these known faults; it does not establish complete test correctness.
See [the container boundary](sandbox.md) for execution and grading limitations.

Generate the two candidates independently. Evaluate both, then replay:

- **Baseline:** one strong-model generation per task/repeat.
- **Compact-first:** compact generation; if rejected, use the strong generation
  from the matching task/repeat. Include both attempts in the policy total.

Using the same strong candidate for both policies supports a paired offline
comparison. It is a replay of routing, not a second live production deployment.
Report accepted suites per task, failures/inconclusives, escalation rate, and total
tokens/cost/latency. Present aggregate cost per accepted suite alongside the
acceptance rate so failed work is visible. A faster or cheaper model is not
automatically lower carbon. Leave provider carbon unavailable until calibrated.

No real model responses have been collected. Current compact/thorough profiles
are hand-authored fixtures and their usage numbers remain synthetic.
