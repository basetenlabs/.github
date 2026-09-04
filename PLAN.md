# Customer-aligned endpoint boundary

Build one dedicated RTX PRO 6000 endpoint that accepts batches of raw PDFs and returns faithful, page-aware document representations. Total Values’ existing selection and extraction models remain downstream and outside this Truss.

## End goal

```
Batch of raw PDFs
    ↓
Dedicated PDF parser on 1× RTX PRO 6000
    ↓
Normalized document representations
    ├─→ Total Values selection model
    └─→ Total Values extraction model
            ↓
      Final fields and statistical workflow
```

The parser does **not**:

- Accept an extraction prompt.
- Accept a variable response schema.
- Select relevant papers.
- Extract Total Values’ business fields.
- Run DeepSeek or any other downstream model.
- Know anything about the final statistical analysis.

Its sole responsibility is to turn raw PDFs into accurate, consistent input for both downstream models.

## Why this matches Artem

From the September 4 call:

- Most of Total Values’ data arrives as PDFs.
- Long PDFs represented as images encounter page/image limits.
- Artem proposed using a dedicated PDF parser and then the existing downstream models.
- Real-time latency is unnecessary; waiting hours or approximately a day is acceptable.
- Academic papers are relatively standardized.
- Selection and extraction already exist as separate downstream workloads.
- Accuracy can be evaluated deterministically using expected numbers and prior Gemini results.
- “Close enough” quality at materially lower cost is acceptable.
- A dedicated PDF parser on an inexpensive GPU was explicitly of interest.

## Customer-facing contract

### Input

Use signed or otherwise authorized PDF URLs as the required v1 transport. This avoids very large base64 request bodies when submitting batches.

```json
{
  "documents": [
    {
      "id": "paper-001",
      "pdf_url": "https://example.com/paper-001.pdf"
    },
    {
      "id": "paper-002",
      "pdf_url": "https://example.com/paper-002.pdf"
    }
  ]
}
```

Requirements:

- `id` is supplied by Total Values and returned unchanged.
- `pdf_url` must resolve to one PDF.
- Input ordering is preserved in the response.
- A failed document does not fail the rest of the batch.
- Add base64 upload only if Total Values cannot provide signed URLs.
- Set the maximum documents per request after measuring the first deployment; do not invent an untested production limit.

### Output

```json
{
  "results": [
    {
      "id": "paper-001",
      "status": "succeeded",
      "page_count": 17,
      "document_markdown": "<!-- page: 1 -->\n\n...",
      "pages": [
        {
          "page_number": 1,
          "markdown": "...",
          "warnings": []
        }
      ],
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
      "errors": [
        {
          "code": "INVALID_PDF",
          "message": "The document could not be opened as a PDF"
        }
      ]
    }
  ]
}
```

The primary artifact is `document_markdown`, with explicit page boundaries. Page-level output exists for debugging, traceability, and retry behavior.

Possible document statuses:

- `succeeded`: every page completed.
- `partial`: at least one page failed after retry.
- `failed`: the PDF could not be opened or no pages completed.

Never silently omit a document or page.

## Required parser fidelity

The representation must preserve the information the downstream models need:

- Every page, in order.
- Multi-column reading order.
- Table headers, row labels, cells, and units.
- Minus signs, decimal points, percentages, confidence intervals, and sample sizes.
- Formulas, captions, and footnotes.
- Explicit page boundaries.
- Table continuity cues when a table spans pages.

It does not need to reconstruct a perfect visual replica of the PDF. It needs to preserve enough structure and exact text for selection and extraction to behave correctly.

## Model and hardware

### Initial implementation

- Model: rednote-hilab/dots.ocr
- Accelerator: one RTX PRO 6000.
- Deployment: one custom Truss.
- PDF decoding: PyMuPDF inside the same container.
- Inference: process rendered pages through dots.ocr, preserve document/page ordering, and stitch the output.

Why dots.ocr first:

- It combines layout recognition and OCR in one model.
- It has an official PDF parsing path.
- It produces structured document output suitable for tables.
- Internal testing found strong quality/performance and favorable RTX PRO 6000 economics.

