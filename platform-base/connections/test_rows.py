"""test_rows — what a row's STATUS says, for the cases where the probe alone would say it wrong.

    python3 platform-base/connections/test_rows.py

A status is a claim the owner acts on: a red dot beside "סודות מערכת" sends somebody to look for a
failure. These hold the decisions that keep that dot honest — none can be shown on demand by a
running stack, because they depend on what an office does NOT run.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app  # noqa: E402

PROV = {"group": "Infra", "kind": "text-secret", "env": "SOME_SECRET", "probe": {"type": "http", "url": "http://not-here:1/"}}


def _row(reqs, probe_says, prov=PROV):
    real = (app.resolve, app.probe)
    app.resolve, app.probe = (lambda *a, **k: ("env", "a-real-value")), (lambda *a, **k: probe_says)
    try:
        return app._row("some-secret", dict(prov), reqs, {})
    finally:
        app.resolve, app.probe = real


def test_a_row_nobody_in_this_office_consumes_is_not_degraded():
    """GlitchTip's two secrets on an office that does not run GlitchTip: the value is set, the probe
    cannot even resolve the service's name, and nobody here uses it. That is "not in use", not a
    failure — it read `degraded` and kept a red dot on a healthy office."""
    row = _row({}, ("degraded", "probe failed: <urlopen error [Errno -2] Name or servic"))
    assert row["consumers"] == [] and row["status"] == "unset", row["status"]
    assert "office" in row["detail"]


def test_a_row_somebody_consumes_stays_degraded_when_its_probe_fails():
    """The same probe failure, with a consumer in the office: the dependency IS down, and the row
    must go on saying so — the rule above is about offices that do not run the service at all."""
    reqs = {"some-secret": [{"service": "glitchtip", "required": True}]}
    row = _row(reqs, ("degraded", "probe failed: <urlopen error [Errno -2] Name or servic"))
    assert row["consumers"] == ["glitchtip"] and row["status"] == "degraded" and row["required"] is True


def test_a_pairing_nobody_in_this_office_uses_does_not_ask_for_action():
    """The WhatsApp pairing and the Google grant on an office that runs neither chat nor INDOX: the
    probe says "start the bot to pair" / "click Connect", and «דורשים טיפול» counted both. With a
    consumer in the office the same answer stands — that IS somebody's next step."""
    row = _row({}, ("needs_action", "bot offline — start it to pair"))
    assert row["status"] == "unset" and "office" in row["detail"], row
    reqs = {"some-secret": [{"service": "chat", "required": False}]}
    assert _row(reqs, ("needs_action", "bot offline — start it to pair"))["status"] == "needs_action"


def test_a_missing_optional_row_is_unset_and_a_required_one_is_missing():
    assert _row({}, ("missing", "not configured"))["status"] == "unset"
    reqs = {"some-secret": [{"service": "n8n", "required": True}]}
    assert _row(reqs, ("missing", "not configured"))["status"] == "missing"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("  ok  ", t.__name__)
    print(f"connections rows: {len(tests)}/{len(tests)} ok")
