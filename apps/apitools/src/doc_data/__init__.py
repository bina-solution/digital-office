"""doc_data — business-document management (CRUD + lifecycle) over Postgres/Supabase.

Green-Invoice / morning.com-style API: create a draft, edit it, issue it (gapless legal
number + immutable rendered artifact), download (מקור once / העתק), send, mark paid, and
cancel via a credit document — with audit trail, tamper-evident chaining and 7-year
retention. Postgres is the source of truth (SQLite fallback for standalone dev).
No OCR in this layer.
"""
from . import store, entities
from .store import (create, update, get, query, issue, download, send, pay, cancel,
                    events, convert, record_consent, has_consent, attach_allocation,
                    verify_sequence, verify_chain)
from . import db
