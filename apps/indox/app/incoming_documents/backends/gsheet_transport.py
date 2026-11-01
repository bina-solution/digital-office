"""Transport seam for the Google Sheets / Drive APIs.

`GSheetTransport` is the minimal surface area `GSheetRepo` needs. We
provide two implementations:

* `GoogleApiTransport` — wraps `google-api-python-client` + `google-auth`.
  Heavy import; only loaded when actually instantiated.
* `FakeGSheetTransport` — in-memory implementation used by unit tests so
  the repo can be exercised end-to-end without hitting Google.

This split lets us reach >85% coverage without any live network calls.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Protocol


# ---------- Protocol ----------


class GSheetTransport(Protocol):
    # Spreadsheet container
    def spreadsheet_create(self, title: str) -> dict[str, Any]: ...
    def spreadsheet_get(self, spreadsheet_id: str) -> dict[str, Any]: ...
    def spreadsheet_batch_update(
        self, spreadsheet_id: str, requests: list[dict[str, Any]]
    ) -> dict[str, Any]: ...

    # Cell values
    def values_get(
        self, spreadsheet_id: str, range_: str
    ) -> dict[str, Any]: ...
    def values_update(
        self, spreadsheet_id: str, range_: str, values: list[list[Any]]
    ) -> dict[str, Any]: ...
    def values_batch_update(
        self, spreadsheet_id: str, data: list[dict[str, Any]]
    ) -> dict[str, Any]: ...
    def values_append(
        self, spreadsheet_id: str, range_: str, values: list[list[Any]]
    ) -> dict[str, Any]: ...

    # Drive
    def drive_share(
        self, spreadsheet_id: str, email: str, role: str = "writer"
    ) -> dict[str, Any]: ...
    def drive_delete(self, spreadsheet_id: str) -> None: ...


# ---------- Fake (in-memory) ----------


@dataclass
class _FakeSheet:
    title: str
    sheet_id: int
    values: list[list[Any]] = field(default_factory=list)


@dataclass
class _FakeSpreadsheet:
    spreadsheet_id: str
    title: str
    sheets: dict[str, _FakeSheet] = field(default_factory=dict)
    permissions: list[dict[str, str]] = field(default_factory=list)


class FakeGSheetTransport:
    """In-memory implementation of `GSheetTransport` for unit tests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._spreadsheets: dict[str, _FakeSpreadsheet] = {}
        self._next_sheet_id = 100
        self._next_spreadsheet_id = 1

    # ----- helpers -----
    def _new_id(self) -> str:
        sid = f"fake-ss-{self._next_spreadsheet_id:04d}"
        self._next_spreadsheet_id += 1
        return sid

    def _new_sheet_id(self) -> int:
        sid = self._next_sheet_id
        self._next_sheet_id += 1
        return sid

    def _get(self, spreadsheet_id: str) -> _FakeSpreadsheet:
        if spreadsheet_id not in self._spreadsheets:
            raise KeyError(f"spreadsheet '{spreadsheet_id}' not found")
        return self._spreadsheets[spreadsheet_id]

    @staticmethod
    def _split_range(range_: str) -> tuple[str, Optional[str]]:
        """Parse e.g. ``'Sheet1!A1:C10'`` or ``'Sheet1'`` -> (sheet, a1)."""
        if "!" in range_:
            sheet, a1 = range_.split("!", 1)
            return sheet.strip("'"), a1
        return range_.strip("'"), None

    @staticmethod
    def _a1_to_indices(a1: str) -> tuple[int, int, int, int]:
        """Return (start_row, start_col, end_row, end_col) 0-indexed.

        Supports A1:C10, A:C, 1:5. End is inclusive. Missing parts are
        clamped to "everything".
        """
        import re

        def split(cell: str) -> tuple[Optional[int], Optional[int]]:
            m = re.match(r"^([A-Za-z]*)(\d*)$", cell)
            if not m:
                return None, None
            col_s, row_s = m.group(1), m.group(2)
            col = None
            if col_s:
                col = 0
                for ch in col_s.upper():
                    col = col * 26 + (ord(ch) - 64)
                col -= 1
            row = int(row_s) - 1 if row_s else None
            return row, col

        if ":" in a1:
            start, end = a1.split(":", 1)
        else:
            start = end = a1
        sr, sc = split(start)
        er, ec = split(end)
        return (sr or 0, sc or 0, er if er is not None else 10**9,
                ec if ec is not None else 10**9)

    # ----- API -----

    def spreadsheet_create(self, title: str) -> dict[str, Any]:
        with self._lock:
            sid = self._new_id()
            sheet = _FakeSheet(title="Sheet1", sheet_id=self._new_sheet_id())
            ss = _FakeSpreadsheet(
                spreadsheet_id=sid, title=title, sheets={sheet.title: sheet}
            )
            self._spreadsheets[sid] = ss
            return {
                "spreadsheetId": sid,
                "properties": {"title": title},
                "sheets": [
                    {
                        "properties": {
                            "title": sheet.title,
                            "sheetId": sheet.sheet_id,
                        }
                    }
                ],
            }

    def spreadsheet_get(self, spreadsheet_id: str) -> dict[str, Any]:
        with self._lock:
            ss = self._get(spreadsheet_id)
            return {
                "spreadsheetId": ss.spreadsheet_id,
                "properties": {"title": ss.title},
                "sheets": [
                    {
                        "properties": {
                            "title": s.title,
                            "sheetId": s.sheet_id,
                        }
                    }
                    for s in ss.sheets.values()
                ],
            }

    def spreadsheet_batch_update(
        self, spreadsheet_id: str, requests: list[dict[str, Any]]
    ) -> dict[str, Any]:
        with self._lock:
            ss = self._get(spreadsheet_id)
            replies: list[dict[str, Any]] = []
            for req in requests:
                if "addSheet" in req:
                    title = req["addSheet"]["properties"]["title"]
                    if title in ss.sheets:
                        raise ValueError(f"sheet '{title}' already exists")
                    sheet = _FakeSheet(title=title, sheet_id=self._new_sheet_id())
                    ss.sheets[title] = sheet
                    replies.append(
                        {
                            "addSheet": {
                                "properties": {
                                    "title": title,
                                    "sheetId": sheet.sheet_id,
                                }
                            }
                        }
                    )
                elif "deleteSheet" in req:
                    sheet_id = req["deleteSheet"]["sheetId"]
                    title = next(
                        (t for t, s in ss.sheets.items() if s.sheet_id == sheet_id),
                        None,
                    )
                    if title:
                        del ss.sheets[title]
                    replies.append({})
                else:
                    replies.append({})
            return {"replies": replies}

    def values_get(self, spreadsheet_id: str, range_: str) -> dict[str, Any]:
        with self._lock:
            ss = self._get(spreadsheet_id)
            sheet_name, a1 = self._split_range(range_)
            if sheet_name not in ss.sheets:
                return {"values": []}
            sheet = ss.sheets[sheet_name]
            if a1 is None:
                return {"values": [list(r) for r in sheet.values]}
            sr, sc, er, ec = self._a1_to_indices(a1)
            out: list[list[Any]] = []
            for r in sheet.values[sr : er + 1]:
                slice_ = r[sc : ec + 1]
                out.append(list(slice_))
            # Trim trailing all-empty rows like Google does
            while out and not any(x not in (None, "") for x in out[-1]):
                out.pop()
            return {"values": out}

    def values_update(
        self, spreadsheet_id: str, range_: str, values: list[list[Any]]
    ) -> dict[str, Any]:
        with self._lock:
            ss = self._get(spreadsheet_id)
            sheet_name, a1 = self._split_range(range_)
            if sheet_name not in ss.sheets:
                raise ValueError(f"sheet '{sheet_name}' not found")
            sheet = ss.sheets[sheet_name]
            sr, sc, _er, _ec = self._a1_to_indices(a1 or "A1")
            updated = 0
            for i, row in enumerate(values):
                target = sr + i
                while len(sheet.values) <= target:
                    sheet.values.append([])
                line = sheet.values[target]
                for j, val in enumerate(row):
                    col = sc + j
                    while len(line) <= col:
                        line.append("")
                    line[col] = val
                    updated += 1
            return {"updatedRange": range_, "updatedCells": updated}

    def values_batch_update(
        self, spreadsheet_id: str, data: list[dict[str, Any]]
    ) -> dict[str, Any]:
        total = 0
        responses = []
        for entry in data:
            r = self.values_update(
                spreadsheet_id, entry["range"], entry["values"]
            )
            total += r["updatedCells"]
            responses.append(r)
        return {
            "totalUpdatedCells": total,
            "responses": responses,
            "spreadsheetId": spreadsheet_id,
        }

    def values_append(
        self, spreadsheet_id: str, range_: str, values: list[list[Any]]
    ) -> dict[str, Any]:
        with self._lock:
            ss = self._get(spreadsheet_id)
            sheet_name, _ = self._split_range(range_)
            if sheet_name not in ss.sheets:
                raise ValueError(f"sheet '{sheet_name}' not found")
            sheet = ss.sheets[sheet_name]
            start_row = len(sheet.values)
            for row in values:
                sheet.values.append(list(row))
            end_row = len(sheet.values)
            return {
                "spreadsheetId": spreadsheet_id,
                "updates": {
                    "updatedRange": f"{sheet_name}!A{start_row + 1}:Z{end_row}",
                    "updatedRows": len(values),
                },
            }

    def drive_share(
        self, spreadsheet_id: str, email: str, role: str = "writer"
    ) -> dict[str, Any]:
        with self._lock:
            ss = self._get(spreadsheet_id)
            ss.permissions.append({"emailAddress": email, "role": role})
            return {"id": f"perm-{len(ss.permissions)}", "emailAddress": email,
                    "role": role}

    def drive_delete(self, spreadsheet_id: str) -> None:
        with self._lock:
            self._spreadsheets.pop(spreadsheet_id, None)


