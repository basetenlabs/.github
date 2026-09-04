"""Truss model entrypoint: batch PDF URL → page-aware Markdown."""

from __future__ import annotations

import logging
import os
from typing import Any

from contracts import ErrorItem
from parser import DotsOCRHFEngine, MODEL_ID, MODEL_REVISION, process_batch
from pdf import DEFAULT_DPI, DEFAULT_MAX_PAGES

logger = logging.getLogger("total_values_pdf_parser")
logging.basicConfig(level=logging.INFO)


class Model:
    def __init__(self, **kwargs: Any):
        self._data_dir = kwargs.get("data_dir")
        self._config = kwargs.get("config") or {}
        self._secrets = kwargs.get("secrets") or {}
        self.engine: DotsOCRHFEngine | None = None
        self.dpi = int(os.environ.get("PDF_RENDER_DPI", DEFAULT_DPI))
        self.max_pages = int(os.environ.get("PDF_MAX_PAGES", DEFAULT_MAX_PAGES))
        self.allow_http_dev_fixture = os.environ.get("ALLOW_HTTP_DEV_FIXTURE", "").lower() in {
            "1",
            "true",
            "yes",
        }

    def load(self) -> None:
        """Load dots.ocr and log runtime identity (never log document contents)."""
        attn = os.environ.get("DOTS_OCR_ATTN", "sdpa")
        self.engine = DotsOCRHFEngine(
            model_id=os.environ.get("DOTS_OCR_MODEL_ID", MODEL_ID),
            revision=os.environ.get("DOTS_OCR_MODEL_REVISION", MODEL_REVISION),
            attn_implementation=attn,
        )
        meta = self.engine.load()
        logger.info(
            "startup_ready model_revision=%s torch=%s cuda=%s gpu=%s attn=%s",
            meta.get("model_revision"),
            meta.get("torch_version"),
            meta.get("cuda_version"),
            meta.get("gpu_name"),
            meta.get("attn_implementation"),
        )

    def predict(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.engine is None:
            return {
                "results": [],
                "errors": [ErrorItem("MODEL_NOT_LOADED", "Model.load() has not completed").to_dict()],
            }
        if not isinstance(request, dict):
            return {
                "results": [],
                "errors": [ErrorItem("INVALID_REQUEST", "Request body must be a JSON object").to_dict()],
            }

        # Reject out-of-scope extraction/selection fields early.
        return process_batch(
            request,
            self.engine,
            dpi=self.dpi,
            max_pages=self.max_pages,
            allow_http_dev_fixture=self.allow_http_dev_fixture,
        )
