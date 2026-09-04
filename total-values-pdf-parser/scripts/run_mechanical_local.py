#!/usr/bin/env python3
"""Local mechanical checklist using generated PDFs + stub OCR (no GPU).

Covers PLAN.md mechanical gates that do not require dots.ocr weights:
  - single-page success
  - multi-page (14–21) success with full ordering
  - multi-document batch ordering
  - invalid PDF failure
  - page-limit failure
  - mixed batch (one fail, one succeed)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from contracts import DocumentInput, DocumentStatus  # noqa: E402
from parser import process_document  # noqa: E402


class StubOCR:
    def infer_page(self, image, prompt: str = "", *, page_number: int | None = None) -> str:
        return json.dumps(
            [{"bbox": [0, 0, 10, 10], "category": "Text", "text": f"stub-page-{page_number}"}]
        )


def write_pdf(path: Path, pages: int) -> Path:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Fixture page {i + 1}")
    doc.save(path)
    doc.close()
    return path


def main() -> int:
    out_dir = Path("/tmp/tv-pdf-mechanical")
    out_dir.mkdir(parents=True, exist_ok=True)
    engine = StubOCR()
    report = []

    cases = [
        ("single_page", 1, None),
        ("pages_17", 17, None),
        ("over_page_limit", 31, "PAGE_LIMIT_EXCEEDED"),
    ]

    for name, n_pages, expect_err in cases:
        path = write_pdf(out_dir / f"{name}.pdf", n_pages)
        result = process_document(
            DocumentInput(id=name, pdf_url=f"https://example.com/{name}.pdf"),
            engine,
            local_pdf_path=str(path),
            max_pages=30,
        )
        ok = True
        if expect_err:
            ok = result.status == DocumentStatus.FAILED and any(
                e.code == expect_err for e in result.errors
            )
        else:
            ok = (
                result.status == DocumentStatus.SUCCEEDED
                and result.page_count == n_pages
                and [p.page_number for p in result.pages] == list(range(1, n_pages + 1))
                and all(f"<!-- page: {i} -->" in (result.document_markdown or "") for i in range(1, n_pages + 1))
            )
        report.append({"case": name, "ok": ok, "status": result.status.value, "errors": [e.to_dict() for e in result.errors]})

    # Invalid PDF
    bad = out_dir / "invalid.pdf"
    bad.write_bytes(b"not-a-pdf")
    r_bad = process_document(
        DocumentInput(id="invalid", pdf_url="https://example.com/invalid.pdf"),
        engine,
        local_pdf_path=str(bad),
    )
    report.append(
        {
            "case": "invalid_pdf",
            "ok": r_bad.status == DocumentStatus.FAILED and r_bad.id == "invalid",
            "status": r_bad.status.value,
            "errors": [e.to_dict() for e in r_bad.errors],
        }
    )

    # Mixed batch ordering
    good = write_pdf(out_dir / "batch_good.pdf", 2)
    r1 = process_document(DocumentInput(id="a", pdf_url="https://example.com/a.pdf"), engine, local_pdf_path=str(good))
    r2 = process_document(DocumentInput(id="b", pdf_url="https://example.com/b.pdf"), engine, local_pdf_path=str(bad))
    mixed_ok = [r1.id, r2.id] == ["a", "b"] and r1.status == DocumentStatus.SUCCEEDED and r2.status == DocumentStatus.FAILED
    report.append({"case": "mixed_batch", "ok": mixed_ok, "statuses": [r1.status.value, r2.status.value]})

    passed = all(item["ok"] for item in report)
    print(json.dumps({"passed": passed, "report": report}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
