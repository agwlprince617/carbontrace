# Shipping-fee pair: manual inspection

Receipt `592fc8d97aca4ea5a96ac2cd94c144f6`, recorded 18 October 2026.
Exact visible payload SHA256:
`c20dc84aa8d8c824c2b14c7defb7ec07a27dba60b7c5eb0ee9454dd312d9b549`.

This is inspection of the two [actual returned texts](hosted-comparison-live-results.json).
Neither suite was executed. No automatic functional-quality score or acceptance
result has been assigned. The original receipts retain `quality: not_evaluated`.

| Requested behavior | Expected result | Flash-Lite output | Flash output |
| --- | --- | --- | --- |
| Negative totals | ValueError with standard and expedited delivery | Both covered | Both covered |
| Zero total | Standard 5; expedited 12 | Both covered | Both covered |
| Just below threshold | 49.99: standard 5; expedited 12 | Both covered | Both covered |
| At threshold | 50: standard 0; expedited 7 | Both covered | Both covered |
| Above threshold | Standard 0; expedited 7 | 100, both modes | 50.01 and 100, both modes |
| Default expedited argument | Behaves as standard delivery | Default used in standard cases | Explicit default-argument tests |

Flash-Lite groups its checks into nine test methods and ten assertion contexts;
Flash uses six methods and fourteen assertion contexts. Those counts describe
structure, not a quality score. Flash includes an additional just-above-threshold
example. Both texts use expected values consistent with the supplied rules for
the listed cases, by inspection.

This supports a narrow demo observation: both responses address the requested
cases, with different grouping and output lengths, while Flash-Lite has the lower
observed catalog cost in this one pair. Runtime validation, fault detection and
evaluation on unfamiliar tasks are still needed before recommending a model on
the basis of equivalent functional quality. No request-level carbon was measured.