Do not begin with a model bake-off. Build dots.ocr first. Test GLM-OCR Direct only if dots.ocr fails the Total Values downstream evaluation or cannot run reliably on RTX PRO 6000.

## Single-Truss architecture

```
predict(request)
  ├─ validate documents[]
  ├─ download each PDF with limits
  ├─ validate PDF bytes
  ├─ render pages at 200 DPI
  ├─ flatten ready pages for GPU inference
  ├─ run dots.ocr
  ├─ retry one failed page once
  ├─ restore page and document ordering
  ├─ stitch document Markdown
  └─ return one result per input document
```

There is no separate CPU service, Chain, queue, database, prompt router, or extraction layer.

## Runtime requirements

- Accelerator: `RTX_PRO_6000:1`.
- Blackwell-compatible base image.
- CUDA 12.8 or later.
- PyTorch build with `sm_120` support.
- A dots.ocr-supported runtime.
- Exact model revision and dependency versions pinned.
- Prefer a verified current runtime and PyTorch SDPA before adding custom CUDA extensions.

At startup, log the model revision, PyTorch version, CUDA version, and GPU name. Do not log PDF contents or parsed text.

## Input safety and limits

- Require HTTPS unless an explicitly approved development fixture is used.
- Apply a download timeout and maximum file size.
- Block local/private-network addresses and unsafe redirects.
- Verify PDF magic bytes and open with a PDF parser before inference.
- Reject encrypted PDFs clearly.
- Start with a temporary 30-page limit because Total Values’ known papers are primarily 14–21 pages.
- Delete temporary files after each request.
- Do not retain or commit customer PDFs or parsed contents.

## Cursor execution context

The implementation agent will run inside Cursor, not this Notion conversation. Assume it has only:

- The current repository and filesystem.
- A local terminal.
- Git access already configured on the machine.
- Public internet access when permitted.
- A locally installed and authenticated Truss CLI, if the user has configured it.
- Environment variables explicitly provided by the user.

Do **not** assume it can access Notion, Slack, Gong, Gmail, Runlayer, internal search, this conversation, customer deployments, or internal repositories that are not already checked out.

### Self-contained handoff

Before asking Cursor to execute, copy this plan into the working repository as `PLAN.md`, or paste the complete Cursor prompt at the bottom of this page. The repository—not workspace search—must contain every requirement needed to implement the endpoint.

Expected local handoff structure:

```
PLAN.md
inputs/
├── README.md
└── eval/
    ├── manifest.jsonl        # authorized document IDs, URLs, and expected metadata
    └── expected/             # optional approved downstream results; gitignored if sensitive
```

The agent must create:

```
RESULTS.md                    # commands, tests, measurements, and conclusions
BLOCKERS.md                   # only real access/data/deployment blockers
artifacts/                    # local benchmark outputs; gitignored
```

No customer PDFs, parsed contents, credentials, or private URLs may be committed.

### Cursor preflight

The agent should first:

1. Inspect the current directory and existing repository instructions.
2. Check `git status` and avoid overwriting unrelated work.
3. Determine whether it is in an existing Truss repository or needs to scaffold one.
4. Read the official dots.ocr documentation and pin an exact model revision.
5. Verify the Truss CLI is installed and authenticated before attempting deployment.
6. Confirm the target is a development deployment on one RTX PRO 6000.
7. Treat missing credentials, deployment approval, or authorized evaluation data as blockers; never fabricate them.

A local GPU is not required to write the Truss or unit-test PDF handling. GPU inference validation happens after the remote RTX deployment is active.

If customer evaluation inputs are missing, the agent should still build and mechanically test the endpoint using a public PDF, record the missing customer gate in `BLOCKERS.md`, and make no customer-quality claims.

## Execution plan

These are evidence gates, not calendar estimates. A coding agent should continue automatically until blocked by access, deployment approval, customer-data permission, or a failed quality gate.

### 1. Validate the local handoff inputs

