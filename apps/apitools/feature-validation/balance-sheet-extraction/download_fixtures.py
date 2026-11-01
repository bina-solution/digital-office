#!/usr/bin/env python3
"""Download balance-sheet fixture documents from Google Drive."""

import json
import re
import os
import sys
from pathlib import Path

import gdown

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DOCUMENTS_DIR = FIXTURES_DIR / "documents"
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

MIME_TO_EXT = {
    "pdf": ".pdf",
    "xlsx": ".xlsx",
    "jpeg": ".jpg",
    "docs": ".pdf",  # Google Docs exported as PDF
}


def extract_file_id(url: str) -> str:
    """Extract GDrive file/doc ID from various URL formats."""
    # Google Sheets: https://docs.google.com/spreadsheets/d/ID
    m = re.search(r'spreadsheets/d/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    # Google Docs: https://docs.google.com/document/d/ID
    m = re.search(r'document/d/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    # Regular GDrive file: https://drive.google.com/file/d/ID
    m = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    return url


def is_google_native(url: str) -> str | None:
    """Return 'sheets' or 'docs' if URL is a Google native format."""
    if 'docs.google.com/spreadsheets' in url:
        return 'sheets'
    if 'docs.google.com/document' in url:
        return 'docs'
    return None


def download_case(case: dict) -> str | None:
    """Download a single case document. Returns local filename or None."""
    name = case["name"]
    url = case["gdrive_link"]
    mime = case.get("mime_type", "pdf")
    ext = MIME_TO_EXT.get(mime, ".pdf")
    
    out_path = DOCUMENTS_DIR / f"{name}{ext}"
    
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"  {name}: already exists ({out_path.stat().st_size} bytes)")
        return f"fixtures/documents/{name}{ext}"

    file_id = extract_file_id(url)
    native = is_google_native(url)
    
    try:
        if native == 'sheets':
            # Export Google Sheet as xlsx
            export_url = f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx"
            print(f"  {name}: exporting Google Sheet...")
            gdown.download(export_url, str(out_path), quiet=True, fuzzy=False)
        elif native == 'docs' or mime == 'docs':
            # Export Google Doc as PDF
            export_url = f"https://docs.google.com/document/d/{file_id}/export?format=pdf"
            print(f"  {name}: exporting Google Doc as PDF...")
            gdown.download(export_url, str(out_path), quiet=True, fuzzy=False)
        else:
            # Regular file download
            gdrive_url = f"https://drive.google.com/uc?id={file_id}"
            print(f"  {name}: downloading file ({mime})...")
            gdown.download(gdrive_url, str(out_path), quiet=True, fuzzy=False)
        
        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"  {name}: OK ({out_path.stat().st_size} bytes)")
            return f"fixtures/documents/{name}{ext}"
        else:
            print(f"  {name}: FAILED (empty or missing)")
            if out_path.exists():
                out_path.unlink()
            return None
    except Exception as e:
        print(f"  {name}: ERROR - {e}")
        if out_path.exists():
            out_path.unlink()
        return None


def main():
    fixtures_path = FIXTURES_DIR / "fixtures.json"
    cases = json.loads(fixtures_path.read_text())
    
    print(f"Downloading {len(cases)} documents to {DOCUMENTS_DIR}\n")
    
    results = {}
    for case in cases:
        local_path = download_case(case)
        results[case["name"]] = local_path
    
    print(f"\nResults:")
    ok = sum(1 for v in results.values() if v)
    print(f"  {ok}/{len(results)} downloaded successfully")
    for name, path in results.items():
        status = "OK" if path else "FAILED"
        print(f"  {name}: {status}")
    
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
