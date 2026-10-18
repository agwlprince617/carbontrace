# CarbonTrace project instructions

- This is an original project. Do not copy or import another project's implementation,
  regression coefficients, model architecture guesses, or model catalogs.
- Keep development offline. No live model calls, token-count API calls, paid
  grading, grounding, or cloud deployment without a cost estimate and the user's
  explicit approval for the planned run.
- Hosted execution is explicitly authorized by the user, subject to a priced
  deployment approval, signed request quotes, per-request visitor approval and a
  durable global allowance. No retries or generated-code execution on the host.
- Fixture-lab suites and usage are synthetic and must remain labelled in UI and
  exports. Live CLI results must preserve their actual provenance and raw usage.
- Local quality results describe the bundled assertions and seeded mutants only.
  They are not evidence of real model performance or complete correctness.
- Do not invent Gemini energy coefficients. Hardware scenarios are illustrative,
  explicitly enabled, and never presented as measured provider emissions.
- Run pytest with coverage, strict mypy, Black, and Ruff for backend changes.
- Do not execute arbitrary uploaded Python on the host. The offline evaluator
  invokes only project-owned functions and literal, validated test-case data.
