# Results

Status: **local implementation + mechanical unit tests complete**. Remote GPU deployment and Total Values quality evaluation are **blocked** (see `BLOCKERS.md`).

## Preflight

| Check | Result |
| --- | --- |
| Repository | `basetenlabs/.github` profile repo; scaffolded isolated `total-values-pdf-parser/` |
| `git status` | Clean `main` before branch; work on `cursor/total-values-pdf-parser-be64` |
| Existing Truss | None — new Truss scaffolded |
| dots.ocr docs | Official README + HF model card reviewed |
| Model pin | `rednote-hilab/dots.ocr` @ `c0111ce6bc07803dbc267932ffef0ae3a51dc951` |
| Truss CLI | **Not installed / not authenticated** |
| Customer eval inputs | **Missing** |

## Files changed

- `PLAN.md` — full customer-aligned plan (source of truth)
- `BLOCKERS.md`, `RESULTS.md`, `.gitignore`
- `inputs/` — handoff structure (no customer PDFs/URLs)
- `total-values-pdf-parser/` — Truss + packages + tests + eval harness
- Root `README.md` / `profile/` left unchanged

## Model and dependency revisions

| Dependency | Pin |
| --- | --- |
| Model | `rednote-hilab/dots.ocr` |
| Model revision | `c0111ce6bc07803dbc267932ffef0ae3a51dc951` |
| `transformers` | `4.56.1` |
| Base image | `pytorch/pytorch:2.7.0-cuda12.8-cudnn9-runtime` |
| Attention | SDPA (`DOTS_OCR_ATTN=sdpa`) — no flash-attn / custom CUDA ext yet |
| PyMuPDF | `1.26.4` |
| Accelerator | `RTX_PRO_6000:1` |

## Endpoint contract examples

### Request

```json
{
  "documents": [
    {"id": "paper-001", "pdf_url": "https://example.com/signed/paper-001.pdf"},
    {"id": "paper-002", "pdf_url": "https://example.com/signed/paper-002.pdf"}
  ]
}
```

### Response (shape)

```json
{
  "results": [
    {
      "id": "paper-001",
      "status": "succeeded",
      "page_count": 17,
      "document_markdown": "<!-- page: 1 -->\n\n...",
      "pages": [{"page_number": 1, "markdown": "...", "warnings": [], "errors": []}],
      "elapsed_ms": 23140,
      "errors": []
    },
    {
      "id": "paper-002",
      "status": "failed",
      "page_count": null,
      "document_markdown": null,
      "pages": [],
      "elapsed_ms": 940,
      "errors": [{"code": "INVALID_PDF", "message": "The document could not be opened as a PDF"}]
    }
  ]
}
```

## Exact run commands

### Unit / mechanical (local, no GPU)

```bash
cd total-values-pdf-parser
python3 -m pip install pytest PyMuPDF pillow
PYTHONPATH=packages python3 -m pytest tests/ -q
```

### Eval harness dry-run

```bash
cd total-values-pdf-parser
python3 eval/run_total_values_eval.py --manifest eval/manifest.example.jsonl
```

### Deployment — **pending explicit approval** (do not run yet)

```bash
cd total-values-pdf-parser
truss push --publish=false
```

| Item | Value |
| --- | --- |
| Target | Development deployment (not production) |
| GPU | `RTX_PRO_6000:1` (Blackwell, 96 GiB) |
| Expected hourly cost | **~$4.00/hr** ($0.06667/min × 60; Baseten instance reference) |
| Rollback / shutdown | Deactivate or delete the development deployment in the Baseten UI (or equivalent `baseten deployment deactivate <id>` once CLI auth exists) |

## Mechanical test results

### Unit tests (`pytest`)

```text
19 passed in 0.35s
```

Commands:

```bash
cd total-values-pdf-parser
PYTHONPATH=packages python3 -m pytest tests/ -q
```

Covered:

- Request validation (ordering, duplicate IDs, reject prompt/schema/base64)
- HTTPS / localhost URL safety
- PDF open, render order, page-limit, invalid bytes, encrypted PDF rejection
- Succeeded / partial / retry / failed document statuses
- Mixed batch: one result per ID, failures isolated

### Local mechanical checklist (stub OCR, generated PDFs)

```bash
PYTHONPATH=packages python3 scripts/run_mechanical_local.py
```

Result: **passed** — single-page, 17-page ordered stitch, page-limit failure, invalid PDF failure, mixed batch.

### Live GPU / public-PDF inference

**Not run** — Truss auth and deployment approval missing.

### Customer-aligned quality gate

**Not run** — authorized Total Values inputs missing.

## Downstream selection / extraction comparison

**Not run.** Authorized Total Values manifests, baselines, and downstream model access are absent (`BLOCKERS.md` §2). No customer-quality claims.

## Throughput / cost measurements

**Not measured.** Requires live RTX PRO 6000 deployment.

## Recommendation

**Continue** local/parser work is done for the scaffold. **Pause deployment** until:

1. Truss auth is available,
2. User explicitly approves the `truss push` command above,
3. Authorized eval PDFs are provided for the customer quality gate.

Do **not** start a GLM-OCR bake-off unless dots.ocr fails reliability on RTX PRO 6000 or fails Total Values downstream evaluation after deployment.
