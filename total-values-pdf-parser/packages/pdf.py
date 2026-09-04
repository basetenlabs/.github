"""PDF download, validation, and page rendering helpers."""

from __future__ import annotations

import ipaddress
import os
import socket
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from contracts import ErrorItem

# Temporary operational limits (see PLAN.md). Page limit is intentional; batch max is TBD.
DEFAULT_DPI = 200
DEFAULT_MAX_PAGES = 30
DEFAULT_MAX_BYTES = 50 * 1024 * 1024  # 50 MiB temporary download cap
DEFAULT_TIMEOUT_SEC = 60
PDF_MAGIC = b"%PDF"


@dataclass
class RenderedPage:
    page_number: int  # 1-indexed
    image: object  # PIL.Image.Image


@dataclass
class ValidatedPdf:
    path: Path
    page_count: int


class PdfError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_error_item(self) -> ErrorItem:
        return ErrorItem(self.code, self.message)


def _hostname_resolves_to_public(hostname: str) -> None:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise PdfError("DOWNLOAD_FAILED", f"Could not resolve host: {hostname}") from exc

    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise PdfError(
                "UNSAFE_URL",
                "PDF URL resolves to a private or non-public network address",
            )


def validate_pdf_url(url: str, *, allow_http_dev_fixture: bool = False) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise PdfError("INVALID_URL", "pdf_url must use https (or approved http fixture)")
    if parsed.scheme == "http" and not allow_http_dev_fixture:
        raise PdfError("INVALID_URL", "pdf_url must use HTTPS")
    if not parsed.hostname:
        raise PdfError("INVALID_URL", "pdf_url is missing a hostname")
    host = parsed.hostname.lower()
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        raise PdfError("UNSAFE_URL", "Local or metadata hostnames are not allowed")
    _hostname_resolves_to_public(host)


def download_pdf(
    url: str,
    *,
    dest_dir: Path,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    max_bytes: int = DEFAULT_MAX_BYTES,
    allow_http_dev_fixture: bool = False,
    opener: Callable[..., object] | None = None,
) -> Path:
    """Download a PDF to dest_dir. Caller must delete the file."""
    validate_pdf_url(url, allow_http_dev_fixture=allow_http_dev_fixture)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"doc-{int(time.time() * 1000)}-{os.getpid()}.pdf"

    request = Request(
        url,
        headers={"User-Agent": "total-values-pdf-parser/0.1"},
        method="GET",
    )
    open_fn = opener or urlopen
    try:
        with open_fn(request, timeout=timeout_sec) as response:  # type: ignore[arg-type]
            final_url = getattr(response, "geturl", lambda: url)()
            if final_url and final_url != url:
                # Re-validate redirect target (blocks open redirects into private nets).
                validate_pdf_url(final_url, allow_http_dev_fixture=allow_http_dev_fixture)

            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(1024 * 64)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise PdfError(
                        "FILE_TOO_LARGE",
                        f"PDF exceeds maximum allowed size of {max_bytes} bytes",
                    )
                chunks.append(chunk)
            data = b"".join(chunks)
    except PdfError:
        raise
    except HTTPError as exc:
        raise PdfError("DOWNLOAD_FAILED", f"HTTP error downloading PDF: {exc.code}") from exc
    except URLError as exc:
        raise PdfError("DOWNLOAD_FAILED", f"Network error downloading PDF: {exc.reason}") from exc
    except TimeoutError as exc:
        raise PdfError("DOWNLOAD_TIMEOUT", "Timed out while downloading PDF") from exc
    except Exception as exc:  # noqa: BLE001 - map unknown download failures
        raise PdfError("DOWNLOAD_FAILED", "Failed to download PDF") from exc

    if not data.startswith(PDF_MAGIC):
        raise PdfError("INVALID_PDF", "Downloaded bytes do not start with PDF magic header")

    dest.write_bytes(data)
    return dest


def validate_and_open_pdf(path: Path, *, max_pages: int = DEFAULT_MAX_PAGES) -> ValidatedPdf:
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001
        raise PdfError("INVALID_PDF", "The document could not be opened as a PDF") from exc

    try:
        if doc.is_encrypted:
            # Try empty password; still reject if encryption remains.
            if not doc.authenticate(""):
                raise PdfError("ENCRYPTED_PDF", "Encrypted PDFs are not supported")
            if doc.is_encrypted:
                raise PdfError("ENCRYPTED_PDF", "Encrypted PDFs are not supported")

        page_count = doc.page_count
        if page_count <= 0:
            raise PdfError("INVALID_PDF", "PDF contains no pages")
        if page_count > max_pages:
            raise PdfError(
                "PAGE_LIMIT_EXCEEDED",
                f"PDF has {page_count} pages; temporary limit is {max_pages}",
            )
        return ValidatedPdf(path=path, page_count=page_count)
    finally:
        doc.close()


def render_pages(
    path: Path,
    *,
    dpi: int = DEFAULT_DPI,
    page_numbers: list[int] | None = None,
) -> list[RenderedPage]:
    """Render PDF pages to RGB PIL images. page_numbers are 1-indexed."""
    import fitz
    from PIL import Image

    rendered: list[RenderedPage] = []
    with fitz.open(path) as doc:
        indices = (
            [n - 1 for n in page_numbers]
            if page_numbers is not None
            else list(range(doc.page_count))
        )
        for idx in indices:
            if idx < 0 or idx >= doc.page_count:
                raise PdfError("INVALID_PAGE", f"Page number out of range: {idx + 1}")
            page = doc[idx]
            mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            # Guard against pathological page sizes.
            if pix.width > 4500 or pix.height > 4500:
                pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            rendered.append(RenderedPage(page_number=idx + 1, image=image))
    return rendered


def temporary_workdir() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory(prefix="tv-pdf-parser-")
