# Total Values PDF Parser (Truss)

Dedicated batch PDF → page-aware Markdown endpoint for Total Values.

**Boundary:** this Truss only parses PDFs. Selection, extraction, prompts, schemas, DeepSeek, and statistical analysis stay downstream.

## Layout

```
total-values-pdf-parser/
├── config.yaml          # RTX_PRO_6000:1 Truss config
├── model/model.py       # Truss Model.load / predict
├── packages/
│   ├── contracts.py     # Request/response types
│   ├── pdf.py           # Download, validate, render (PyMuPDF)
│   └── parser.py        # dots.ocr inference + stitch
├── tests/
├── eval/
└── README.md
```

Root handoff files (repo root): `PLAN.md`, `inputs/`, `RESULTS.md`, `BLOCKERS.md`, `artifacts/`.

## Model pin

| Item | Value |
| --- | --- |
| Model | `rednote-hilab/dots.ocr` |
| Revision | `c0111ce6bc07803dbc267932ffef0ae3a51dc951` |
| Attention | PyTorch SDPA (`DOTS_OCR_ATTN=sdpa`) |
| Transformers | `4.56.1` |
| Render DPI | 200 |
| Temporary max pages | 30 |
| Accelerator | `RTX_PRO_6000:1` (~$0.06667/min ≈ **$4.00/hr**) |

## Request / response

```bash
curl -X POST "$PREDICT_URL" \
  -H "Authorization: Api-Key $BASETEN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      {"id": "paper-001", "pdf_url": "https://example.com/signed/paper-001.pdf"}
    ]
  }'
```

Returns one ordered `results[]` entry per input `id` with `document_markdown` (`<!-- page: N -->` markers), per-page markdown, status (`succeeded` \| `partial` \| `failed`), and explicit errors.

## Local tests (no GPU)

```bash
cd total-values-pdf-parser
python3 -m pip install pytest PyMuPDF pillow
PYTHONPATH=packages python3 -m pytest tests/ -q
```

## Deployment (do not run until approved)

Development push to one RTX PRO 6000:

```bash
cd total-values-pdf-parser
truss push --publish=false
```

Expected hourly cost: **~$4.00/hr** while the development deployment is scaled up (`RTX-PRO-6000` at $0.06667/min per Baseten instance reference).

Shutdown / rollback after testing:

```bash
# Deactivate or delete the development deployment from the Baseten UI, or:
# baseten deployment deactivate <deployment_id>
# (exact CLI depends on your installed Baseten/Truss version)
```

See `BLOCKERS.md` — Truss CLI auth is not configured in this environment, so deployment is paused pending credentials and explicit approval.

## Non-goals

No extraction prompts, response schemas, selection logic, business-field JSON, DeepSeek calls, custom queues, or model bake-offs in this Truss.
