"""dots.ocr page inference, retry, ordering, and Markdown stitching."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from pdf import DEFAULT_DPI, DEFAULT_MAX_PAGES, PdfError, RenderedPage, download_pdf, render_pages, temporary_workdir, validate_and_open_pdf
from contracts import (
    DocumentInput,
    DocumentResult,
    DocumentStatus,
    ErrorItem,
    PageResult,
    parse_documents,
    results_payload,
)

logger = logging.getLogger("total_values_pdf_parser")

# Official dots.ocr layout+OCR prompt (prompt_layout_all_en).
LAYOUT_PROMPT = """Please output the layout information from the PDF image, including each layout element's bbox, its category, and the corresponding text content within the bbox.

1. Bbox format: [x1, y1, x2, y2]

2. Layout Categories: The possible categories are ['Caption', 'Footnote', 'Formula', 'List-item', 'Page-footer', 'Page-header', 'Picture', 'Section-header', 'Table', 'Text', 'Title'].

3. Text Extraction & Formatting Rules:
    - Picture: For the 'Picture' category, the text field should be omitted.
    - Formula: Format its text as LaTeX.
    - Table: Format its text as HTML.
    - All Others (Text, Title, etc.): Format their text as Markdown.

4. Constraints:
    - The output text must be the original text from the image, with no translation.
    - All layout elements must be sorted according to human reading order.

