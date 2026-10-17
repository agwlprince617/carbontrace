# CarbonTrace project instructions

- This is an original project. Do not copy or import EcoLogits implementation,
  regression coefficients, model architecture guesses, or model catalogs.
- Keep development offline. No live model calls, token-count API calls, paid
  grading, grounding, or cloud deployment without a cost estimate and the user's
  explicit approval for the planned run.
- Provider execution exists only in the explicitly approved, one-shot local CLI.
  The web live endpoint stays blocked. No UI switch or environment flag is approval.
- Fixtures and usage are synthetic and must remain labelled in UI and exports.
- Local quality results describe the bundled assertions and seeded mutants only.
  They are not evidence of real model performance or complete correctness.
- Do not invent Gemini energy coefficients. Hardware scenarios are illustrative,
  explicitly enabled, and never presented as measured provider emissions.
- Run pytest with coverage, strict mypy, Black, and Ruff for backend changes.
- Do not execute arbitrary uploaded Python on the host. The offline evaluator
  invokes only project-owned functions and literal, validated test-case data.
