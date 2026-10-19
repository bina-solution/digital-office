import pytest
from flask import Flask

from incoming_documents.api import (
    _Scope,
    _enrich_registry,
    _validate_sync_entry,
)
from incoming_documents.core.errors import ValidationError


def _drive_entry(**changes):
    # THIN is the only sync contract (proc retired 2026-08-31): a valid entry names NO
    # processor_wf. Since 2026-09-02 a pipe needs its SOURCE folder and nothing else — the
    # synced / failed folders are optional user-visible marks.
    entry = {
        "name": "drive-invoices",
        "source": "drive",
        "connection": "drive-google-company",
        "engine": "v3",
        "projection": "on",
        "pairs": [{
            "from": "source-id",
            "to_sync": "source-id",
            "to": "archive-id",
            "synced": "archive-id",
            "failed": "failed-id",
        }],
    }
    entry.update(changes)
    return entry


def _gmail_entry(**changes):
    entry = {
        "name": "gmail-docs",
        "source": "gmail",
        "connection": "mail_imap_app_password-1",
        "engine": "v3",
        "projection": "on",
        "labels": {"to_sync": "DOC_TO_SYNC"},
    }
    entry.update(changes)
    return entry


def test_processor_wf_is_refused_not_defaulted():
    # A stale caller still naming the v1 processor must be refused at write time -- loudly,
    # where the operator can act -- never accepted into a registry Deliver will refuse forever.
    with pytest.raises(ValidationError, match="retired"):
        _validate_sync_entry(_drive_entry(processor_wf="SyncProcGDoc0001"),
                             require_complete=True)
    with pytest.raises(ValidationError, match="retired"):
        _validate_sync_entry(_drive_entry(v3_mode="proc"), require_complete=True)
    # explicit null (what the Console sends) and absence are both simply thin
    _validate_sync_entry(_drive_entry(processor_wf=None), require_complete=True)


# (the sync capabilities test left with `_sync_capabilities` itself — the sync page is DB-only
#  since 2026-09-02 and offers no manual moves; nothing to assert about a capability map.)

def test_complete_drive_entry_is_valid():
    _validate_sync_entry(_drive_entry(), require_complete=True)


@pytest.mark.parametrize("missing", ["connection", "projection"])
def test_production_entry_rejects_missing_contract_field(missing):
    # processor_wf left this list 2026-08-31: absence IS the contract now (thin-only).
    entry = _drive_entry()
    entry.pop(missing)
    with pytest.raises(ValidationError):
        _validate_sync_entry(entry, require_complete=True)


def test_drive_entry_needs_only_its_source_folder():
    # OWNER RULE (2026-09-02): dest / fail-dest are optional marks; the source folder is the pipe.
    entry = _drive_entry()
    entry["pairs"][0]["failed"] = ""
    entry["pairs"][0]["synced"] = ""
    entry["pairs"][0]["to"] = ""
    _validate_sync_entry(entry, require_complete=True)
    entry["pairs"][0]["to_sync"] = ""
    entry["pairs"][0]["from"] = ""
    with pytest.raises(ValidationError, match="to_sync"):
        _validate_sync_entry(entry, require_complete=True)


def test_gmail_entry_needs_only_its_source_label():
    _validate_sync_entry(_gmail_entry(), require_complete=True)
    with pytest.raises(ValidationError, match="to_sync"):
        _validate_sync_entry(_gmail_entry(labels={"synced": "SYNCED_DOC"}), require_complete=True)


def test_drive_entry_rejects_conflicting_aliases():
    entry = _drive_entry()
    entry["pairs"][0]["to_sync"] = "different-source-id"
    with pytest.raises(ValidationError, match="conflict"):
        _validate_sync_entry(entry, require_complete=True)


class _CountsTransport:
    """The sync board's reads are the two DB-only views — sync_item_counts (the bar) and
    sync_item_reasons (the chips, 2026-09-03). Nothing else is asked: no walk, no other app."""

    def __init__(self, rows, reasons=None):
        self.rows = rows
        self.reasons = reasons or []
        self.calls = []

    def select(self, **kwargs):
        self.calls.append(kwargs)
        assert kwargs["table"] in ("sync_item_counts", "sync_item_reasons")
        return self.rows if kwargs["table"] == "sync_item_counts" else self.reasons