5. Final Output: The entire output must be a single JSON object.
"""

MODEL_ID = "rednote-hilab/dots.ocr"
# Pinned Hugging Face revision (sha from HF API at implementation time).
MODEL_REVISION = "c0111ce6bc07803dbc267932ffef0ae3a51dc951"
MAX_NEW_TOKENS = 16384
PAGE_RETRY_ATTEMPTS = 1  # retry one failed page once → total 2 attempts


class PageOCREngine(Protocol):
    def infer_page(
        self,
        image: Any,
        prompt: str = LAYOUT_PROMPT,
        *,
        page_number: int | None = None,
    ) -> str:
        """Return raw model text for one page image."""


@dataclass
class PageInferenceOutcome:
    page_number: int
    markdown: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: ErrorItem | None = None


def _clean_text(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[:2] == "`$" and text[-2:] == "$`":
        text = text[1:-1]
    return text


def _formula_markdown(text: str) -> str:
    text = text.strip()
    if text.startswith("$$") and text.endswith("$$"):
        inner = text[2:-2].strip()
        if "$" not in inner:
            return f"$$\n{inner}\n$$"
        return text
    if text.startswith("\\[") and text.endswith("\\]"):
        return f"$$\n{text[2:-2].strip()}\n$$"
    if re.search(r"\$[^$\n]+\$", text) or "\\begin{" in text:
        return text
    return f"$$\n{text}\n$$"


def layout_cells_to_markdown(cells: list[dict[str, Any]]) -> str:
    """Convert dots.ocr layout cells to page Markdown (no embedded image bytes)."""
    parts: list[str] = []
    for cell in cells:
        category = cell.get("category", "Text")
        text = cell.get("text", "")
        if category in {"Page-header", "Page-footer"}:
            # Keep headers/footers; downstream models may use page context.
            text = _clean_text(str(text)) if text else ""
            if text:
                parts.append(text)
            continue
        if category == "Picture":
            parts.append("<!-- picture omitted -->")
            continue
        if category == "Formula":
            parts.append(_formula_markdown(str(text)))
            continue
        if category == "Table":
            table_text = _clean_text(str(text))
            parts.append(table_text)
            continue
        cleaned = _clean_text(str(text)) if text else ""
        if cleaned:
            parts.append(cleaned)
    return "\n\n".join(parts).strip()


def _extract_json_payload(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        raise ValueError("empty model output")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Prefer fenced JSON or first array/object span.
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        return json.loads(fence.group(1).strip())
    start_candidates = [i for i in (raw.find("["), raw.find("{")) if i >= 0]
    if not start_candidates:
        raise ValueError("no JSON object/array found in model output")
    start = min(start_candidates)
    end_square = raw.rfind("]")
    end_curly = raw.rfind("}")
    end = max(end_square, end_curly)
    if end <= start:
        raise ValueError("incomplete JSON in model output")
    return json.loads(raw[start : end + 1])


def raw_model_output_to_markdown(raw: str) -> tuple[str, list[str]]:
    """Parse model output into Markdown. Returns (markdown, warnings)."""
    warnings: list[str] = []
    try:
        payload = _extract_json_payload(raw)
    except Exception:  # noqa: BLE001
        warnings.append("MODEL_OUTPUT_NOT_JSON")
        # Fall back to raw text so the page is not silently dropped.
        text = raw.strip()
        if not text:
            raise ValueError("model returned empty non-JSON output")
        return text, warnings

    cells: list[dict[str, Any]]
    if isinstance(payload, list):
        cells = [c for c in payload if isinstance(c, dict)]
    elif isinstance(payload, dict):
        if "cells" in payload and isinstance(payload["cells"], list):
            cells = [c for c in payload["cells"] if isinstance(c, dict)]
        elif "category" in payload:
            cells = [payload]
        else:
            # Unknown object shape — stringify carefully without inventing structure.
            warnings.append("UNEXPECTED_JSON_SHAPE")
            return json.dumps(payload, ensure_ascii=False), warnings
    else:
        warnings.append("UNEXPECTED_JSON_TYPE")
        return str(payload), warnings

    if not cells:
        warnings.append("EMPTY_LAYOUT_CELLS")
        return "", warnings
    return layout_cells_to_markdown(cells), warnings


def page_ends_with_table(markdown: str) -> bool:
    tail = markdown.rstrip()[-400:].lower() if markdown else ""
    return "</table>" in tail or tail.rstrip().endswith("|") or "<table" in tail


def page_starts_with_table(markdown: str) -> bool:
    head = markdown.lstrip()[:400].lower() if markdown else ""
    return head.startswith("<table") or head.startswith("|")


def stitch_document_markdown(pages: list[PageResult]) -> str:
    """Stitch page Markdown with explicit boundaries and table continuity cues."""
    blocks: list[str] = []
    previous_md: str | None = None
    for page in pages:
        page_md = page.markdown if page.markdown is not None else ""
        header = f"<!-- page: {page.page_number} -->"
        if (
            previous_md is not None
            and page_ends_with_table(previous_md)
            and page_starts_with_table(page_md)
        ):
            header = f"{header}\n\n<!-- table continues from previous page -->"
        elif previous_md is not None and page_ends_with_table(previous_md) and page_md:
            # Soft cue when the previous page ended mid-table-like content.
            if not page_starts_with_table(page_md):
                header = f"{header}\n\n<!-- previous page ended with a table; verify continuity -->"
        blocks.append(f"{header}\n\n{page_md}".rstrip())
        previous_md = page_md
    return "\n\n".join(blocks).strip() + ("\n" if blocks else "")


def infer_page_with_retry(
    engine: PageOCREngine,
    page: RenderedPage,
    *,
    retries: int = PAGE_RETRY_ATTEMPTS,
) -> PageInferenceOutcome:
    last_error: Exception | None = None
    warnings: list[str] = []
    attempts = retries + 1
    for attempt in range(attempts):
        try:
            raw = engine.infer_page(page.image, page_number=page.page_number)
            markdown, parse_warnings = raw_model_output_to_markdown(raw)
            warnings.extend(parse_warnings)
            if attempt > 0:
                warnings.append("RETRIED_ONCE")
            return PageInferenceOutcome(
                page_number=page.page_number,
                markdown=markdown,
                warnings=warnings,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning(
                "page_inference_failed page=%s attempt=%s",
                page.page_number,
                attempt + 1,
            )
    return PageInferenceOutcome(
        page_number=page.page_number,
        markdown=None,
        warnings=warnings,
        error=ErrorItem(
            "PAGE_INFERENCE_FAILED",
            f"Page {page.page_number} failed after retry: {type(last_error).__name__}",
        ),
    )


def process_document(
    document: DocumentInput,
    engine: PageOCREngine,
    *,
    dpi: int = DEFAULT_DPI,
    max_pages: int = DEFAULT_MAX_PAGES,
    allow_http_dev_fixture: bool = False,
    local_pdf_path: str | None = None,
) -> DocumentResult:
    """Download/validate/render one document and run page OCR with ordering preserved."""
    started = time.perf_counter()
    errors: list[ErrorItem] = []

    try:
        with temporary_workdir() as tmp:
            tmp_path = __import__("pathlib").Path(tmp)
            if local_pdf_path:
                pdf_path = __import__("pathlib").Path(local_pdf_path)
            else:
                pdf_path = download_pdf(
                    document.pdf_url,
                    dest_dir=tmp_path,
                    allow_http_dev_fixture=allow_http_dev_fixture,
                )
            validated = validate_and_open_pdf(pdf_path, max_pages=max_pages)
            pages_images = render_pages(validated.path, dpi=dpi)

            page_results: list[PageResult] = []
            for rendered in pages_images:
                outcome = infer_page_with_retry(engine, rendered)
                page_errors = [outcome.error] if outcome.error else []
                page_results.append(
                    PageResult(
                        page_number=outcome.page_number,
                        markdown=outcome.markdown,
                        warnings=list(outcome.warnings),
                        errors=page_errors,
                    )
                )

            succeeded_pages = [p for p in page_results if p.markdown is not None and not p.errors]
            failed_pages = [p for p in page_results if p.errors or p.markdown is None]

            if not succeeded_pages:
                status = DocumentStatus.FAILED
                errors.append(
                    ErrorItem("NO_PAGES_COMPLETED", "No pages completed successfully")
                )
                document_markdown = None
            elif failed_pages:
                status = DocumentStatus.PARTIAL
                errors.append(
                    ErrorItem(
                        "PARTIAL_PAGES",
                        f"{len(failed_pages)} page(s) failed after retry",
                    )
                )
                document_markdown = stitch_document_markdown(page_results)
            else:
                status = DocumentStatus.SUCCEEDED
                document_markdown = stitch_document_markdown(page_results)

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return DocumentResult(
                id=document.id,
                status=status,
                page_count=validated.page_count,
                document_markdown=document_markdown,
                pages=page_results,
                elapsed_ms=elapsed_ms,
                errors=errors,
            )
    except PdfError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return DocumentResult(
            id=document.id,
            status=DocumentStatus.FAILED,
            page_count=None,
            document_markdown=None,
            pages=[],
            elapsed_ms=elapsed_ms,
            errors=[exc.to_error_item()],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("document_failed id=%s", document.id)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return DocumentResult(
            id=document.id,
            status=DocumentStatus.FAILED,
            page_count=None,
            document_markdown=None,
            pages=[],
            elapsed_ms=elapsed_ms,
            errors=[ErrorItem("INTERNAL_ERROR", f"Unexpected failure: {type(exc).__name__}")],
        )


def process_batch(
    payload: dict[str, Any],
    engine: PageOCREngine,
    *,
    dpi: int = DEFAULT_DPI,
    max_pages: int = DEFAULT_MAX_PAGES,
    allow_http_dev_fixture: bool = False,
) -> dict[str, Any]:
    documents, error = parse_documents(payload)
    if error is not None or documents is None:
        # Request-level failure still returns a structured body without inventing document rows.
        return {
            "results": [],
            "errors": [error.to_dict() if error else {"code": "INVALID_REQUEST", "message": "Invalid request"}],
        }

    results: list[DocumentResult] = []
    for document in documents:
        results.append(
            process_document(
                document,
                engine,
                dpi=dpi,
                max_pages=max_pages,
                allow_http_dev_fixture=allow_http_dev_fixture,
            )
        )
    return results_payload(results)


class DotsOCRHFEngine:
    """Hugging Face transformers engine for rednote-hilab/dots.ocr using SDPA."""

    def __init__(
        self,
        model_id: str = MODEL_ID,
        revision: str = MODEL_REVISION,
        *,
        max_new_tokens: int = MAX_NEW_TOKENS,
        attn_implementation: str = "sdpa",
    ):
        self.model_id = model_id
        self.revision = revision
        self.max_new_tokens = max_new_tokens
        self.attn_implementation = attn_implementation
        self.model = None
        self.processor = None
        self.process_vision_info = None
        self.device = "cuda"

    def load(self) -> dict[str, str]:
        import torch
        from transformers import AutoModelForCausalLM, AutoProcessor
        from qwen_vl_utils import process_vision_info

        self.process_vision_info = process_vision_info
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        logger.info(
            "loading_model id=%s revision=%s attn=%s torch=%s cuda=%s",
            self.model_id,
            self.revision,
            self.attn_implementation,
            torch.__version__,
            torch.version.cuda,
        )
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            logger.info("gpu_name=%s", gpu_name)
        else:
            gpu_name = "cpu"
            logger.warning("CUDA unavailable; loading on CPU (development only)")

        dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            revision=self.revision,
            attn_implementation=self.attn_implementation,
            torch_dtype=dtype,
            device_map="auto" if self.device == "cuda" else None,
            trust_remote_code=True,
        )
        if self.device == "cpu":
            self.model = self.model.to(self.device)
        self.processor = AutoProcessor.from_pretrained(
            self.model_id,
            revision=self.revision,
            trust_remote_code=True,
            use_fast=True,
        )
        self.model.eval()
        return {
            "model_id": self.model_id,
            "model_revision": self.revision,
            "torch_version": torch.__version__,
            "cuda_version": str(torch.version.cuda),
            "gpu_name": gpu_name,
            "attn_implementation": self.attn_implementation,
        }

    def infer_page(
        self,
        image: Any,
        prompt: str = LAYOUT_PROMPT,
        *,
        page_number: int | None = None,
    ) -> str:
        import torch

        del page_number  # Ordering is handled by the caller; model is page-local.
        if self.model is None or self.processor is None or self.process_vision_info is None:
            raise RuntimeError("DotsOCRHFEngine.load() must be called before infer_page()")

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        text = self.processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        image_inputs, video_inputs = self.process_vision_info(messages)
        inputs = self.processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        )
        inputs = inputs.to(self.model.device)

        with torch.inference_mode():
            generated_ids = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
            )
        trimmed = [
            out_ids[len(in_ids) :]
            for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        decoded = self.processor.batch_decode(
            trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )
        return decoded[0]
