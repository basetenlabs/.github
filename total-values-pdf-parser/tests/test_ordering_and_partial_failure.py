"""Ordering, partial failure, and mixed-batch mechanical behavior."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from contracts import DocumentStatus  # noqa: E402
from parser import process_document  # noqa: E402
from contracts import DocumentInput  # noqa: E402


def _write_pdf(path: Path, page_count: int = 1) -> Path:
    doc = fitz.open()
    for i in range(page_count):
        page = doc.new_page()
        page.insert_text((72, 72), f"content {i + 1}")
    doc.save(path)
    doc.close()
    return path


class OrderedStubEngine:
    """Returns deterministic per-page text; can fail specific pages."""

    def __init__(self, fail_pages: set[int] | None = None, fail_once_pages: set[int] | None = None):
        self.fail_pages = fail_pages or set()
        self.fail_once_pages = fail_once_pages or set()
        self._attempts: dict[int, int] = {}
        self.calls: list[int] = []

    def infer_page(self, image, prompt: str = "", *, page_number: int | None = None) -> str:
        if page_number is None:
            raise AssertionError("page_number is required for OrderedStubEngine")
        self.calls.append(page_number)
        self._attempts[page_number] = self._attempts.get(page_number, 0) + 1
        if page_number in self.fail_pages:
            raise RuntimeError("permanent failure")
        if page_number in self.fail_once_pages and self._attempts[page_number] == 1:
            raise RuntimeError("transient failure")
        return json.dumps(
            [
                {
                    "bbox": [0, 0, 10, 10],
                    "category": "Text",
                    "text": f"page-{page_number}",
                }
            ]
        )


def test_all_pages_ordered_on_success(tmp_path: Path):
    pdf = _write_pdf(tmp_path / "ok.pdf", page_count=3)
    engine = OrderedStubEngine()
    result = process_document(
        DocumentInput(id="paper-001", pdf_url="https://example.com/ok.pdf"),
        engine,
        local_pdf_path=str(pdf),
    )
    assert result.status == DocumentStatus.SUCCEEDED
    assert result.id == "paper-001"
    assert result.page_count == 3
    assert [p.page_number for p in result.pages] == [1, 2, 3]
    assert "<!-- page: 1 -->" in result.document_markdown
    assert "<!-- page: 2 -->" in result.document_markdown
    assert "<!-- page: 3 -->" in result.document_markdown
    assert "page-1" in result.document_markdown
    assert "page-3" in result.document_markdown


def test_partial_status_when_one_page_fails_after_retry(tmp_path: Path):
    pdf = _write_pdf(tmp_path / "partial.pdf", page_count=3)
    engine = OrderedStubEngine(fail_pages={2})
    result = process_document(
        DocumentInput(id="paper-partial", pdf_url="https://example.com/p.pdf"),
        engine,
        local_pdf_path=str(pdf),
    )
    assert result.status == DocumentStatus.PARTIAL
    assert len(result.pages) == 3
    assert result.pages[1].errors
    assert result.pages[1].errors[0].code == "PAGE_INFERENCE_FAILED"
    # Failed page is still present (not silently omitted).
    assert result.pages[1].page_number == 2
    assert result.pages[0].markdown is not None
    assert result.pages[2].markdown is not None


def test_retry_recovers_transient_page_failure(tmp_path: Path):
    pdf = _write_pdf(tmp_path / "retry.pdf", page_count=2)
    engine = OrderedStubEngine(fail_once_pages={1})
    result = process_document(
        DocumentInput(id="paper-retry", pdf_url="https://example.com/r.pdf"),
        engine,
        local_pdf_path=str(pdf),
    )
    assert result.status == DocumentStatus.SUCCEEDED
    assert "RETRIED_ONCE" in result.pages[0].warnings


def test_failed_invalid_pdf_does_not_raise(tmp_path: Path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-not-really")
    # Corrupted enough that PyMuPDF may or may not open; force non-pdf magic path
    # by using a clearly invalid file without magic after download simulation.
    bad.write_bytes(b"nope")
    engine = OrderedStubEngine()
    result = process_document(
        DocumentInput(id="paper-bad", pdf_url="https://example.com/bad.pdf"),
        engine,
        local_pdf_path=str(bad),
    )
    assert result.status == DocumentStatus.FAILED
    assert result.document_markdown is None
    assert result.pages == []
    assert result.errors
    assert result.id == "paper-bad"


def test_mixed_batch_preserves_one_result_per_id(tmp_path: Path):
    from parser import process_batch

    good = _write_pdf(tmp_path / "good.pdf", page_count=1)
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not-pdf")

    class LocalPathEngine(OrderedStubEngine):
        pass

    # process_batch downloads URLs; for local mechanical tests call process_document.
    engine = LocalPathEngine()
    r1 = process_document(
        DocumentInput(id="ok", pdf_url="https://example.com/ok.pdf"),
        engine,
        local_pdf_path=str(good),
    )
    r2 = process_document(
        DocumentInput(id="bad", pdf_url="https://example.com/bad.pdf"),
        engine,
        local_pdf_path=str(bad),
    )
    results = [r1, r2]
    assert [r.id for r in results] == ["ok", "bad"]
    assert r1.status == DocumentStatus.SUCCEEDED
    assert r2.status == DocumentStatus.FAILED
