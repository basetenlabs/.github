# Total Values evaluation inputs

This directory holds **authorized** evaluation fixtures for the PDF parser.

## Expected contents

| Path | Purpose |
| --- | --- |
| `eval/manifest.jsonl` | Authorized document IDs, HTTPS PDF URLs, expected page counts, and notes |
| `eval/expected/` | Optional approved selection/extraction baselines (gitignored if sensitive) |

## Manifest schema (one JSON object per line)

```json
{
  "id": "paper-001",
  "pdf_url": "https://example.com/signed/paper-001.pdf",
  "expected_page_count": 17,
  "selection_notes": "Representation currently sent into the selection model",
  "extraction_notes": "Representation currently sent into the extraction model",
  "downstream_eval": null
}
```

## Status

Authorized Total Values PDF URLs, Gemini baselines, and deterministic expected extraction values are **not present** in this workspace. See root `BLOCKERS.md`.

Do not commit customer PDFs, private URLs, credentials, or parsed document contents.
