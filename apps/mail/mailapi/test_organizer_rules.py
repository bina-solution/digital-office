# -*- coding: utf-8 -*-
"""The organizer plane's validation, PROCESSED guard, snapshot + rollback (RELEASE-DECISIONS N2).

"A bad rule cannot be saved" is the acceptance line; these tests are what makes it a fact rather
than an intention. They drive `options.py` directly and the HTTP routes through Flask's test
client, against a temp file — no stack, no volume, no IMAP:

    python3 -m pytest apps/mail/mailapi/test_organizer_rules.py -q

The shipped fixture (`fixtures/tag_rules.json`) is the backward-compatibility contract: every one
of its 23 rows — the SYSTEM sentinel form, `attachments.some(a => !a.inline)`, a LABEL with a
trailing space, `thread.messages[0].text` — must pass unchanged, because the seed goes through the
same validation as the editor.
"""
import copy
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import options  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "tag_rules.json")
SENTINEL = 'contains(email.text, "__NEVER_MATCH_SYNC_STATE__")'


def fixture_rows():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def doc_of(rows):
    return {"mail": {"organizer": {"mode": "default", "rules": rows}}}


def minimal_rows():
    """The smallest valid document: one event rule and the PROCESSED mark."""
    return [
        {"KEY": "INVOICE_RELATED", "LABEL": "קשור-לחשבונית", "TYPE": "ON_CREATE_EVENT",
         "EVENT": "ON_CREATE", "RULE": 'containsAny(email.text, ["invoice", "document"])',
         "row_number": 5},
        {"KEY": "PROCESSED", "LABEL": "תוויות-טופל", "TYPE": "PROCESSED", "EVENT": "SYSTEM",
         "RULE": SENTINEL, "row_number": 200},
    ]


@pytest.fixture
def store(tmp_path, monkeypatch):
    p = str(tmp_path / "organizer-defaults.json")
    monkeypatch.setattr(options, "DEFAULTS_PATH", p)
    return p


def problems_of(exc):
    return {(p["row"], p["field"]): p["message"] for p in exc.value.problems}


# ── the fixture is the contract ─────────────────────────────────────────────────────────────────
def test_shipped_fixture_passes_and_is_normalised(store):
    rows = fixture_rows()
    doc, ignored = options.put_defaults(doc_of(rows))
    out = options.rules_of(doc)
    assert len(out) == 23 and ignored == []
    # renumbered 1..n, order preserved (row_number first, list position breaks the fixture's ties)
    assert [r["row_number"] for r in out] == list(range(1, 24))
    assert [r["KEY"] for r in out][:3] == ["SEND_FAILED", "DOMAIN_RELATED", "AUTOMATION_INFRA"]
    assert [r["KEY"] for r in out][-4:] == ["SAVED_SHIPMENT", "FOUND_UNKNOWN", "ACTION_DONE", "ACTION_FAILED"]
    # `enabled` defaulted, nothing else rewritten — the trailing space in SUPPLIER_MAIL survives
    assert all(r["enabled"] is True for r in out)
    assert next(r for r in out if r["KEY"] == "SUPPLIER_MAIL")["LABEL"] == "מייל-מספק "
    assert doc["saved_at"] and "previous" not in doc


def test_every_fixture_rule_passes_the_syntax_check():
    for r in fixture_rows():
        assert options.check_rule_syntax(r["RULE"]) == [], (r["KEY"], r["RULE"][:80])


def test_seed_goes_through_validation(store, monkeypatch):
    import organizer_seed
    monkeypatch.setattr(organizer_seed, "FIXTURE_PATH", FIXTURE)
    assert organizer_seed.seed_if_missing().startswith("organizer defaults seeded")
    assert len(options.rules_of(options.get_defaults())) == 23
    assert organizer_seed.seed_if_missing().startswith("organizer defaults already present")


# ── the RULE syntax check ───────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("rule", [
    'contains(email.text, "x")',
    "attachments.length > 0 && !includesAny(email.labels, [\"a\", \"b\"])",
    "attachments.some(a => !a.inline)",
    "attachments.filter((a, i) => a.size > 1000 && i < 3).length > 0",
    "thread.messages[0].text === 'x' || thread.from === \"person113@example.com\"",
    "noHebrew(email.text) && (isEmpty(email.cc) ? true : false)",
    "email.ageDays <= 3 && email.size !== 0",
    "email.from?.toLowerCase() === \"a@b.c\"",
])
def test_rules_the_engine_can_evaluate_pass(rule):
    assert options.check_rule_syntax(rule) == []


