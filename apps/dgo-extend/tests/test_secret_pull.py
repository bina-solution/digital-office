#!/usr/bin/env python3
"""test_secret_pull — a linked office takes a NAMED secret it is given, over the link, into its own vault (DGO-1330).

    python3 apps/dgo-extend/tests/test_secret_pull.py

«סודות תמיד במק»: a business secret lives in one office's vault, and no office writes another's (hos-001). So the
office that holds it NAMES what it gives whom (DGO_SERVE_SECRETS=<office>=<instance>), and the other office's own
dgo-extend pulls it (app.api_link_secret → projection.pull_secrets):

  · the holder answers only through the link proxy, only the office its door names, only with that pair's secret;
  · only an instance named for THAT office — never a pair's own secret, never a copy the holder pulled itself;
  · the copy keeps its id, protocol and label (what an app looks it up by) and is marked `office` — and a row of
    the puller's own by that id is never replaced; a copy no longer given is removed.

Hermetic: the vault, the link and the web stack are stood in, as in test_agent_pull.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import links  # noqa: E402
import projection  # noqa: E402
from test_agent_pull import PROXY, SECRET, _Req, _app, _status  # noqa: E402

BOT = {"token": "123456789:" + "A" * 35, "username": "BinaSolutionsAgentBot"}
IID = "telegram_bot-5fdf4bea"


class _Vault:
    """links._call, against a dict of rows: {id: {protocol, label, account_hint, secret}}."""

    def __init__(self, rows: dict):
        self.rows = rows
        self.calls = []

    def __call__(self, method, path, body=None, timeout=20):
        self.calls.append((method, path))
        if method == "GET" and path.startswith("/api/instances?") or (method == "GET" and path == "/api/instances"):
            return {"instances": [{"id": k, **{x: v[x] for x in ("protocol", "label", "account_hint")}}
                                  for k, v in self.rows.items()]}
        if method == "GET" and path.endswith("/secret"):
            iid = path.split("/")[3]
            if iid not in self.rows:
                raise links.LinkError("no such row", 404)
            return {"secret": dict(self.rows[iid]["secret"])}
        if method == "POST" and path == "/api/instances":
            self.rows[body["id"]] = {k: body[k] for k in ("protocol", "label", "account_hint", "secret")}
            return {"id": body["id"]}
        if method == "PUT" and path.endswith("/secret"):
            self.rows[path.split("/")[3]]["secret"] = dict(body["secret"])
            return {}
        if method == "DELETE":
            self.rows.pop(path.split("/")[3], None)
            return {}
        raise AssertionError((method, path))


def _holding(given: str, rows: dict):
    app = _app()
    saved = {"home": app.cv.home_office, "pairs": links.pair_tokens, "proxy": app._link_proxy_addresses,
             "call": links._call, "env": os.environ.get("DGO_SERVE_SECRETS")}
    app._link_proxy_addresses = lambda: {PROXY}
    app.cv.home_office = lambda: {"id": "hp-laptop"}
    links.pair_tokens = lambda home, peer: [("dgo_link-macbook", SECRET)] if (home, peer) == ("hp-laptop", "macbook") else []
    links._call = _Vault(rows)
    os.environ["DGO_SERVE_SECRETS"] = given
    return app, saved


def _unhold(app, saved):
    app.cv.home_office, app._link_proxy_addresses = saved["home"], saved["proxy"]
    links.pair_tokens, links._call = saved["pairs"], saved["call"]
    if saved["env"] is None:
        os.environ.pop("DGO_SERVE_SECRETS", None)
    else:
        os.environ["DGO_SERVE_SECRETS"] = saved["env"]


def _rows():
    return {IID: {"protocol": "telegram_bot", "label": "בוט טלגרם ראשי", "account_hint": "@BinaSolutionsAgentBot",
                  "secret": dict(BOT)},
            "dgo_link-macbook": {"protocol": "dgo_link", "label": "pair", "account_hint": "",
                                 "secret": {"token": SECRET}},
            "telegram_bot-copied": {"protocol": "telegram_bot", "label": "a copy", "account_hint": "· from:vps1",
                                    "secret": {"token": "x", "office": "vps1"}}}


MAC = {"x-dgo-office": "macbook", "authorization": f"Bearer {SECRET}"}


def test_the_holder_gives_only_what_it_names_and_only_through_its_door_with_the_pairs_secret():
    app, saved = _holding(f"macbook={IID}", _rows())
    try:
        ok = app.api_link_secret(IID, _Req(MAC))
        assert _status(ok) == 200 and ok["secret"] == BOT and ok["protocol"] == "telegram_bot", ok
        assert ok["label"] == "בוט טלגרם ראשי" and ok["office"] == "hp-laptop", ok
        assert app.api_link_secrets(_Req(MAC))["secrets"] == [IID]
        # a container inside the office, whatever it writes
        assert _status(app.api_link_secret(IID, _Req(MAC, came="172.18.0.99"))) == 403
        # the door's office with the wrong secret, with none, and another office with this pair's secret
        assert _status(app.api_link_secret(IID, _Req({"x-dgo-office": "macbook", "authorization": "Bearer " + "x" * 64}))) == 403
        assert _status(app.api_link_secret(IID, _Req({"x-dgo-office": "macbook"}))) == 403
        assert _status(app.api_link_secret(IID, _Req({"x-dgo-office": "vps1", "authorization": f"Bearer {SECRET}"}))) == 403
    finally:
        _unhold(app, saved)


def test_nothing_unnamed_no_pair_secret_and_no_copy_is_ever_given():
    for given in ("", "vps1=" + IID, "macbook=*", "macbook=telegram_*", f"macbook={IID}x"):
        app, saved = _holding(given, _rows())
        try:
            r = app.api_link_secret(IID, _Req(MAC))
            assert _status(r) == 403 and BOT["token"].encode() not in getattr(r, "body", b""), (given, r)
            assert IID not in app.api_link_secrets(_Req(MAC))["secrets"], given
        finally:
            _unhold(app, saved)
    app, saved = _holding("macbook=dgo_link-macbook,macbook=telegram_bot-copied", _rows())
    try:
        assert _status(app.api_link_secret("dgo_link-macbook", _Req(MAC))) == 403       # a pair's own secret
        assert _status(app.api_link_secret("telegram_bot-copied", _Req(MAC))) == 403    # one hop: a copy stays
    finally:
        _unhold(app, saved)


class _Cv:
    """The puller's link: answers per path."""

    def __init__(self, answers: dict):
        self.answers, self.asked = answers, []

    def _http_auth(self, method, url, token, timeout=30):
        self.asked.append(url.rsplit("9405", 1)[-1])
        return self.answers.get(url.rsplit("9405", 1)[-1], {"_status": 404, "error": "no"})


