#!/usr/bin/env python3
"""Downstream evaluation harness stub for Total Values selection/extraction.

This script does **not** implement selection or extraction. It only:
1. Reads a manifest of authorized documents.
2. Calls the PDF parser endpoint (or loads local parser results).
3. Documents how to feed `document_markdown` into existing downstream models.

Authorized customer manifests, baselines, and downstream endpoints are not
present in this workspace by default. See BLOCKERS.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_manifest(path: Path) -> list[dict]:
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("eval/manifest.example.jsonl"),
        help="JSONL manifest of document ids/urls",
    )
    parser.add_argument(
        "--parser-url",
        default=None,
        help="Deployed parser predict URL (required for live calls)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Baseten API key (or set BASETEN_API_KEY); never commit secrets",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("../artifacts/parser_results.json"),
        help="Where to write parser outputs (gitignored artifacts/)",
    )
    args = parser.parse_args()

    if not args.manifest.exists():
        print(f"Manifest not found: {args.manifest}", file=sys.stderr)
        print("Authorized Total Values inputs are missing; see BLOCKERS.md", file=sys.stderr)
        return 2

    rows = load_manifest(args.manifest)
    if not rows:
        print("Manifest is empty; nothing to evaluate.", file=sys.stderr)
        return 2

    if args.parser_url is None:
        print("No --parser-url provided. Dry-run only.")
        print(f"Loaded {len(rows)} manifest row(s) from {args.manifest}")
        print(
            "Next steps after deployment:\n"
            "  1. POST documents to the parser endpoint.\n"
            "  2. Feed each document_markdown into Total Values' existing selection model unchanged.\n"
            "  3. For selected docs, feed the same markdown into the existing extraction model unchanged.\n"
            "  4. Compare selection decisions and deterministic extracted numbers to baselines.\n"
            "Do not modify downstream prompts/schemas from this harness."
        )
        return 0

    api_key = args.api_key or __import__("os").environ.get("BASETEN_API_KEY")
    if not api_key:
        print("BASETEN_API_KEY / --api-key missing; refusing to invent credentials.", file=sys.stderr)
        return 2

    try:
        import requests
    except ImportError as exc:
        raise SystemExit("Install requests to call the live endpoint") from exc

    payload = {
        "documents": [
            {"id": row["id"], "pdf_url": row["pdf_url"]}
            for row in rows
            if "id" in row and "pdf_url" in row
        ]
    }
    response = requests.post(
        args.parser_url,
        headers={"Authorization": f"Api-Key {api_key}"},
        json=payload,
        timeout=60 * 60,
    )
    response.raise_for_status()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(response.json(), indent=2), encoding="utf-8")
    print(f"Wrote parser results to {args.out}")
    print("Downstream selection/extraction comparison must use Total Values' existing models.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