@pytest.mark.parametrize("rule,needle", [
    ("", "non-empty"),
    ("   ", "non-empty"),
    ('contains(email.text, "x"', "unclosed '('"),
    ('contains(email.text, "x"))', "unbalanced ')'"),
    ('includes(email.labels, "x"]', "unbalanced ']'"),
    ('contains(email.text, "x)', "unterminated string"),
    ("contains(email.text, 'x)", "unterminated string"),
    ("email.text = 'x'", "assignment"),
    ("contains(email.text, \"x\"); true", "';'"),
    ("({a: 1}).a", "'{'"),
    ("`abc`", "template"),
    ("foo(email.text)", "unknown identifier 'foo'"),
    ("Math.max(1, 2) > 1", "unknown identifier 'Math'"),
    ("new RegExp('x').test(email.text)", "unknown identifier 'new'"),
    ("email.text &&", "ends with an operator"),
    ("/abc/i.test(email.text)", "unknown identifier 'abc'"),
])
def test_rules_the_engine_would_throw_on_are_refused(rule, needle):
    msgs = options.check_rule_syntax(rule)
    assert msgs, rule
    assert any(needle in m for m in msgs), (rule, msgs)


def test_rule_length_is_bounded():
    assert options.check_rule_syntax("true || " * 20000 + "true")[0].startswith("RULE is longer")


# ── document validation (400 problems pinned to cells) ──────────────────────────────────────────
def test_body_shape_problems():
    with pytest.raises(options.ValidationError) as e:
        options.validate([])
    assert e.value.problems[0]["message"] == "body must be a JSON object"
    with pytest.raises(options.ValidationError) as e:
        options.validate({"mail": {}})
    assert e.value.problems[0]["field"] == "mail.organizer"
    with pytest.raises(options.ValidationError) as e:
        options.validate({"mail": {"organizer": {"rules": {"KEY": "X"}}}})
    assert e.value.problems[0]["field"] == "mail.organizer.rules"


def test_row_problems_name_row_field_and_reason():
    rows = minimal_rows()
    rows[0]["KEY"] = "invoice related"
    rows[0]["LABEL"] = "   "
    rows[0]["RULE"] = "contains(email.text, "
    rows[0]["enabled"] = "yes"
    rows[0]["row_number"] = "5"
    rows.append({"KEY": "PROCESSED", "LABEL": "dup", "TYPE": "PROCESSED", "RULE": SENTINEL})
    rows.append({"KEY": "BAD_TYPE", "LABEL": "x", "TYPE": "SOMETHING", "RULE": "true"})
    rows.append({"KEY": "NOT_A_MARK", "LABEL": "x", "TYPE": "NOT_A_MARK", "RULE": "true"})
    rows.append("not a rule")
    with pytest.raises(options.ValidationError) as e:
        options.validate(doc_of(rows))
    p = problems_of(e)
    assert "UPPER_SNAKE_CASE" in p[(0, "KEY")]
    assert p[(0, "LABEL")] == "LABEL is required"
    assert "unclosed" in p[(0, "RULE")]
    assert p[(0, "enabled")] == "enabled must be true or false"
    assert p[(0, "row_number")] == "row_number must be an integer"
    assert p[(2, "KEY")] == "duplicate KEY 'PROCESSED' (also row 1)"
    assert "ON_CREATE_EVENT" in p[(3, "TYPE")]
    assert "never-match sentinel" in p[(4, "TYPE")]
    assert p[(5, "")] == "each rule must be an object"
    assert str(e.value).startswith("organizer rules refused: ")


def test_override_mode_is_refused_and_dead_knobs_are_dropped(store):
    doc = doc_of(minimal_rows())
    doc["mail"]["organizer"]["mode"] = "override"
    with pytest.raises(options.ValidationError) as e:
        options.validate(doc)
    assert problems_of(e)[(None, "mail.organizer.mode")].startswith("mode may only be")

    doc["mail"]["organizer"].update(mode="default", enabled=True, schedule_min=15, batch_limit=10)
    stored, ignored = options.put_defaults(doc)
    assert ignored == ["batch_limit", "enabled", "schedule_min"]
    assert set(stored["mail"]["organizer"]) == {"mode", "rules"}


