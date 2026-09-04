"""PDF validation and rendering tests (no GPU required)."""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from pdf import (  # noqa: E402
    PdfError,
    render_pages,
    validate_and_open_pdf,
    validate_pdf_url,
)


def _write_pdf(path: Path, page_count: int = 1, text: str = "Hello") -> Path:
    doc = fitz.open()
    for i in range(page_count):
        page = doc.new_page()
        page.insert_text((72, 72), f"{text} page {i + 1}")
    doc.save(path)
    doc.close()
    return path


def test_https_required(tmp_path: Path):
    with pytest.raises(PdfError) as exc:
        validate_pdf_url("http://example.com/a.pdf")
    assert exc.value.code == "INVALID_URL"


def test_localhost_blocked():
    with pytest.raises(PdfError) as exc:
        validate_pdf_url("https://localhost/a.pdf")
    assert exc.value.code == "UNSAFE_URL"


def test_validate_and_render_single_page(tmp_path: Path):
    pdf_path = _write_pdf(tmp_path / "one.pdf", page_count=1)
    validated = validate_and_open_pdf(pdf_path, max_pages=30)
    assert validated.page_count == 1
    pages = render_pages(pdf_path, dpi=72)
    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert pages[0].image.size[0] > 0


def test_render_preserves_page_order(tmp_path: Path):
    pdf_path = _write_pdf(tmp_path / "multi.pdf", page_count=3)
    pages = render_pages(pdf_path, dpi=72)
    assert [p.page_number for p in pages] == [1, 2, 3]


def test_page_limit_enforced(tmp_path: Path):
    pdf_path = _write_pdf(tmp_path / "long.pdf", page_count=5)
    with pytest.raises(PdfError) as exc:
        validate_and_open_pdf(pdf_path, max_pages=3)
    assert exc.value.code == "PAGE_LIMIT_EXCEEDED"


def test_invalid_pdf_bytes(tmp_path: Path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not-a-pdf")
    with pytest.raises(PdfError) as exc:
        validate_and_open_pdf(bad)
    assert exc.value.code == "INVALID_PDF"


def test_encrypted_pdf_rejected(tmp_path: Path):
    plain = tmp_path / "plain.pdf"
    _write_pdf(plain, page_count=1)
    encrypted = tmp_path / "enc.pdf"
    doc = fitz.open(plain)
    # PyMuPDF encryption API
    doc.save(
        encrypted,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        user_pw="secret",
        owner_pw="owner",
    )
    doc.close()
    with pytest.raises(PdfError) as exc:
        validate_and_open_pdf(encrypted)
    assert exc.value.code == "ENCRYPTED_PDF"