def test_enrich_registry_reads_only_the_counts_view(monkeypatch):
    monkeypatch.setattr("incoming_documents.api._instance", lambda: "incoming-documents-main")
    monkeypatch.setattr("incoming_documents.api._request_schema", lambda default="public": "indox_t")
    transport = _CountsTransport([{
        "source": "incoming-documents-main/drive-invoices", "pipe": "drive-invoices",
        "discovered": 3, "claimed": 1, "delivered": 40, "failed": 2, "needs_review": 1, "total": 47,
        "last_discovered_at": "2026-09-02T10:00:00+00:00",
        "last_delivered_at": "2026-09-02T10:05:00+00:00", "last_error": "boom",
    }])
    out = _enrich_registry(transport, [_drive_entry(), _drive_entry(name="drive-empty")],
                           _Scope(instance="incoming-documents-main", doc_table="incoming_documents"))
    assert [c["table"] for c in transport.calls] == ["sync_item_counts", "sync_item_reasons"]
    got = {e["name"]: e for e in out}
    assert got["drive-invoices"]["counts"] == {
        "discovered": 3, "claimed": 1, "delivered": 40, "failed": 2, "needs_review": 1, "total": 47}
    assert got["drive-invoices"]["counts_computed"] is True
    assert got["drive-invoices"]["last_error"] == "boom"
    assert got["drive-invoices"]["last_run"] == "2026-09-02T10:05:00+00:00"
    # a pipe the view has no row for has NO items — a confident zero, not an unknown
    assert got["drive-empty"]["counts"]["total"] == 0
    assert got["drive-empty"]["counts_computed"] is True


def test_enrich_registry_reports_unknown_when_the_view_cannot_be_read(monkeypatch):
    monkeypatch.setattr("incoming_documents.api._request_schema", lambda default="public": "indox_t")

    class Broken:
        def select(self, **kwargs):
            raise RuntimeError("no view")

    out = _enrich_registry(Broken(), [_drive_entry()],
                           _Scope(instance="incoming-documents-main", doc_table="incoming_documents"))
    assert out[0]["counts"] is None
    assert out[0]["counts_computed"] is False


def test_config_row_patch_scopes_select_and_update_to_active_instance(monkeypatch):
    # Exercised against `companies`, not `tag_rules`. What this test is about is TENANT SCOPING --
    # that the existence check and the update are both filtered to the active instance -- and the
    # table was only ever a vehicle for that. mail-organizer-refactor 8 moved the label organiser
    # (rules included) to the mail app and dropped tag_rules from _EDITABLE_CONFIG_TABLES, so the
    # endpoint now answers 400 for it by design; the test kept asserting 200 and had been failing
    # ever since. `companies` is the one table the endpoint still edits, so the original assertions
    # carry over unchanged. The rejection itself is covered by the test below.
    from incoming_documents.api import create_blueprint

    class Transport:
        def __init__(self):
            self.select_filter = None
            self.update_match = None

        def select(self, **kwargs):
            self.select_filter = kwargs["filter"]
            return [{"id": 17}]

        def update(self, **kwargs):
            self.update_match = kwargs["match"]
            return [{"id": 17, "LABEL": "new-label"}]

    transport = Transport()
    monkeypatch.setattr(
        "incoming_documents.backends.supabase_transport.HttpxSupabaseTransport",
        lambda: transport,
    )
    monkeypatch.setattr("incoming_documents.api._instance", lambda: "tenant-a")

    app = Flask(__name__)
    app.register_blueprint(create_blueprint(url_prefix="/incomingDocuments"))
    response = app.test_client().patch(
        "/incomingDocuments/config/companies/17",
        json={"key": "LABEL", "value": "new-label"},
    )

    assert response.status_code == 200
    assert transport.select_filter == {"instance": "tenant-a", "id": 17}
    assert transport.update_match == {"instance": "tenant-a", "id": 17}


def test_config_row_patch_rejects_tables_that_are_not_editable():
    # Locks in what mail-organizer-refactor 8 decided: tag_rules stays READABLE for audit but
    # rejects writes here, because the label organiser owns it now (mailview / mailapi
    # /organizer/defaults). Nothing asserted this, which is why the change silently turned an
    # existing test red instead of being caught as an intended contract change.
    from incoming_documents.api import create_blueprint

    app = Flask(__name__)
    app.register_blueprint(create_blueprint(url_prefix="/incomingDocuments"))
    response = app.test_client().patch(
        "/incomingDocuments/config/tag_rules/17",
        json={"key": "LABEL", "value": "new-label"},
    )

    assert response.status_code == 400