Inspect `inputs/README.md` and `inputs/eval/manifest.jsonl` for:

- A small authorized set of raw PDF URLs from the existing evaluation.
- Expected document IDs and page counts.
- Notes describing the representation currently sent into the selection model.
- Notes describing the representation currently sent into the extraction model.
- A local command, script, or documented API call for invoking both downstream evaluations without changing their prompts or models.
- Existing Gemini outputs and deterministic expected extraction values, if approved for local use.

If any item is unavailable, record it precisely in `BLOCKERS.md`. Continue building the parser and running public mechanical tests. Do not attempt to retrieve customer data from systems the Cursor agent cannot access, and do not redesign downstream prompts or schemas.

### 2. Build the parser

Create the smallest viable repository:

```
total-values-pdf-parser/
├── config.yaml
├── model/
│   └── model.py
├── packages/
│   ├── pdf.py
│   ├── parser.py
│   └── types.py
├── tests/
│   ├── test_input_validation.py
│   ├── test_pdf_rendering.py
│   └── test_ordering_and_partial_failure.py
├── eval/
│   ├── run_total_values_eval.py
│   └── manifest.example.jsonl
├── README.md
└── RESULTS.md
```

Implement:

- Batch URL input.
- PDF validation and rendering.
- dots.ocr loading and page inference.
- Stable page/document ordering.
- Explicit document/page errors.
- Stitched Markdown with page boundaries.
- Basic elapsed-time reporting.

### 3. Push the dedicated endpoint

Before deployment, present:

- Exact `truss push` command.
- Target development environment.
- RTX PRO 6000 configuration.
- Expected hourly cost.
- Rollback or shutdown command.

After approval, push the Truss and wait for the endpoint to become active.

### 4. Mechanical validation

Run:

- One valid single-page PDF.
- One valid 14–21-page PDF.
- A batch containing multiple PDFs.
- Invalid PDF bytes or an invalid PDF URL.
- A PDF over the temporary page limit.
- A mixed batch where one document fails.

The batch passes if every input ID receives exactly one ordered result and no page disappears silently.

### 5. Customer-aligned quality evaluation

Run the first authorized Total Values documents through the new parser. Then, without modifying downstream logic:

1. Send parser output into the existing selection model.
2. Compare selection decisions with Total Values’ current baseline.
3. Send the same parser output into the existing extraction model for the selected documents.
4. Compare final extracted numbers with deterministic expected values and previous Gemini results.

The parser wins only if both downstream stages continue to work. Attractive Markdown by itself is not a success criterion.

### 6. Scale through existing customer gates

Proceed only if the small set is promising:

- Existing approximately 100-paper evaluation.
- Planned approximately 2,000-paper evaluation.
- If successful, the production shape of approximately 1 million selection documents and 30,000 extraction documents.

Use Total Values’ existing batch/flex workflow when available. Do not build a custom 24-hour queue inside the parser container.

## Acceptance criteria

Do not invent a universal OCR score. Use Total Values’ actual downstream outcomes.

### Mechanical

- One result for every submitted document ID.
- All pages represented and ordered.
- Explicit partial or failed status when necessary.
- No unbounded repetition output.
- No customer content logged or retained.

### Selection compatibility

- Run Total Values’ existing selection model unchanged.
- Compare its decisions with the established baseline.
- Investigate any material decision differences by tracing them to parser output.

### Extraction compatibility

- Run Total Values’ existing extraction model unchanged.
- Score deterministic expected numerical values.
- Compare with previous Gemini outputs.
- Confirm that signs, decimals, units, confidence intervals, headers, and row associations survive parsing.

### Commercial

- Quality is “close enough” by Total Values’ standard.
- End-to-end cost is materially below Gemini.
- Batch completion fits Total Values’ non-real-time delivery window.

The exact acceptable accuracy difference should be confirmed with Artem rather than invented in this plan.

## Go/no-go tree

