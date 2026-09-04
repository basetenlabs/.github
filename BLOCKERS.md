# Blockers

Real access / data / deployment blockers only. No speculative timeline estimates.

## 1. Truss CLI not installed or authenticated

- `truss` is not on `PATH` in this Cloud Agent environment.
- No `BASETEN_API_KEY` / Truss credentials were provided.
- **Impact:** cannot `truss push` or exercise a live RTX PRO 6000 endpoint.
- **Required to unblock:** install/authenticate Truss CLI, provide API key via environment, and **explicitly approve** the push command in `RESULTS.md`.

## 2. Authorized Total Values evaluation inputs missing

Inspected:

- `inputs/README.md` — documents expected manifest schema; no customer URLs present.
- `inputs/eval/manifest.jsonl` — placeholder only.
- `inputs/eval/expected/` — empty (gitignored for sensitive baselines).

Missing for the customer-aligned quality gate:

- Authorized raw PDF URLs from Total Values’ evaluation set.
- Expected document IDs / page counts for those papers.
- Notes on the representation currently fed to selection and extraction models.
- A callable path to the existing selection and extraction models (unchanged prompts/schemas).
- Approved Gemini baselines and deterministic expected extraction values.

**Impact:** mechanical tests can use public PDFs only. **No Total Values quality claims** can be made.

## 3. Deployment approval required

Per `PLAN.md`, do not deploy until the user explicitly approves the presented `truss push` command, target environment, RTX configuration, hourly cost, and shutdown procedure.

## 4. Local GPU not available (expected)

No local RTX PRO 6000 in this environment. GPU inference validation is deferred to the remote development deployment after blocker (1) and (3) clear.

## Non-blockers (intentionally out of scope)

- Downstream selection/extraction implementation — remains outside this Truss.
- GLM-OCR Direct bake-off — only if dots.ocr fails reliability or customer-aligned quality gates.
- Production max documents/request — deferred until first deployment is measured.