def test_order_is_row_number_then_list_position_and_missing_goes_last():
    rows = [
        {"KEY": "B", "LABEL": "b", "TYPE": "ON_CREATE_EVENT", "RULE": "true", "row_number": 20},
        {"KEY": "NO_NUMBER", "LABEL": "n", "TYPE": "ON_CREATE_EVENT", "RULE": "true"},
        {"KEY": "A", "LABEL": "a", "TYPE": "ON_CREATE_EVENT", "RULE": "true", "row_number": 10},
        {"KEY": "A2", "LABEL": "a2", "TYPE": "ON_CREATE_EVENT", "RULE": "true", "row_number": 10},
        {"KEY": "PROCESSED", "LABEL": "p", "TYPE": "PROCESSED", "RULE": SENTINEL, "row_number": 200},
    ]
    doc, _ = options.validate(doc_of(rows))
    out = options.rules_of(doc)
    assert [r["KEY"] for r in out] == ["A", "A2", "B", "PROCESSED", "NO_NUMBER"]
    assert [r["row_number"] for r in out] == [1, 2, 3, 4, 5]


def test_disabled_rows_are_kept_and_flagged(store):
    rows = minimal_rows()
    rows[0]["enabled"] = False
    doc, _ = options.put_defaults(doc_of(rows))
    out = options.rules_of(doc)
    assert [r["enabled"] for r in out] == [False, True]
    assert options.enabled_of({"enabled": "junk"}) is True     # a legacy row is enabled


# ── the PROCESSED guard (409) ───────────────────────────────────────────────────────────────────
def test_processed_must_exist(store):
    with pytest.raises(options.ProcessedGuard) as e:
        options.put_defaults(doc_of(minimal_rows()[:1]))
    assert "no PROCESSED row" in str(e.value)
    doc, _ = options.put_defaults(doc_of(minimal_rows()[:1]), confirm_processed=True)
    assert options.processed_row(doc) is None


def test_processed_rename_needs_confirmation(store):
    options.put_defaults(doc_of(minimal_rows()))
    renamed = minimal_rows()
    renamed[1]["LABEL"] = "טופל-אחרת"
    with pytest.raises(options.ProcessedGuard) as e:
        options.put_defaults(doc_of(renamed))
    assert "renaming PROCESSED from 'תוויות-טופל' to 'טופל-אחרת'" in str(e.value)
    doc, _ = options.put_defaults(doc_of(renamed), confirm_processed=True)
    assert options.processed_row(doc)["LABEL"] == "טופל-אחרת"
    # the same label, re-saved: no guard (trailing whitespace is not a rename)
    same = copy.deepcopy(renamed)
    same[1]["LABEL"] = "טופל-אחרת "
    options.put_defaults(doc_of(same))


# ── snapshot + rollback ─────────────────────────────────────────────────────────────────────────
def test_previous_snapshot_and_rollback_swap(store):
    with pytest.raises(options.NothingToRollBack):
        options.rollback()
    first, _ = options.put_defaults(doc_of(minimal_rows()))
    assert "previous" not in first and options.public_view(first)[1]["available"] is False

    second_rows = minimal_rows()
    second_rows[0]["LABEL"] = "שונה"
    second, _ = options.put_defaults(doc_of(second_rows))
    assert second["previous"]["mail"] == first["mail"]
    assert "previous" not in second["previous"]                     # one level only
    view, info = options.public_view(second)
    assert "previous" not in view and info == {"available": True, "saved_at": first["saved_at"], "rules": 2}

    back = options.rollback()
    assert options.rules_of(back)[0]["LABEL"] == "קשור-לחשבונית"
    assert options.rules_of(back["previous"])[0]["LABEL"] == "שונה"     # reversible
    again = options.rollback()
    assert options.rules_of(again)[0]["LABEL"] == "שונה"
    # a client that round-trips `previous` cannot forge it: PUT ignores it
    doc = doc_of(minimal_rows())
    doc["previous"] = {"mail": {"organizer": {"rules": [{"KEY": "FORGED"}]}}}
    stored, _ = options.put_defaults(doc)
    assert options.rules_of(stored["previous"])[0]["KEY"] != "FORGED"


