# Methodology and provenance

## 1. Functional unit and scope

The unit of comparison is one **acceptable test suite for one curated Python
function**, under a specified seeded-fault detection threshold. A suite must pass
against the reference function. We count every attempt in the selected policy,
including a rejected compact suite and an escalation to the thorough fixture.

This is a scripted policy demonstration, not measured model selection. The suite
and its cases are manually authored, and the literal assertions are evaluated
without executing arbitrary user Python. The rendered pytest exports implement
the same cases and are verified separately by the automated test suite.

## 2. Quality evidence

Each exercise has four deliberately defective implementations. A defect is
detected if any suite assertion fails for that implementation. Detection rate is
detected seeded defects divided by the four known defects. Every assertion must
also pass against the correct implementation.

Detecting all eighty curated defects is not a proof that a test generator will
detect arbitrary faults. These examples are not representative or held-out model
evidence, and the fixture profiles do not stand in for particular Gemini models.
Never describe this prototype's local scores as real model accuracy.

## 3. Usage provenance

Tokens are an explicit illustration: input characters from the reference source
and output characters from the rendered suite, each divided by four and rounded
up. This does not use a real tokenizer. Elapsed inference times are arbitrary
fixture assumptions: compact = 2 seconds; thorough = 8 seconds. Local checking
time is not inference duration, and is not being measured as inference energy.

## 4. Original scenario calculator

No model energy factors are supplied. The user must explicitly enable the
illustrative scenario before any energy or GWP number is returned.

For each attempted generation:

```text
electricity_Wh = allocated_compute_watts × seconds / 3600 × PUE
operational_GWP_gCO2e = electricity_Wh / 1000 × grid_gCO2e_per_kWh
```

Power is an interval. Both bounds are propagated through positive multipliers,
then summed across all attempted generations. An interval is not a statistical
confidence interval. A direction is declared only for non-overlapping GWP bounds;
overlap means insufficient support for a clear ranking under these assumptions.

Allocated compute watts must already account for concurrency and shared hardware.
PUE should only be applied to IT energy that excludes facility overhead. Do not
apply PUE again to an energy factor already measured at facility level.

UI defaults (30–60 W compact, 120–180 W thorough, PUE 1.2, electricity intensity
400 gCO2e/kWh) are **arbitrary examples**, not facts about Google hardware or any
named model. Mapping them to a provider without evidence is unsupported.

The boundary includes assumed operational computation and facility overhead.
It excludes model training, hardware manufacturing/end of life, networking,
end-user devices, and local quality-check infrastructure. It is not a full SCI
score, life-cycle assessment, verified carbon account, or carbon-offset quantity.

## 5. Scientific references versus implementation

The Green Software Foundation describes operational emissions as electricity
consumption multiplied by the applicable electricity carbon intensity, and SCI
additionally includes embodied emissions and a functional unit:
[SCI specification](https://sci.greensoftware.foundation/).

Our elementary unit conversions are independently implemented. We do not claim
SCI conformance. The application uses original calculation code; published CLEER
workload data is separately attributed and licensed.

## 6. Before claiming real efficiency or savings

- Collect actual provider token usage and response metadata, with source/time and
  exact model/configuration identifiers.
- Establish a representative dataset, independent fault oracles, repeated runs,
  and a held-out evaluation set. Calibrate automated quality judgments.
- Include failed generations, retries, routing/judging inference, and quality
  infrastructure in the chosen accounting boundary.
- Obtain a sourced energy attribution method for the provider/model/workload.
  Better telemetry alone does not reveal provider GPU energy.
- Retain unknown estimates as unavailable. Show scenarios separately from
  empirical observations; do not translate token or price reductions into
  carbon reductions without supporting methodology.