def _pulling(rows: dict, take: str = f"hp-laptop={IID}"):
    saved = (links.pair_tokens, links._call)
    links.pair_tokens = lambda home, peer: [("dgo_link-hp-laptop", SECRET)] if (home, peer) == ("macbook", "hp-laptop") else []
    links._call = _Vault(rows)
    projection._secret_pulls.clear()
    os.environ["DGO_TAKE_SECRETS"] = take
    return saved


URL = "http://dgo-net:9405/api/link/catalog"
GIVEN = {"/api/link/secrets": {"office": "hp-laptop", "secrets": [IID]},
         f"/api/link/secret/{IID}": {"office": "hp-laptop", "id": IID, "protocol": "telegram_bot",
                                     "label": "בוט טלגרם ראשי", "account_hint": "@BinaSolutionsAgentBot",
                                     "secret": dict(BOT)}}


def test_the_puller_keeps_a_marked_copy_under_the_same_id_protocol_and_label():
    rows = {}
    saved = _pulling(rows)
    try:
        got = projection.pull_secrets(_Cv(GIVEN), {"id": "macbook"}, "hp-laptop", URL, now=1000)
        assert got == {IID: {"ok": True, "changed": True}}, got
        row = rows[IID]
        assert row["protocol"] == "telegram_bot" and row["label"] == "בוט טלגרם ראשי", row
        assert row["secret"] == {**BOT, "office": "hp-laptop"} and "from:hp-laptop" in row["account_hint"], row
        # inside the period: not asked; after it, unchanged is not rewritten
        assert projection.pull_secrets(_Cv(GIVEN), {"id": "macbook"}, "hp-laptop", URL, now=1000 + 60) == {}
        again = projection.pull_secrets(_Cv(GIVEN), {"id": "macbook"}, "hp-laptop", URL,
                                        now=1000 + projection.SECRET_PULL_SECONDS)
        assert again == {IID: {"ok": True, "changed": False}}, again
    finally:
        links.pair_tokens, links._call = saved


def test_the_pullers_own_row_by_that_id_is_never_replaced():
    rows = {IID: {"protocol": "telegram_bot", "label": "mine", "account_hint": "", "secret": {"token": "MINE"}}}
    saved = _pulling(rows)
    try:
        got = projection.pull_secrets(_Cv(GIVEN), {"id": "macbook"}, "hp-laptop", URL, now=1000)
        assert not got[IID]["ok"] and rows[IID]["secret"] == {"token": "MINE"}, (got, rows)
    finally:
        links.pair_tokens, links._call = saved