def test_write_is_atomic_and_readable(store):
    options.put_defaults(doc_of(minimal_rows()))
    assert not os.path.exists(store + ".tmp")
    with open(store, encoding="utf-8") as f:
        assert len(json.load(f)["mail"]["organizer"]["rules"]) == 2


# ── the HTTP shape (through Flask's test client) ────────────────────────────────────────────────
@pytest.fixture
def client(store):
    import profiles
    profiles._started = True            # no background reconciler in a unit test
    import service
    service.app.testing = True
    return service.app.test_client()


def test_put_answers_400_with_problems(client):
    rows = minimal_rows()
    rows[0]["RULE"] = "foo(email.text)"
    r = client.put("/organizer/defaults", json=doc_of(rows))
    assert r.status_code == 400
    body = r.get_json()
    assert body["error"].startswith("organizer rules refused")
    assert body["problems"] == [{"row": 0, "field": "RULE",
                                 "message": body["problems"][0]["message"]}]
    assert "unknown identifier 'foo'" in body["problems"][0]["message"]
    r = client.put("/organizer/defaults", data="not json", content_type="text/plain")
    assert r.status_code == 400 and r.get_json()["problems"][0]["field"] == "mail.organizer"


def test_put_get_rollback_and_settings_roundtrip(client):
    r = client.put("/organizer/defaults", json=doc_of(minimal_rows()))
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True and body["ignored"] == [] and body["rollback"]["available"] is False
    assert "previous" not in body["defaults"]

    # the engine's document carries `enabled` on rows AND labels, and skips nothing
    rows = minimal_rows()
    rows[0]["enabled"] = False
    assert client.put("/organizer/defaults", json=doc_of(rows)).status_code == 200
    s = client.get("/organizer/settings?connection_id=whatever").get_json()
    assert [x["enabled"] for x in s["gmail"]["rows"]] == [False, True]
    assert s["gmail"]["labels"]["INVOICE_RELATED"]["enabled"] is False
    assert s["gmail"]["labels"]["PROCESSED"] == {
        "name": "תוויות-טופל", "label_id": None, "event": "SYSTEM", "rule": SENTINEL,
        "row_number": 2, "enabled": True}

    g = client.get("/organizer/defaults").get_json()
    assert "previous" not in g["defaults"] and g["rollback"]["available"] is True

    r = client.post("/organizer/rollback")
    assert r.status_code == 200
    s = client.get("/organizer/settings").get_json()
    assert [x["enabled"] for x in s["gmail"]["rows"]] == [True, True]


def test_put_answers_409_on_processed_until_confirmed(client):
    assert client.put("/organizer/defaults", json=doc_of(minimal_rows())).status_code == 200
    r = client.put("/organizer/defaults", json=doc_of(minimal_rows()[:1]))
    assert r.status_code == 409
    assert r.get_json()["confirm_with"] == {"confirm_processed": True}
    body = doc_of(minimal_rows()[:1])
    body["confirm_processed"] = True
    r = client.put("/organizer/defaults", json=body)
    assert r.status_code == 200
    assert "confirm_processed" not in r.get_json()["defaults"]


def test_rollback_with_nothing_is_409(client):
    r = client.post("/organizer/rollback")
    assert r.status_code == 409 and "nothing to roll back" in r.get_json()["error"]


def test_retired_routes_are_gone_and_kept_routes_exist(client):
    import service
    rules = {r.rule for r in service.app.url_map.iter_rules()}
    for gone in ("/", "/ui/unread", "/ui/attachment/<int:uid>", "/labels/delete", "/labels/rebuild",
                 "/connections/<cid>/options", "/organizer/effective/<cid>"):
        assert gone not in rules, gone
    for kept in ("/mailboxes", "/mailboxes/<path:address>", "/setup/status", "/providers",
                 "/connections/<cid>/probe", "/organizer/defaults", "/organizer/settings",
                 "/organizer/rollback", "/search", "/message/<int:uid>", "/thread/<tid>",
                 "/labels", "/labels/add", "/labels/remove", "/labels/create", "/append", "/send"):
        assert kept in rules, kept
    assert service.app.static_folder is None
