"""Shared request/response types for the Total Values PDF parser."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class DocumentStatus(str, Enum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass
class ErrorItem:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass
class PageResult:
    page_number: int
    markdown: str | None
    warnings: list[str] = field(default_factory=list)
    errors: list[ErrorItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "markdown": self.markdown,
            "warnings": list(self.warnings),
            "errors": [e.to_dict() for e in self.errors],
        }


@dataclass
class DocumentResult:
    id: str
    status: DocumentStatus
    page_count: int | None
    document_markdown: str | None
    pages: list[PageResult]
    elapsed_ms: int
    errors: list[ErrorItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status.value,
            "page_count": self.page_count,
            "document_markdown": self.document_markdown,
            "pages": [p.to_dict() for p in self.pages],
            "elapsed_ms": self.elapsed_ms,
            "errors": [e.to_dict() for e in self.errors],
        }


@dataclass
class DocumentInput:
    id: str
    pdf_url: str


def parse_documents(payload: dict[str, Any]) -> tuple[list[DocumentInput] | None, ErrorItem | None]:
    """Validate top-level request shape. Returns (documents, error)."""
    if not isinstance(payload, dict):
        return None, ErrorItem("INVALID_REQUEST", "Request body must be a JSON object")

    if "prompt" in payload or "schema" in payload or "response_schema" in payload:
        return None, ErrorItem(
            "UNSUPPORTED_FIELD",
            "This endpoint does not accept extraction prompts or response schemas",
        )

    documents = payload.get("documents")
    if not isinstance(documents, list) or len(documents) == 0:
        return None, ErrorItem("INVALID_REQUEST", "`documents` must be a non-empty array")

    # Temporary safety ceiling only — not a measured production limit (see PLAN.md).
    temporary_safety_ceiling = payload.get("_temporary_safety_ceiling", 50)
    if len(documents) > temporary_safety_ceiling:
        return None, ErrorItem(
            "BATCH_TOO_LARGE",
            f"Batch size {len(documents)} exceeds temporary safety ceiling "
            f"{temporary_safety_ceiling}; set production max after first deployment measurement",
        )

    seen_ids: set[str] = set()
    parsed: list[DocumentInput] = []
    for idx, item in enumerate(documents):
        if not isinstance(item, dict):
            return None, ErrorItem("INVALID_REQUEST", f"documents[{idx}] must be an object")
        doc_id = item.get("id")
        pdf_url = item.get("pdf_url")
        if not isinstance(doc_id, str) or not doc_id.strip():
            return None, ErrorItem("INVALID_REQUEST", f"documents[{idx}].id must be a non-empty string")
        if doc_id in seen_ids:
            return None, ErrorItem("INVALID_REQUEST", f"Duplicate document id: {doc_id}")
        if not isinstance(pdf_url, str) or not pdf_url.strip():
            return None, ErrorItem(
                "INVALID_REQUEST",
                f"documents[{idx}].pdf_url must be a non-empty string",
            )
        if "pdf_base64" in item or "content_base64" in item:
            return None, ErrorItem(
                "UNSUPPORTED_FIELD",
                "Base64 upload is not enabled in v1; provide signed HTTPS pdf_url values",
            )
        seen_ids.add(doc_id)
        parsed.append(DocumentInput(id=doc_id, pdf_url=pdf_url.strip()))

    return parsed, None


def results_payload(results: list[DocumentResult]) -> dict[str, Any]:
    return {"results": [r.to_dict() for r in results]}


def dataclass_json(obj: Any) -> Any:
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if isinstance(obj, Enum):
        return obj.value
    return asdict(obj)