# ---------- Real Google-API transport ----------


def _load_credentials():
    """Load a service-account ``Credentials`` from the env var.

    ``GOOGLE_SERVICE_ACCOUNT_JSON`` may hold either an inline JSON blob
    (starts with ``{``) or a filesystem path.
    """
    from google.oauth2.service_account import Credentials  # type: ignore

    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is required for GoogleApiTransport"
        )
    if raw.lstrip().startswith("{"):
        info = json.loads(raw)
        return Credentials.from_service_account_info(
            info,
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
    return Credentials.from_service_account_file(
        raw,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )


class GoogleApiTransport:
    """Production transport built on `google-api-python-client`.

    Lazy: imports the heavy SDK only on construction.
    """

    def __init__(self, *, credentials=None) -> None:
        from googleapiclient.discovery import build  # type: ignore

        creds = credentials or _load_credentials()
        self._sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self._drive = build("drive", "v3", credentials=creds, cache_discovery=False)

    def spreadsheet_create(self, title: str) -> dict[str, Any]:
        return (
            self._sheets.spreadsheets()
            .create(body={"properties": {"title": title}})
            .execute()
        )

    def spreadsheet_get(self, spreadsheet_id: str) -> dict[str, Any]:
        return (
            self._sheets.spreadsheets()
            .get(spreadsheetId=spreadsheet_id)
            .execute()
        )

    def spreadsheet_batch_update(
        self, spreadsheet_id: str, requests: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return (
            self._sheets.spreadsheets()
            .batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests})
            .execute()
        )

    def values_get(self, spreadsheet_id: str, range_: str) -> dict[str, Any]:
        return (
            self._sheets.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=range_)
            .execute()
        )

    def values_update(
        self, spreadsheet_id: str, range_: str, values: list[list[Any]]
    ) -> dict[str, Any]:
        return (
            self._sheets.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=range_,
                valueInputOption="USER_ENTERED",
                body={"values": values},
            )
            .execute()
        )

    def values_batch_update(
        self, spreadsheet_id: str, data: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return (
            self._sheets.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": data},
            )
            .execute()
        )

    def values_append(
        self, spreadsheet_id: str, range_: str, values: list[list[Any]]
    ) -> dict[str, Any]:
        return (
            self._sheets.spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=range_,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": values},
            )
            .execute()
        )

    def drive_share(
        self, spreadsheet_id: str, email: str, role: str = "writer"
    ) -> dict[str, Any]:
        return (
            self._drive.permissions()
            .create(
                fileId=spreadsheet_id,
                body={"type": "user", "role": role, "emailAddress": email},
                sendNotificationEmail=False,
                fields="id",
            )
            .execute()
        )

    def drive_delete(self, spreadsheet_id: str) -> None:
        self._drive.files().delete(fileId=spreadsheet_id).execute()
