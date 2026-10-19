"""Backend implementations of `DocumentRepo`.

Public exports:
* `GSheetRepo` / `SupabaseRepo` — backend implementations
* Transport seams: `GSheetTransport` + Fake/GoogleApi, `SupabaseTransport` + Fake/Httpx
"""
from .gsheet import GSheetRepo
from .gsheet_transport import (
    FakeGSheetTransport,
    GoogleApiTransport,
    GSheetTransport,
)
from .supabase import SupabaseRepo
from .supabase_transport import (
    FakeSupabaseTransport,
    HttpxSupabaseTransport,
    SupabaseTransport,
)

__all__ = [
    "GSheetRepo",
    "GSheetTransport",
    "FakeGSheetTransport",
    "GoogleApiTransport",
    "SupabaseRepo",
    "SupabaseTransport",
    "FakeSupabaseTransport",
    "HttpxSupabaseTransport",
]
