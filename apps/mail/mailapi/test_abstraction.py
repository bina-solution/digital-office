"""The mail service is a MULTI-PROTOCOL abstraction — these tests are what makes that a fact.

Three backends answer the same op surface: the local mailbox, Gmail over an app password, and Gmail
over OAuth. "They behave the same" is the entire promise of the service, and until now nothing
checked it: each backend was written separately, and a method quietly missing from one of them shows
up as a 500 in production against one account and works fine against another.

These are STRUCTURAL tests. They do not open sockets, so they run anywhere — no Gmail credentials, no
GreenMail, no network. What they prove is the part that actually rots: that the op surface is the
same shape everywhere, that the manifest tells the truth about it, and that protocol-specific ops are
declared as such instead of being discovered by provoking a 501.

    python3 -m pytest apps/mail/mailapi/test_abstraction.py -q
"""
import inspect
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import adapters                       # noqa: E402
from app import GmailBackend, GmailOAuthBackend   # noqa: E402
from local_app import LocalBackend    # noqa: E402

BACKENDS = [LocalBackend, GmailBackend, GmailOAuthBackend]
BACKEND_IDS = [c.__name__ for c in BACKENDS]


# ── the op surface is the same shape on every protocol ────────────────────────
@pytest.mark.parametrize("cls", BACKENDS, ids=BACKEND_IDS)
@pytest.mark.parametrize("op,method", sorted(adapters.CANONICAL_OPS.items()))
def test_every_backend_implements_every_canonical_op(cls, op, method):
    """A canonical op must exist on ALL THREE. This is the test that would have caught a backend
    growing an op its siblings never got — which is exactly how `thread` arrived."""
    fn = getattr(cls, method, None)
    assert callable(fn), f"{cls.__name__} does not implement {op!r} (expected method {method!r})"


@pytest.mark.parametrize("cls", BACKENDS, ids=BACKEND_IDS)
@pytest.mark.parametrize("op,method", sorted(adapters.RETIRED_OPS.items()))
def test_retired_ops_stay_retired(cls, op, method):
    """`deleteLabel` and `rebuildLabels` were removed with their zero callers (RELEASE-DECISIONS
    N12). A backend method with no route is dead code that LOOKS like an op; if one grows back it
    must come with a route, an entry in CANONICAL_OPS and a caller — not silently."""
    assert op not in adapters.CANONICAL_OPS
    assert not callable(getattr(cls, method, None)), (
        f"{cls.__name__}.{method} exists but {op!r} is retired — no route answers it")


@pytest.mark.parametrize("cls", BACKENDS, ids=BACKEND_IDS)
def test_every_backend_declares_its_protocol(cls):
    """resolve_active() keys its cache on the connection and _outbound_scope() branches on this. A
    backend without a protocol string is invisible to both."""
    assert getattr(cls, "protocol", None), f"{cls.__name__} has no `protocol`"


@pytest.mark.parametrize("cls", BACKENDS, ids=BACKEND_IDS)
def test_every_backend_can_be_closed(cls):
    """Backends own IMAP sockets and are dropped on credential rotation. One that cannot be closed
    leaks a connection pool per rotation — and Gmail caps concurrent IMAP connections per account."""
    assert callable(getattr(cls, "close", None)), f"{cls.__name__} has no close()"


@pytest.mark.parametrize("cls", BACKENDS, ids=BACKEND_IDS)
def test_health_surface_is_uniform(cls):
    """/healthz and /readyz dispatch to these on whichever backend is active. A missing one is a 500
    on the endpoint the compose healthcheck keys on."""
    for m in ("healthz", "probe", "stats", "stats_reset"):
        assert callable(getattr(cls, m, None)), f"{cls.__name__} has no {m}()"


# ── the manifest tells the truth ───────────────────────────────────────────────
def test_ops_for_reports_only_implemented_ops():
    """ops_for() asks the object rather than trusting a list, so a backend that loses a method stops
    advertising it instead of advertising a 500."""
    class Stunted:
        protocol = "test"
        def search(self, b):  # noqa: D102
            return {}
    ops = adapters.ops_for(Stunted())
    assert ops == ["search"], ops


def test_every_protocol_advertises_the_same_ops():
    """With the protocol-specific split gone, the op surface is ONE list on every backend — what a
    caller can do never depends on which connection is selected."""
    assert adapters.ops_for(LocalBackend) == adapters.ops_for(GmailBackend) == \
        adapters.ops_for(GmailOAuthBackend) == list(adapters.CANONICAL_OPS)


def test_canonical_and_retired_ops_do_not_overlap():
    """An op in both dicts would be advertised and retired at once."""
    assert not (set(adapters.CANONICAL_OPS) & set(adapters.RETIRED_OPS))


# ── send() must never claim delivery it did not perform ───────────────────────
def test_local_send_signature_is_uniform():
    """Every backend's send takes exactly the request body — the route passes it straight through."""
    for cls in BACKENDS:
        params = list(inspect.signature(cls.send).parameters)
        assert params == ["self", "b"], f"{cls.__name__}.send{tuple(params)}"


# ── an error must blame the connection that actually failed ───────────────────
def test_adapter_error_carries_the_failing_connection():
    """Found by experiment, not by reading: sending through a misconfigured Gmail account answered

        {"connection_id": "mail_imap_local-local",
         "error": "connection mail_imap_app_password-env: secret needs {username, password}"}

    The message named Gmail; the machine-readable field named the local mailbox, because the handler
    reported cc.active() regardless of which connection the request had overridden to. Anything
    keying on that field — the console's state chip, an n8n error branch — is pointed at an account
    that was never involved."""
    e = adapters.AdapterError("boom", 502, connection_id="mail_imap_app_password-env")
    assert e.connection_id == "mail_imap_app_password-env"
    assert e.status == 502


def test_build_failures_name_their_own_connection():
    """Every raise site inside _build must attach its cid — that is the path a per-call override
    takes, and the path where the wrong id is most misleading."""
    with pytest.raises(adapters.AdapterError) as ei:
        adapters._build("some-conn-id", "mail_imap_app_password", {})       # missing user/password
    assert ei.value.connection_id == "some-conn-id"

    with pytest.raises(adapters.AdapterError) as ei2:
        adapters._build("other-conn", "no_such_protocol", {})
    assert ei2.value.connection_id == "other-conn"


def test_default_outbound_mode_is_our_own_mta():
    """The local backend now talks to a real Postfix, which delivers or bounces. The dangerous
    default would be assuming an external relay is configured when none is — so the default names
    what is actually there."""
    import local_app
    assert local_app.SMTP_MODE == "mta" or os.environ.get("LOCALMAIL_SMTP_MODE"), (
        "local mail defaulted to something other than 'mta' with no explicit setting")