```
Can dots.ocr run reliably on one RTX PRO 6000?
├─ No → Fix one bounded compatibility issue; otherwise test GLM-OCR Direct
└─ Yes
   └─ Does every input PDF produce complete ordered parser output?
      ├─ No → Fix parser mechanics before evaluating model quality
      └─ Yes
         └─ Does Total Values’ existing selection model remain acceptable?
            ├─ No → Inspect parser fidelity on changed decisions
            └─ Yes
               └─ Does the existing extraction model remain close enough to Gemini?
                  ├─ Yes → Run the 100-paper and then 2,000-paper gates
                  └─ No → Inspect exact parser-caused field failures
                         ├─ dots.ocr issue → Test GLM-OCR Direct
                         └─ downstream issue → Do not expand parser scope
```

## Explicit non-goals

- Prompt input.
- Variable extraction schemas.
- Final business-field JSON.
- Selection or screening logic.
- Extraction logic.
- DeepSeek calls from inside the Truss.
- Statistical analysis.
- General-purpose document ingestion.
- Formal public benchmark programs.
- Multiple OCR models in production.
- PP-DocLayout or a second service without evidence.
- A custom job queue, database, dashboard, or multi-region architecture.
- Fine-tuning before the base parser is evaluated.

## Paste-ready coding-agent prompt

You are a coding agent running inside Cursor. Assume you have the current repository, local filesystem, shell, git, public internet when available, and an installed Truss CLI only if the user configured it. You do not have access to Notion, Slack, Gong, Gmail, Runlayer, this conversation, internal search, or customer systems unless files or credentials are explicitly present in the working environment. Do not claim to have used unavailable systems.

Treat `PLAN.md` as the source of truth. Inspect existing repository instructions and `git status` before editing. If the directory is empty, scaffold the repository described in the plan. If it is an existing repository, avoid unrelated changes and work in a clearly isolated folder or branch.

Build the customer-aligned Total Values batch PDF parser specified in `PLAN.md`.

The endpoint boundary is strict: accept a batch of raw PDF URLs and return a faithful page-aware document representation. Do not accept extraction prompts or schemas. Do not perform selection, business-field extraction, DeepSeek calls, or statistical analysis. Total Values already runs selection and extraction downstream with separate models.

Use one custom Truss on one RTX PRO 6000. Start with rednote-hilab/dots.ocr. Decode PDFs with PyMuPDF inside the same container, render at an initial 200 DPI, process pages through dots.ocr, preserve page and document order, retry one failed page once, stitch document Markdown with explicit page markers, and return one result or explicit error for every input document ID.

Use signed PDF URLs for v1. Add base64 only if the customer cannot provide URLs. Apply basic download, file-size, page-count, encrypted-PDF, and unsafe-network protections. Do not log or retain customer document contents.

Do not run a broad model bake-off. Test GLM-OCR Direct only if dots.ocr fails the customer-aligned downstream evaluation or cannot run reliably on RTX PRO 6000. Do not add PP-DocLayout, another service, a custom queue, a database, or production platform features.

After the endpoint works mechanically, evaluate it by passing its output into Total Values’ existing selection and extraction models without changing their prompts or logic. Compare selection decisions, deterministic extracted numbers, and previous Gemini results. Parser Markdown quality alone is not the decision metric.

Proceed autonomously through local implementation and tests. If authorized customer inputs are absent, use a public PDF only for mechanical validation, record the missing customer gate in `BLOCKERS.md`, and make no Total Values quality claims. Never invent credentials, deployment identifiers, internal source paths, or evaluation results.

Pause only for missing repository access, missing Truss authentication, deployment approval, customer-data permission, or a failed quality gate requiring an architecture decision. Before `truss push`, show the exact command, target development environment, RTX configuration, expected hourly cost, and shutdown/rollback procedure. Do not deploy until the user explicitly approves the command.

Report:

1. Files changed.
2. Exact run and deployment commands.
3. Model and dependency revisions.
4. Endpoint request and response examples.
5. Mechanical test results.
6. Downstream selection and extraction comparison results.
7. Actual throughput and cost measurements.
8. Continue, adjust, or stop recommendation.
