"""Input validation for the batch PDF parser API contract."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from contracts import PageResult, parse_documents  # noqa: E402
from parser import process_batch, stitch_document_markdown  # noqa: E402


class StubEngine:
    def infer_page(self, image, prompt: str = "", *, page_number: int | None = None) -> str:
        return '[{"bbox":[0,0,10,10],"category":"Text","text":"hello"}]'


def test_requires_documents_array():
    docs, err = parse_documents({})
    assert docs is None
    assert err is not None
    assert err.code == "INVALID_REQUEST"


def test_rejects_prompt_and_schema_fields():
    docs, err = parse_documents(
        {
            "documents": [{"id": "a", "pdf_url": "https://example.com/a.pdf"}],
            "prompt": "extract fields",
        }
    )
    assert docs is None
    assert err.code == "UNSUPPORTED_FIELD"


def test_rejects_base64_upload_in_v1():
    docs, err = parse_documents(
        {
            "documents": [
                {
                    "id": "a",
                    "pdf_url": "https://example.com/a.pdf",
                    "pdf_base64": "aaa",
                }
            ]
        }
    )
    assert docs is None
    assert err.code == "UNSUPPORTED_FIELD"


def test_preserves_input_order_and_unique_ids():
    docs, err = parse_documents(
        {
            "documents": [
                {"id": "paper-002", "pdf_url": "https://example.com/2.pdf"},
                {"id": "paper-001", "pdf_url": "https://example.com/1.pdf"},
            ]
        }
    )
    assert err is None
    assert [d.id for d in docs] == ["paper-002", "paper-001"]


def test_duplicate_ids_rejected():
    docs, err = parse_documents(
        {
            "documents": [
                {"id": "same", "pdf_url": "https://example.com/1.pdf"},
                {"id": "same", "pdf_url": "https://example.com/2.pdf"},
            ]
        }
    )
    assert docs is None
    assert err.code == "INVALID_REQUEST"


def test_request_level_error_returns_structured_body():
    out = process_batch({"documents": []}, StubEngine())
    assert out["results"] == []
    assert out["errors"][0]["code"] == "INVALID_REQUEST"


def test_page_marker_stitching_and_table_continuity():
    pages = [
        PageResult(page_number=1, markdown="<table><tr><td>A</td></tr>"),
        PageResult(page_number=2, markdown="<table><tr><td>B</td></tr></table>"),
    ]
    md = stitch_document_markdown(pages)
    assert "<!-- page: 1 -->" in md
    assert "<!-- page: 2 -->" in md
    assert "table continues from previous page" in md