def test_a_copy_no_longer_given_is_removed_and_nothing_of_this_office_is():
    rows = {IID: {"protocol": "telegram_bot", "label": "בוט טלגרם ראשי", "account_hint": "@x · from:hp-laptop",
                  "secret": {**BOT, "office": "hp-laptop"}},
            "telegram_bot-mine": {"protocol": "telegram_bot", "label": "mine", "account_hint": "", "secret": {"token": "M"}}}
    saved = _pulling(rows)
    try:
        cv = _Cv({"/api/link/secrets": {"office": "hp-laptop", "secrets": []}})
        got = projection.pull_secrets(cv, {"id": "macbook"}, "hp-laptop", URL, now=1000)
        assert got == {IID: {"ok": True, "dropped": True}} and IID not in rows and "telegram_bot-mine" in rows, (got, rows)
    finally:
        links.pair_tokens, links._call = saved


def _offering(iid: str, protocol: str, secret: dict) -> dict:
    return {"/api/link/secrets": {"office": "hp-laptop", "secrets": [iid]},
            f"/api/link/secret/{iid}": {"office": "hp-laptop", "id": iid, "protocol": protocol, "label": "x",
                                        "account_hint": "", "secret": secret}}


def test_a_holder_alone_never_decides_what_lands_here():
    # F1 (the second reader): a compromised holder offers a link row — or anything this office did not name
    evil = {"label": "vps1", "app": "bina-ds", "address": "93.184.216.14", "port": 1}
    for iid, protocol, take in (("dgo_link-x", "dgo_link", "hp-laptop=dgo_link-x"),          # named, link-shaped
                                ("dgo_link-serve-vps1-bina-ds-agent", "telegram_bot",
                                 "hp-laptop=dgo_link-serve-vps1-bina-ds-agent"),            # link-shaped id
                                ("telegram_bot-1", "dgo_link", "hp-laptop=telegram_bot-1"),  # link protocol
                                ("mail_imap-1", "telegram_bot", "hp-laptop=mail_imap-1"),    # id of another kind
                                (IID, "telegram_bot", "")):                                  # offered, not taken
        rows = {}
        saved = _pulling(rows, take)
        try:
            got = projection.pull_secrets(_Cv(_offering(iid, protocol, evil)), {"id": "macbook"}, "hp-laptop", URL, now=1000)
            assert rows == {}, (iid, protocol, take, rows, got)
        finally:
            links.pair_tokens, links._call = saved


def test_a_row_that_is_not_a_copy_is_never_replaced_even_if_its_secret_names_the_holder():
    # F2: an agent credential (or any own row) carries `office: hp-laptop` in its secret — it is still not a copy
    own = {IID: {"protocol": "telegram_bot", "label": "mine", "account_hint": "",
                 "secret": {"token": "OWN", "office": "hp-laptop"}}}
    saved = _pulling(own)
    try:
        got = projection.pull_secrets(_Cv(GIVEN), {"id": "macbook"}, "hp-laptop", URL, now=1000)
        assert not got[IID]["ok"] and own[IID]["secret"] == {"token": "OWN", "office": "hp-laptop"}, (got, own)
    finally:
        links.pair_tokens, links._call = saved


def test_an_unpair_removes_that_offices_copies_and_nothing_else():
    # F3: after an unpair `pull_secrets` never runs for that office again — the copies go with the pair
    rows = {IID: {"protocol": "telegram_bot", "label": "c", "account_hint": "@x · from:hp-laptop",
                  "secret": {**BOT, "office": "hp-laptop"}},
            "telegram_bot-v": {"protocol": "telegram_bot", "label": "v", "account_hint": "· from:vps1",
                               "secret": {"token": "V", "office": "vps1"}},
            "telegram_bot-mine": {"protocol": "telegram_bot", "label": "m", "account_hint": "", "secret": {"token": "M"}}}
    saved = _pulling(rows)
    try:
        projection._secret_pulls["hp-laptop"] = 10 ** 12
        assert projection.forget_secrets("hp-laptop") == [IID] and set(rows) == {"telegram_bot-v", "telegram_bot-mine"}
        assert "hp-laptop" not in projection._secret_pulls
    finally:
        links.pair_tokens, links._call = saved


def test_no_pair_and_a_refused_list_take_nothing():
    rows = {}
    saved = _pulling(rows)
    try:
        none = projection.pull_secrets(_Cv(GIVEN), {"id": "macbook"}, "examplef", URL, now=1000)
        assert none["*"]["ok"] is False and rows == {}, none
        refused = projection.pull_secrets(_Cv({"/api/link/secrets": {"_status": 403, "error": "no"}}),
                                          {"id": "macbook"}, "hp-laptop", URL, now=2000)
        assert refused["*"]["ok"] is False and rows == {}, refused
    finally:
        links.pair_tokens, links._call = saved


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    bad = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as e:                                # noqa: BLE001 — report every test
            bad += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
    print(f"secret_pull: {len(tests)} test(s), {len(tests) - bad} pass, {bad} fail")
    raise SystemExit(1 if bad else 0)
