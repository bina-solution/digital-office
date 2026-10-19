"""dgo-extend.pair_api — pairing two INSTALLED offices from their own screens (DGO-33/34, joined).

Why this module exists
----------------------
`pairing.py` had the cryptography and `static/connect.*` had the screens, and nothing between them:
no route, no place to write the peer, and two different wire formats (measured 2026-10-04 on both
offices — `POST /api/pair/offer` → 404). This is the missing middle. It is the "office first" order of
the same result the `computers` path produces: both offices are already installed, neither holds a
key on the other's machine, and the link is made by two people looking at two screens.

The flow, and why it needs no open port
---------------------------------------
Everything crosses VISUALLY, in both directions:

  1. the JOINER shows an offer (QR / text, `DGOPAIR1:`) — public material only;
  2. the HOST reads it, chooses the pair's slot and who dials, mints the link token, and shows a
     REPLY (QR / text, `DGOPAIRR1:`): its public identity plus a grant sealed to the offer's
     ephemeral key and signed with its identity key;
  3. the JOINER reads the reply; both screens now show the same six digits, derived from the ECDH
     secret, and each operator confirms on their own screen;
  4. on ITS OWN confirmation each office writes the other as a `kind: paired` record, stores the link
     token in the vault, and re-renders its tunnel.

A pairing that needed a rendezvous port would need a firewall rule before the first handshake, on
machines that block every inbound connection by default (Windows/Hyper-V) or cannot receive one at all
(the Mac engine forwards TCP 80/443 to loopback only). The tunnel itself still needs ONE reachable
UDP port on one side — that is `listen` below, and it is the only network fact a pairing carries.

What is deliberately NOT here
-----------------------------
The tunnel. This module writes the record and asks for a render (`ports.render()`); how a record
becomes an interface, a firewall and a delivery plan is `net.py` / `app.render_tunnel`'s.

State
-----
Live offers and claims are IN MEMORY and last ten minutes (`pairing.OFFER_TTL`). A restart of this
app drops them — the operator shows a new code. That is the design ("an offer that survives a restart
is an offer that can be redeemed after the room has emptied"), and every answer that carries an
`expires_at` says so.

A half pair is a state, not an accident: each side writes on its own confirmation, so one office can
hold the record while the other never confirmed. It is visible (`GET /api/pair` lists the record and
the tunnel shows no handshake) and it is undone with `DELETE /api/pair/<office>` on the side that
wrote — which removes the record AND the token, re-renders the tunnel, and compiles, so the
office's tiles and routes leave with it (`compiled` in the answer says how that went).
"""
from __future__ import annotations

import os
import re
import secrets
import threading
import time

import declaration
import pairing

#: How this office is reached for the TUNNEL, when it can be reached at all: a host/IP the other
#: office can dial, and the UDP port published for `dgo-net`. Both from the environment (compose),
#: because a container cannot learn its machine's LAN address by looking — and an office that sets
#: neither simply dials (the Mac engine: nothing inbound is possible there).
LISTEN_ENDPOINT_ENV = "DGO_WG_ENDPOINT"
LISTEN_PORT_ENV = "DGO_WG_PUBLISH_PORT"

#: WHY this office cannot be dialed, when it cannot. It is the other half of the same fact, and it
#: used to be silence: the screen said "this office only dials", the pairing of two such offices was
#: refused after both codes had been exchanged, and the refusal named two environment variables.
#: A container cannot see what kind of machine runs it any more than it can see the LAN address, so
#: this too is said on the machine: `hooks/prepare` records why it declared no address
#: (`DGO_WG_DIAL_ONLY`), and `DGO_WG_AUTO=0` is the owner saying "this office only dials".
DIAL_ONLY_ENV = "DGO_WG_DIAL_ONLY"
AUTO_ENV = "DGO_WG_AUTO"
#: reason → (the cause, what to do). The words both screens show, after their own lead "this office
#: only dials" — so each is a sentence about "her" (the office), never a second statement of the
#: consequence. A `backticked` run is something a person types or looks for; the screens set it
#: apart as a token.
DIAL_ONLY_HE = {
    # The remedy is ONE command, and the sentence still says what that command does — so a person
    # who would rather do it by hand, or whose command fails, is not left with a name and no meaning.
    # (The version is one unbreakable unit: a line that ended in "Windows" and the next that began
    # with "11 22H2" was read off the first screenshot.)
    "wsl-nat": ("Windows מריץ אותה ברשת פנימית, ומחשב אחר ברשת לא מגיע אליה.",
                "כדי שתהיה נגישה: מריצים במחשב הזה `bbox.cmd dialable` ואחריו `bbox.cmd run`. "
                "הפקודה שואלת לפני שהיא משנה משהו: היא כותבת `networkingMode=mirrored` בקובץ `.wslconfig` "
                "של המשתמש ומפעילה מחדש את `WSL`. נדרש Windows 11 22H2 ומעלה."),
    "engine-guest": ("ב-Mac היא רצה בתוך מנוע שמכניס פנימה רק גלישה, ומחשב אחר ברשת לא מגיע אליה.",
                     "לשכות שאפשר לחייג אליהן: על שרת, על מחשב Linux, ועל מחשב Windows שהוגדר לכך."),
    "declared": ("כך הוגדר לה.",
                 "כדי שתהיה נגישה: מוחקים את השורה `DGO_WG_AUTO=0` מהקובץ `.env` ומריצים `bbox run`."),
    "undeclared": ("לא הוצהרה לה כתובת.",
                   "כדי שתהיה נגישה: מגדירים `DGO_WG_ENDPOINT` ו-`DGO_WG_PUBLISH_PORT` בקובץ `.env` שלה "
                   "ופותחים את הפורט בחומת האש של המחשב."),
}


class PairError(RuntimeError):
    """A refusal the screen can show, with the HTTP status it deserves."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def mirror(direction: str) -> str:
    """The same link seen from the other end (`both` is its own mirror) — `converge._mirror`'s rule,
    restated here so the pure half of this module imports nothing but the standard library."""
    return {"use": "serve", "serve": "use"}.get(direction or "use", "both")


def listen_from_env(env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    host = str(env.get(LISTEN_ENDPOINT_ENV) or "").strip().lower()
    if not host:
        return {}
    try:
        port = int(str(env.get(LISTEN_PORT_ENV) or "").strip() or 0)
    except ValueError:
        port = 0
    if not declaration.HOST_RE.match(host) or not 1 <= port <= 65535:
        return {}
    return {"endpoint": host, "port": port}


def listens(record: dict | None) -> bool:
    """Is THIS office the dialed end of that pair? `dial` names the role that dials; `role` is ours."""
    t = (record or {}).get("tunnel") or {}
    return declaration.is_paired(record) and t.get("dial") in declaration.ROLES and t.get("dial") != t.get("role")


def dials(record: dict | None, measured: dict) -> str:
    """The address this office's tunnel reaches a paired office at, as `host:port` — only where this
    office is the end that dials, and only while that pair's handshake is alive (`measured` is the
    tunnel's own reading, by interface). Pure. It is the one measurement there is of where a
    listening office really is, and that office cannot take it itself (`listen_now`)."""
    t = (record or {}).get("tunnel") or {}
    if not declaration.is_paired(record) or t.get("dial") != t.get("role"):
        return ""
    m = (measured or {}).get(f"wg{int(t.get('slot') or 0)}") or {}
    return str(m.get("endpoint") or "") if m.get("alive") else ""


def listen_now(declared: dict, reached: dict) -> dict:
    """Where this office is dialed NOW: what it declares — unless no office that dials it gets
    through there while one does elsewhere. Then it is the address they reach, and `moved_from`
    names what the declaration still says. Pure.

    A lease moves. The declaration is a line of `.env` that the bring-up corrects, and between
    bring-ups nothing on the machine can tell the office (a container does not see its machine's
    address). The office that has just got through to it does know, and says so in its catalog
    answer (`dials`). 2026-10-08: hp-laptop came back from a night offline as .100, went on declaring
    .102, and its own card and its next offer said .102 until somebody ran the office again.
    `reached` is `{office: "ip:port"}`; a value that is not one counts for nothing. And only a
    declared ADDRESS is ever corrected: a declared name is somebody's decision, not a lease — a
    server that says `office.example.org` is reached at the number that name resolves to, and is
    exactly where it says it is."""
    lease = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
    seen = []
    for text in (reached or {}).values():
        host, _, port = str(text or "").strip().rpartition(":")
        if lease.match(host) and port.isdigit() and 1 <= int(port) <= 65535:
            seen.append((host, int(port)))
    if not declared or not lease.match(str(declared.get("endpoint") or "")) or not seen \
            or any(host == declared["endpoint"] for host, _ in seen):
        return declared
    host, port = max(sorted(set(seen)), key=seen.count)
    return {"endpoint": host, "port": port, "moved_from": declared["endpoint"]}


def worded_refusal(exc: BaseException) -> str:
    """The sentence of a refusal raised by the layer BELOW this one, or "" when `exc` is not one.

    `converge.StepFailed` carries `reason` (what is wrong) and `action` (what to do): a refusal a
    person can act on, not a crash. This module's own routes used to let it through as a 500 —
    measured 2026-10-05 on a brand-new office whose identity had not been minted: every pairing
    route answered "Internal Server Error", the office's own card stayed empty and the pairing
    screen said "HTTP 500", while the reason and the remedy were sitting in the exception.
    Duck-typed on purpose: the pure half of this module imports nothing of the app's."""
    reason = str(getattr(exc, "reason", "") or "").strip()
    if not reason:
        return ""
    action = str(getattr(exc, "action", "") or "").strip()
    return (reason.rstrip(".") + ". " + action).strip() if action else reason


def dial_only_why(env: dict | None = None) -> str:
    """Why this office cannot be dialed — a key of DIAL_ONLY_HE — or "" when it can be."""
    env = os.environ if env is None else env
    if listen_from_env(env):
        return ""
    if str(env.get(AUTO_ENV) or "").strip() == "0":
        return "declared"
    why = str(env.get(DIAL_ONLY_ENV) or "").strip().lower()
    return why if why in DIAL_ONLY_HE else "undeclared"


def dialable(peer_endpoint: str, own_endpoint: str = "") -> bool:
    """Can THIS office dial the address a peer published — `net.dialable_from_here`, asked where the
    decision is taken.

    The predicate lives in `net` beside `lan_address` (one owner for "what counts as a local
    address", and the same answer is needed by the heal and by the verdict), and it is imported
    here, inside the function, because this module's pure half holds its imports to the standard
    library plus `pairing` and `declaration` — the flow is testable without an app around it.
    """
    import net as netmod
    return netmod.dialable_from_here(peer_endpoint, own_endpoint)


def _digits(code) -> str:
    return "".join(ch for ch in str(code or "") if ch.isdigit())


def _public(identity: dict) -> dict:
    """The three fields of an identity that cross the wire — nothing else of the record."""
    return {"ed25519": identity.get("ed25519") or "", "wg": identity.get("wg") or "",
            "fingerprint": identity.get("fingerprint") or ""}


#: What `home.json` holds before anybody named the office. It is the office's word for ITSELF, so
#: published to a peer it titles the peer's card "this office" — measured 2026-10-05: the laptop,
#: which nobody had named, was a card called „הלשכה הזאת” on the MacBook's screen.
UNNAMED = ("", "הלשכה הזאת", "הלשכה הזו", "local")


#: The `serve:` map's own vocabulary (catalog.py owns it; restated because this module's pure half
#: imports nothing of the app): `"*"` = every app this office runs, and the keys that are not apps.
WILDCARD = "*"
SERVE_RESERVED = ("exclude", "only", "label", "identity")


def own_label(home: dict) -> str:
    """The name this office gives itself to another office: its label, or its ID while unnamed."""
    label = home.get("label")
    if isinstance(label, dict):
        label = label.get("he") or label.get("en")
    label = " ".join(str(label or "").split())
    return (label if label not in UNNAMED else str(home.get("id") or ""))[:60]


class Pairing:
    """Both roles of a pairing, over a small set of PORTS the app supplies.

    `ports` is an object with: `home()` → this office's record (id, label, public identity, tunnel);
    `identity_private()` → the Ed25519 private key as stored (base64 of the raw 32 bytes);
    `declarations()` → every peer record; `save(doc)` / `delete(oid)`; `vault_put(name, secret, label)`
    / `vault_delete(name)`; `render()` → what the tunnel render answered; `listen()` → `{endpoint,
    port}` or `{}`. Kept behind ports so the whole flow runs in a test with two in-memory offices and
    no web stack — a rule that can only be exercised through HTTP is a rule the gate cannot measure.
    """

    def __init__(self, ports, now=time.time):
        self.ports = ports
        self.now = now
        self.offers = pairing.Offers(now=now)
        self.claims: dict[str, dict] = {}
        #: offer id → the link it became, kept so the joiner's poll can answer `confirmed` with it
        self._confirmed: dict[str, dict] = {}
        self.lock = threading.RLock()

    # ── shared ──────────────────────────────────────────────────────────────────────────────────
    def _home(self) -> dict:
        home = self.ports.home()
        if not pairing.OFFICE_RE.match(str(home.get("id") or "")):
            raise PairError(f"מזהה הלשכה הזאת ({home.get('id')!r}) אינו תקין לצימוד — הגדירו DGO_OFFICE_ID", 409)
        if not (home.get("identity") or {}).get("ed25519"):
            raise PairError("אין זהות ללשכה הזאת — הריצו `bbox dgo identity mint`", 409)
        return home

    def _taken_slots(self, except_id: str = "") -> set[int]:
        """Every pair slot this office already uses: its records' (paired or installed), its own
        home slot — the legacy single-pair form numbers the pair by the home slot, so a new pair
        that took it would collide with a link that exists today — and the slot of every tunnel
        ADDRESS it holds (`ports.addresses()`). The far end of a link another office converged has
        the tunnel on its machine and no record of it, so its offer named nothing and the new pair
        was given that very slot: 2026-10-08, hp-laptop with vps1 on slot 2 — the slot of vps1's link
        with the MacBook. Two tunnels on one /24 there, vps1's packets for the MacBook left through
        the new one, and every app of hers was «Bad Gateway»."""
        taken = set()
        for addr in self.ports.addresses():
            m = re.match(r"^10\.79\.(\d{1,3})\.\d{1,3}$", str(addr or ""))
            if m:
                taken.add(int(m.group(1)))
        for d in self.ports.declarations():
            if d.get("id") == except_id:
                continue
            try:
                taken.add(int((d.get("tunnel") or {}).get("slot") or 0))
            except (TypeError, ValueError):
                continue
        try:
            taken.add(int((self.ports.home().get("tunnel") or {}).get("slot") or 0))
        except (TypeError, ValueError):
            pass
        taken.discard(0)
        return taken

    def _existing(self, oid: str) -> dict | None:
        for d in self.ports.declarations():
            if d.get("id") == oid:
                return d
        return None

    def _guard_replace(self, oid: str, pair_id: str, replace: bool) -> None:
        """A pairing never silently overwrites a record. The same pairing confirmed twice is
        idempotent (same `pair_id`); anything else under that id — another pairing, or an office this
        one INSTALLED on a machine — needs an explicit `replace`, or the pairing would orphan a
        converge target without saying so."""
        have = self._existing(oid)
        if not have or have.get("pair_id") == pair_id or replace:
            return
        what = ("לשכה שהלשכה הזאת התקינה על מחשב (יש לה machine/path)"
                if not declaration.is_paired(have) else "צימוד קודם")
        raise PairError(f"כבר קיימת כאן רשומה בשם {oid} — {what}. כדי להחליף אותה שלחו replace: true.", 409)

    def _write(self, record: dict, token: str, replace_id: str) -> dict:
        home = self._home()
        clean, err = declaration.validate_paired(record, home["id"],
                                                 taken_slots=self._taken_slots(except_id=replace_id))
        if err:
            raise PairError(err, 400)
        peer = clean["id"]
        # The token first: a record without its token is a link nothing can authorize, while a token
        # without a record is one vault row the next attempt overwrites.
        self.ports.vault_put(f"dgo_link-{peer}",
                             {"token": token, "office": home["id"], "peer": peer,
                              "direction": mirror(clean["links"][0]["direction"]),
                              "pair_id": clean["pair_id"], "created_at": int(self.now())},
                             f"קישור {home['id']} ↔ {peer}")
        self.ports.save(clean)
        # A LINK IN WHICH THIS OFFICE GIVES NEEDS SOMETHING TO GIVE. `serve:` is what opens the catalog
        # and the door on the tunnel side; an office that never declared one answers nothing there, so
        # the office it had just paired with showed it as DOWN over a healthy tunnel (measured
        # 2026-10-05: hp-laptop on the MacBook's screen). The owner's rule is "all apps appear": an
        # office with no declaration gives everything, and one that already chose is left alone.
        gave_all = False
        if mirror(clean["links"][0]["direction"]) in ("serve", "both") \
                and not self._gives_anything() and not self._chose():
            try:
                self._declare({WILDCARD: {}})
                gave_all = True
            except PairError:
                pass                                       # an office that cannot declare still pairs
        rendered = self.ports.render()
        t = clean["tunnel"]
        return {"ok": True,
                "link": {"id": peer, "office": peer, "label": clean["label"], "pair_id": clean["pair_id"],
                         "direction": mirror(clean["links"][0]["direction"]),
                         "slot": t["slot"], "side": t["side"], "role": t["role"], "dial": t["dial"],
                         "endpoint": t["endpoint"], "port": t["port"],
                         "fingerprint": clean["identity"]["fingerprint"]},
                "gave_all": gave_all, "render": rendered}

    # ── what this office GIVES (its own `serve:` declaration, as a person chooses it) ────────────
    def _serve(self) -> dict:
        get = getattr(self.ports, "serve", None)
        doc = get() if get else {}
        return dict(doc) if isinstance(doc, dict) else {}

    def _gives_anything(self) -> bool:
        return any(k not in SERVE_RESERVED for k in self._serve())

    def _chose(self) -> bool:
        """Did a PERSON decide what this office gives? An empty `serve:` means two different things —
        "nobody was ever asked" and "the owner chose to give nothing" — and only the first may be
        filled in by a pairing. The choice is therefore remembered apart from the map."""
        asked = getattr(self.ports, "chose_giving", None)
        try:
            return bool(asked()) if asked else False
        except Exception:  # noqa: BLE001 — an unreadable marker is "not chosen", never a failed pairing
            return False

    def _declare(self, serve: dict) -> dict:
        put = getattr(self.ports, "set_serve", None)
        if not put:
            raise PairError("הלשכה הזאת אינה יודעת להצהיר מה היא נותנת (גרסה ישנה)", 501)
        return put(serve)

    def _publishable(self) -> list[dict]:
        """This office's own apps, from its compiled registry — the only list of "our apps"."""
        get = getattr(self.ports, "publishable", None)
        out = []
        for r in (get() if get else []) or []:
            if not isinstance(r, dict):
                continue
            alias = str(r.get("alias") or "").strip().lower()
            if not alias:
                continue
            out.append({"alias": alias, "app": str(r.get("app") or alias).strip().lower(),
                        "name": str(r.get("name") or alias), "port": r.get("port"),
                        "agent_api_port": r.get("agent_api_port")})
        return out

    def giving(self) -> dict:
        """What THIS office gives to the offices linked to it, as a person reads it: every app it
        runs (`all`), a chosen few (`some`) or nothing (`none`). It is one declaration for the whole
        office, so the screen shows it on the office's own card — and `only` beside it is the one
        thing that is per office: the offices given LESS than that, each with its own list
        (`serve.only`, catalog.only_for)."""
        serve = self._serve()
        every = WILDCARD in serve
        raw_skip = serve.get("exclude") if isinstance(serve.get("exclude"), list) else []
        skip = {str(x).strip().lower() for x in raw_skip if str(x).strip()}
        named = {str(k).strip().lower() for k in serve if k not in SERVE_RESERVED and k != WILDCARD}
        apps = []
        for r in self._publishable():
            names = {r["alias"], r["app"]}
            given = (every and not (skip & names)) or bool(named & names)
            apps.append({"alias": r["alias"], "app": r["app"], "name": r["name"], "given": given})
        count = sum(1 for a in apps if a["given"])
        mode = "all" if every and not skip else ("none" if not count else "some")
        # `chosen`: false while an empty declaration is only "nobody was asked yet" — the next pairing
        # in which this office gives will then give everything, and the screen says so beforehand.
        only = serve.get("only") if isinstance(serve.get("only"), dict) else {}
        return {"mode": mode, "count": count, "total": len(apps), "apps": apps,
                "only": {str(o): list(names or []) for o, names in only.items()},
                "chosen": bool(self._gives_anything() or self._chose())}

    def give(self, mode: str, apps=None) -> dict:
        """Declare what this office gives. `all` = every app, the ones installed later included;
        `some` = exactly the named ones (a new app is NOT given until somebody ticks it); `none` =
        nothing — the links stay, the doors close."""
        mode = str(mode or "").strip()
        serve = self._serve()
        if mode == "all":
            new: dict = {WILDCARD: {}}
        elif mode == "none":
            new = {}
        elif mode == "some":
            rows = self._publishable()
            by_name = {}
            for r in rows:
                by_name.setdefault(r["alias"], r)
                by_name.setdefault(r["app"], r)
            wanted: list[dict] = []
            for a in apps or []:
                row = by_name.get(str(a or "").strip().lower())
                if not row:
                    raise PairError(f"„{a}” אינה אפליקציה שהלשכה הזאת מריצה", 400)
                if row not in wanted:
                    wanted.append(row)
            if not wanted:
                raise PairError("לא נבחרה אף אפליקציה — בחרו לפחות אחת, או „לא לתת דבר”", 400)
            new = {}
            for row in wanted:
                have = serve.get(row["app"]) or serve.get(row["alias"])
                if isinstance(have, dict) and have.get("port"):
                    new[row["app"]] = have                  # what was declared about that app stays
                    continue
                try:
                    port = int(row.get("port"))
                except (TypeError, ValueError):
                    raise PairError(f"לאפליקציה „{row['name']}” אין פורט ברישום של הלשכה", 400) from None
                spec = {"port": port}
                try:
                    api = int(row.get("agent_api_port"))
                    if 1 <= api <= 65535 and api != port:
                        spec["agent_api_port"] = api
                except (TypeError, ValueError):
                    pass
                new[row["app"]] = spec
        else:
            raise PairError("mode חייב להיות all, some או none", 400)
        with self.lock:
            self._declare(new)
            mark = getattr(self.ports, "mark_giving", None)
            if mark:
                mark()
            rendered = self.ports.render()
        return {"ok": True, "giving": self.giving(), "render": rendered}

    # ── the JOINER: show an offer, read the reply, confirm ──────────────────────────────────────
    def offer(self, direction: str = "", label: str = "") -> dict:
        home = self._home()
        listen = self.ports.listen() or {}
        extra = {"label": str(label or own_label(home))[:60],
                 "used_slots": sorted(self._taken_slots())}
        if direction in ("use", "serve", "both"):
            extra["direction"] = direction
        endpoints = []
        if listen:
            extra["listen"] = {"endpoint": listen["endpoint"], "port": int(listen["port"])}
            endpoints = [f"{listen['endpoint']}:{int(listen['port'])}"]
        with self.lock:
            self.offers.gc()
            try:
                offer, priv = pairing.new_offer(home["id"], _public(home["identity"]), endpoints,
                                                now=self.now(), extra=extra)
            except pairing.PairingError as e:
                raise PairError(str(e), 400) from e
            self.offers.add(offer, priv)
        return {"rendezvous_id": offer["offer_id"], "text": pairing.offer_text(offer), "offer": offer,
                "expires_at": offer["expires_at"], "listens": bool(listen),
                "note": "ההצעה חיה בזיכרון עשר דקות; אתחול של האפליקציה מבטל אותה."}

    def offer_state(self, rid: str) -> dict:
        with self.lock:
            state = self.offers.state(rid)
            if state in ("unknown", "expired"):
                return {"state": "expired"}
            if state == "confirmed":
                return {"state": "confirmed", "link": (self._confirmed.get(rid) or {})}
            row = self.offers.get(rid)
            out = {"state": state, "expires_at": row["expires_at"]}
            if row.get("claim"):
                out.update({"code": row["claim"]["code"], "peer": row["claim"]["peer"]})
            return out

    def offer_reply(self, text: str, rid: str = "") -> dict:
        try:
            reply = pairing.parse_reply(text)
        except pairing.PairingError as e:
            raise PairError(str(e), 400) from e
        offer_id = str(reply.get("offer_id") or "")
        if rid and rid != offer_id:
            raise PairError("קוד התשובה שייך להצעה אחרת מזו שמוצגת כאן", 409)
        with self.lock:
            try:
                row = self.offers.get(offer_id)
                grant, code = pairing.open_reply(row["offer"], row["priv"], reply, now=self.now())
                home = self._home()
                if grant.get("joiner") != home["id"]:
                    raise pairing.PairingError("התשובה נכתבה ללשכה אחרת")
                host = str(grant.get("host") or "")
                if not pairing.OFFICE_RE.match(host):
                    raise pairing.PairingError("מזהה הלשכה המארחת שבתשובה אינו תקין")
                peer = {"office_id": host, "label": str(grant.get("label") or host)[:60],
                        "fingerprint": (reply.get("identity") or {}).get("fingerprint") or ""}
                self.offers.claim(offer_id, reply_sig=reply.get("sig"), code=code, grant=grant,
                                  identity=_public(reply.get("identity") or {}), peer=peer)
            except pairing.PairingError as e:
                raise PairError(str(e), 400) from e
        return {"state": "claimed", "rendezvous_id": offer_id, "code": code, "peer": peer,
                "expires_at": row["expires_at"]}

    def offer_confirm(self, rid: str, code, replace: bool = False) -> dict:
        with self.lock:
            try:
                row = self.offers.get(rid)
            except pairing.PairingError as e:
                raise PairError(str(e), 404) from e
            claim = row.get("claim")
            if not claim:
                raise PairError("עוד לא נקרא קוד התשובה של הלשכה המארחת — סרקו או הדביקו אותו קודם", 409)
            if _digits(code) != claim["code"]:
                raise PairError("קוד האישור אינו תואם — הצימוד לא נכתב", 400)
            grant, home = claim["grant"], self._home()
            host = grant["host"]
            self._guard_replace(host, row["offer"]["offer_id"], replace)
            t = grant.get("tunnel") or {}
            record = {"id": host, "label": claim["peer"]["label"], "kind": declaration.PAIRED,
                      "pair_id": row["offer"]["offer_id"], "identity": claim["identity"],
                      "tunnel": {"slot": t.get("slot"), "side": 2, "role": "joiner",
                                 "dial": t.get("dial"), "endpoint": t.get("endpoint"),
                                 "port": t.get("port")},
                      # the record's link is written from the PEER's point of view (the convention
                      # every reader of `links[]` follows) — and the grant's direction IS the host's.
                      "links": [{"office": home["id"], "direction": grant.get("direction")}],
                      "paired_at": int(self.now())}
            out = self._write(record, grant["token"], replace_id=host)
            self.offers.use(rid)
            self._confirmed[rid] = out["link"]
            return out

    def offer_cancel(self, rid: str) -> dict:
        with self.lock:
            self.offers.cancel(rid)
        return {"ok": True}

    # ── the HOST: read an offer, show the reply, confirm ────────────────────────────────────────
    def claim(self, text: str, direction: str = "", replace: bool = False) -> dict:
        home = self._home()
        try:
            offer = pairing.parse_offer(text)
            if pairing.is_expired(offer, self.now()):
                raise pairing.PairingError("הצעת הצימוד פגה (10 דקות) — הציגו הצעה חדשה בלשכה המצטרפת")
        except pairing.PairingError as e:
            raise PairError(str(e), 400) from e
        joiner = offer["office"]
        if joiner == home["id"]:
            raise PairError("זו ההצעה של הלשכה הזאת עצמה — סרקו אותה מהלשכה השנייה", 400)
        if offer["identity"].get("ed25519") == home["identity"].get("ed25519"):
            raise PairError("ההצעה נושאת את הזהות של הלשכה הזאת — שתי לשכות אינן חולקות מפתח", 400)
        # The direction is the HOST's sentence ("this office will use / serve / both"). An offer that
        # asked for one is honoured when the host says nothing; it never overrides what the host chose.
        if direction not in ("use", "serve", "both"):
            direction = mirror(str(offer.get("direction") or "")) if offer.get("direction") in (
                "use", "serve", "both") else "both"
        self._guard_replace(joiner, offer["offer_id"], replace)

        # WHO DIALS is decided once, here, and written into the grant: the side that published a
        # reachable UDP address listens. The dialing side's own port is never published (a home NAT
        # rewrites it — measured 51830 → 51908 — so it would be an address that reaches nobody).
        #
        # AND REACHABLE MEANS REACHABLE FROM HERE (2026-10-12, lnk-032). "She published an address"
        # is not the same fact as "this office can dial it": a peer at home publishes the address its
        # own LAN knows it by, and a cloud office has no packet that arrives there. Preferring that
        # address anyway wrote a pair that could not carry a byte — the reachable office was made the
        # dialer and the unreachable one the listener — and every screen said "paired". So a private
        # address of the joiner's is chosen only when this office could be on that network; when it
        # cannot, the pair is written the other way round (this office listens, the joiner dials the
        # address this office published), and when neither is possible it is refused in words.
        theirs = offer.get("listen") if isinstance(offer.get("listen"), dict) else {}
        mine = self.ports.listen() or {}
        if theirs.get("endpoint") and theirs.get("port") \
                and dialable(theirs["endpoint"], mine.get("endpoint") or ""):
            dial, endpoint, port = "host", str(theirs["endpoint"]).strip().lower(), theirs["port"]
        elif mine:
            dial, endpoint, port = "joiner", mine["endpoint"], mine["port"]
        else:
            # Said in the product's words, and it sends each operator to their OWN office's card: the
            # reason is a fact of each machine (`dial_only`), and only that office can state it.
            raise PairError(
                "אי אפשר לצמד את שתי הלשכות האלה ישירות: שתיהן רק מחייגות, ואין מי שיקבל את החיוג. "
                "אחת מהן צריכה להיות נגישה — מסך „לשכות” של כל אחת אומר למה היא אינה נגישה ומה לעשות.", 409)

        taken = self._taken_slots(except_id=joiner)
        for s in (offer.get("used_slots") or []):
            try:
                taken.add(int(s))
            except (TypeError, ValueError):
                continue
        slot = next((s for s in range(1, 255) if s not in taken), 0)
        if not slot:
            raise PairError("אין slot פנוי (1–254) בשתי הלשכות", 409)

        token = secrets.token_hex(32)
        tunnel = {"slot": slot, "dial": dial, "endpoint": endpoint, "port": int(port)}
        try:
            reply = pairing.accept(offer, home["id"],
                                   pairing.ed25519_private_der(self.ports.identity_private()),
                                   _public(home["identity"]), token=token, direction=direction,
                                   tunnel=tunnel, now=self.now(),
                                   extra={"label": own_label(home)})
        except pairing.PairingError as e:
            raise PairError(str(e), 400) from e
        rid = offer["offer_id"]
        peer = {"office_id": joiner, "label": str(offer.get("label") or joiner)[:60],
                "fingerprint": offer["identity"].get("fingerprint") or ""}
        with self.lock:
            self._gc_claims()
            self.claims[rid] = {"offer": offer, "token": token, "direction": direction,
                                "tunnel": tunnel, "code": reply["host_sas"], "peer": peer,
                                "reply_text": pairing.reply_text(reply),
                                "expires_at": int(offer["expires_at"]), "replace": bool(replace)}
        return {"rendezvous_id": rid, "code": reply["host_sas"], "peer": peer, "offer": offer,
                "reply_text": pairing.reply_text(reply), "direction": direction, "tunnel": tunnel,
                "expires_at": int(offer["expires_at"]),
                "note": "הבקשה חיה בזיכרון עד שההצעה פגה; אתחול של האפליקציה מבטל אותה."}

    def claim_state(self, rid: str) -> dict:
        """What the host is showing for a live claim — the reply to hand over and the six digits —
        for a reader with no screen (a CLI, an agent driving a headless browser). Never the token:
        it is inside the sealed reply and nowhere else."""
        with self.lock:
            self._gc_claims()
            c = self.claims.get(rid)
            if not c:
                return {"state": "expired"}
            return {"state": "claimed", "rendezvous_id": rid, "code": c["code"], "peer": c["peer"],
                    "reply_text": c["reply_text"], "direction": c["direction"], "tunnel": c["tunnel"],
                    "expires_at": c["expires_at"]}

    def _gc_claims(self) -> None:
        now = self.now()
        for rid in [r for r, c in self.claims.items() if now > c["expires_at"]]:
            self.claims.pop(rid, None)

    def claim_confirm(self, rid: str, code, replace: bool = False) -> dict:
        with self.lock:
            self._gc_claims()
            c = self.claims.get(rid)
            if not c:
                raise PairError("אין כאן בקשת צימוד חיה במזהה הזה (אולי היא פגה, או שהאפליקציה אותחלה)", 404)
            if _digits(code) != c["code"]:
                raise PairError("קוד האישור אינו תואם — הצימוד לא נכתב", 400)
            home, offer, t = self._home(), c["offer"], c["tunnel"]
            self._guard_replace(offer["office"], offer["offer_id"], replace or c["replace"])
            record = {"id": offer["office"], "label": c["peer"]["label"], "kind": declaration.PAIRED,
                      "pair_id": offer["offer_id"], "identity": _public(offer["identity"]),
                      "tunnel": {"slot": t["slot"], "side": 1, "role": "host", "dial": t["dial"],
                                 "endpoint": t["endpoint"], "port": t["port"]},
                      "links": [{"office": home["id"], "direction": mirror(c["direction"])}],
                      "paired_at": int(self.now())}
            out = self._write(record, c["token"], replace_id=offer["office"])
            self.claims.pop(rid, None)
            return out

    # ── what exists, and taking it away ─────────────────────────────────────────────────────────
    def _peer_label(self, d: dict) -> str:
        """The name a person reads for a PAIRED office: what it publishes about itself now (the
        catalog this office last pulled), then what it said when it paired, then its id.

        A paired record's label is the PEER's own word, taken once — so the fresher word wins, which
        is the opposite of an installed office (whose label is this office's owner's). And neither
        word is trusted to be a name: an office nobody named says „הלשכה הזאת” about itself.
        """
        live = ""
        published = getattr(self.ports, "published_label", None)
        if published:
            try:
                live = " ".join(str(published(d["id"]) or "").split())
            except Exception:  # noqa: BLE001 — an unreadable catalog is "no fresher name", not a failure
                live = ""
        for name in (live, " ".join(str(d.get("label") or "").split())):
            if name and name not in UNNAMED:
                return name[:60]
        return str(d["id"])

    def _self(self) -> dict:
        home = self.ports.home()
        name = own_label(home)
        return {"id": home.get("id"), "label": name,
                # `named` is what lets a screen say "this office has no name yet" instead of showing
                # an id as if somebody had chosen it
                "named": bool(name) and name != str(home.get("id") or ""),
                "fingerprint": (home.get("identity") or {}).get("fingerprint")}

    def rename(self, label: str) -> dict:
        """Name THIS office — the one string every linked office shows for it."""
        label = " ".join(str(label or "").split())
        if not 1 <= len(label) <= 60:
            raise PairError("שם הלשכה חייב להיות באורך של 1 עד 60 תווים", 400)
        if label in UNNAMED:
            raise PairError("זה לא שם — בחרו שם שיזהה את הלשכה הזאת בלשכה אחרת", 400)
        if any(ord(ch) < 32 for ch in label) or any(ch in label for ch in "<>"):
            raise PairError("שם הלשכה מכיל תווים שאינם מותרים", 400)
        with self.lock:
            self.ports.set_label(label)
        return {"ok": True, "home": self._self()}

    def listing(self) -> dict:
        items = []
        for d in self.ports.declarations():
            if not declaration.is_paired(d):
                continue
            t = d.get("tunnel") or {}
            link = (d.get("links") or [{}])[0]
            items.append({"office": d["id"], "label": self._peer_label(d), "pair_id": d.get("pair_id"),
                          "fingerprint": (d.get("identity") or {}).get("fingerprint"),
                          "direction": mirror(link.get("direction")), "slot": t.get("slot"),
                          "side": t.get("side"), "role": t.get("role"), "dial": t.get("dial"),
                          "endpoint": t.get("endpoint"), "port": t.get("port"),
                          "paired_at": d.get("paired_at")})
        return {"home": self._self(), "listen": self.ports.listen() or None,
                "dial_only": self._dial_only(), "items": items}

    def _dial_only(self) -> dict | None:
        """Why this office cannot be dialed and what would change that — None when it can be."""
        if self.ports.listen():
            return None
        ask = getattr(self.ports, "dial_only", None)
        why = (ask() if ask else "") or "undeclared"
        if why not in DIAL_ONLY_HE:
            why = "undeclared"
        reason, fix = DIAL_ONLY_HE[why]
        return {"why": why, "reason": reason, "fix": fix}

    def unpair(self, oid: str) -> dict:
        have = self._existing(oid)
        if not have:
            raise PairError("אין כאן לשכה מצומדת בשם הזה", 404)
        if not declaration.is_paired(have):
            raise PairError(f"{oid} היא לשכה שהותקנה מכאן, לא צימוד — מסירים אותה במסך הלשכות", 409)
        self.ports.delete(oid)
        self.ports.vault_delete(f"dgo_link-{oid}")
        # …and her tiles and routes with them (`compiled`): the tunnel first, then the compile
        return {"ok": True, "office": oid, "render": self.ports.render(), "compiled": self.ports.compile(),
                "note": "הרשומה והאסימון הוסרו כאן. הלשכה השנייה מסירה את הצד שלה באותה פעולה אצלה."}


# ── the HTTP face ────────────────────────────────────────────────────────────────────────────────
def build_router(engine: Pairing):
    """The routes `static/connect.js` speaks. Built by a function so importing this module needs no
    web stack — the gate imports the class above and never touches FastAPI."""
    from fastapi import APIRouter, Request
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import JSONResponse

    # `from __future__ import annotations` turns `request: Request` into the STRING "Request", which
    # FastAPI resolves in this module's globals — where a function-local import is invisible, so the
    # parameter is read as a required query field and every call answers 422 (measured on the first
    # live call). The name is therefore published to the module once the web stack is known to exist.
    globals()["Request"] = Request

    router = APIRouter()

    async def body_of(request: Request) -> dict:
        try:
            doc = (await request.json()) if await request.body() else {}
        except ValueError:
            doc = {}
        return doc if isinstance(doc, dict) else {}

    async def run(fn, *args, **kwargs):
        try:
            return await run_in_threadpool(lambda: fn(*args, **kwargs))
        except PairError as e:
            return JSONResponse({"error": str(e)}, status_code=e.status)
        except Exception as e:  # noqa: BLE001 — only a WORDED refusal is answered; see worded_refusal
            said = worded_refusal(e)
            if not said:
                raise                                   # not a refusal: a bug, and it stays a 500
            return JSONResponse({"error": said}, status_code=409)

    @router.get("/api/pair")
    async def pair_list():
        return await run(engine.listing)

    @router.post("/api/pair/home")
    async def pair_home(request: Request):
        b = await body_of(request)
        return await run(engine.rename, str(b.get("label") or ""))

    @router.get("/api/pair/giving")
    async def pair_giving():
        return await run(engine.giving)

    @router.post("/api/pair/giving")
    async def pair_give(request: Request):
        b = await body_of(request)
        return await run(engine.give, str(b.get("mode") or ""),
                         b.get("apps") if isinstance(b.get("apps"), list) else [])

    @router.post("/api/pair/offer")
    async def pair_offer(request: Request):
        b = await body_of(request)
        return await run(engine.offer, str(b.get("direction") or ""), str(b.get("label") or ""))

    @router.get("/api/pair/offer/{rid}")
    async def pair_offer_state(rid: str):
        return await run(engine.offer_state, rid)

    @router.post("/api/pair/offer/{rid}/reply")
    async def pair_offer_reply(rid: str, request: Request):
        b = await body_of(request)
        return await run(engine.offer_reply, str(b.get("text") or ""), rid)

    @router.post("/api/pair/reply")
    async def pair_reply(request: Request):
        # The same act without the id in the path: a reply pasted on a freshly opened screen names
        # its own offer, and the screen that reads it has no `rid` in memory to put in a URL.
        b = await body_of(request)
        return await run(engine.offer_reply, str(b.get("text") or ""), "")

    @router.post("/api/pair/offer/{rid}/confirm")
    async def pair_offer_confirm(rid: str, request: Request):
        b = await body_of(request)
        return await run(engine.offer_confirm, rid, b.get("code"), bool(b.get("replace")))

    @router.post("/api/pair/offer/{rid}/cancel")
    async def pair_offer_cancel(rid: str):
        return await run(engine.offer_cancel, rid)

    @router.post("/api/pair/claim")
    async def pair_claim(request: Request):
        b = await body_of(request)
        return await run(engine.claim, str(b.get("text") or ""), str(b.get("direction") or ""),
                         bool(b.get("replace")))

    @router.get("/api/pair/claim/{rid}")
    async def pair_claim_state(rid: str):
        return await run(engine.claim_state, rid)

    @router.post("/api/pair/claim/{rid}")
    async def pair_claim_confirm(rid: str, request: Request):
        b = await body_of(request)
        if not b.get("confirm"):
            return JSONResponse({"error": "האישור חייב להיות מפורש (confirm: true)"}, status_code=400)
        return await run(engine.claim_confirm, rid, b.get("code"), bool(b.get("replace")))

    @router.delete("/api/pair/{oid}")
    async def pair_unpair(oid: str):
        if not re.match(r"^[a-z][a-z0-9-]{1,30}$", oid):
            return JSONResponse({"error": "מזהה לשכה לא תקין"}, status_code=400)
        return await run(engine.unpair, oid)

    return router


# ── the gate's half: two offices in memory, one pairing, every refusal ───────────────────────────
class _MemoryPorts:
    """An office with no disk, no vault and no tunnel — enough to run the whole flow."""

    def __init__(self, oid: str, label: str, slot: int, listen: dict | None = None, addresses=()):
        import base64
        self._addresses = list(addresses)
        priv, pub = pairing._ed25519_keypair()
        self._priv = base64.b64encode(priv[-32:]).decode()
        wg = base64.b64encode(secrets.token_bytes(32)).decode()
        self._home = {"id": oid, "label": label, "tunnel": {"slot": slot},
                      "identity": {"ed25519": base64.b64encode(pub[-32:]).decode(), "wg": wg,
                                   "fingerprint": f"{oid[:4].upper()}-TEST"}}
        self._listen = listen or {}
        self.why = ""
        self.records: dict[str, dict] = {}
        self.vault: dict[str, dict] = {}
        self.published: dict[str, str] = {}
        self.served: dict = {}
        self.chose = False
        self.registry = [{"alias": "bina", "app": "bina-ds", "name": "בינה", "port": 3080, "agent_api_port": 3081},
                         {"alias": "drive", "app": "drive", "name": "מסמכים", "port": 8975},
                         {"alias": "machine", "app": "machine", "name": "מכונה", "port": 8080}]
        self.renders = self.compiles = 0

    def home(self): return self._home
    def identity_private(self): return self._priv
    def declarations(self): return list(self.records.values())
    def addresses(self): return self._addresses
    def save(self, doc): self.records[doc["id"]] = doc
    def delete(self, oid): self.records.pop(oid, None)
    def vault_put(self, name, secret, label): self.vault[name] = secret
    def vault_delete(self, name): self.vault.pop(name, None)
    def listen(self): return self._listen
    def dial_only(self): return self.why
    def set_label(self, label): self._home["label"] = label
    def serve(self): return self.served
    def publishable(self): return self.registry
    def set_serve(self, serve): self.served = dict(serve); return self.served
    def chose_giving(self): return self.chose
    def mark_giving(self): self.chose = True
    def published_label(self, oid): return self.published.get(oid, "")
    def compile(self): self.compiles += 1; return {"ran": True, "ok": True}
    def render(self):
        self.renders += 1
        return {"rendered": [{"office": self._home["id"], "ok": True}]}


def selftest() -> list[str]:
    problems = []

    def refused(name, fn, *a, **k):
        try:
            fn(*a, **k)
            problems.append(f"must be refused: {name}")
        except PairError:
            pass

    # the pair of the owner's own case: the laptop listens, the Mac can only dial, and the Mac
    # already holds slot 2 (its link to vps1) plus an INSTALLED record under the laptop's id
    hp = _MemoryPorts("hp-laptop", "HP", slot=1, listen={"endpoint": "192.168.16.102", "port": 51830})
    mac = _MemoryPorts("macbook", "MacBook", slot=2)
    mac.records["vps1"] = {"id": "vps1", "machine": "computer_ssh-1", "tunnel": {"slot": 2}}
    mac.records["hp-laptop"] = {"id": "hp-laptop", "machine": "computer_ssh-2", "tunnel": {"slot": 3}}
    joiner, host = Pairing(hp), Pairing(mac)

    off = joiner.offer("serve")
    if "token" in off["text"] or off["offer"].get("listen", {}).get("port") != 51830:
        problems.append("the offer carries the joiner's listen address and nothing secret")
    refused("the joiner claiming its own offer", joiner.claim, off["text"])
    refused("an installed office overwritten without `replace`", host.claim, off["text"])
    cl = host.claim(off["text"], replace=True)
    if cl["tunnel"] != {"slot": 3, "dial": "host", "endpoint": "192.168.16.102", "port": 51830}:
        problems.append(f"the host dials the joiner's published address, on a slot free on both: {cl['tunnel']}")
    if cl["direction"] != "use":
        problems.append("an offer that asked to SERVE is, from the host, a link the host USES")
    if not cl["reply_text"].startswith(pairing.REPLY_PREFIX):
        problems.append("the claim answers the reply as text, under the reply's own prefix")
    if "token" in cl or mac.vault:
        problems.append("the link token is never in an API answer, and nothing is stored before the confirmation")

    seen = host.claim_state(cl["rendezvous_id"])
    if seen.get("reply_text") != cl["reply_text"] or seen.get("code") != cl["code"] or "token" in seen:
        problems.append("a live claim can be read back (reply + code) without a screen, and never its token")
    if host.claim_state("0" * 32).get("state") != "expired":
        problems.append("an unknown claim reads as expired")
    refused("confirming before the reply was read", joiner.offer_confirm, off["rendezvous_id"], cl["code"])
    got = joiner.offer_reply(cl["reply_text"], off["rendezvous_id"])
    if got["code"] != cl["code"] or got["peer"]["office_id"] != "macbook":
        problems.append("both screens must show the same six digits, and the joiner must see who answered")
    if joiner.offer_state(off["rendezvous_id"])["state"] != "claimed":
        problems.append("after the reply the offer is `claimed`, still live")
    wrong = "000000" if cl["code"] != "000000" else "111111"
    refused("a wrong code on the joiner", joiner.offer_confirm, off["rendezvous_id"], wrong)
    refused("a wrong code on the host", host.claim_confirm, cl["rendezvous_id"], wrong)
    if hp.records or "hp-laptop" not in mac.records or mac.records["hp-laptop"].get("kind"):
        problems.append("a wrong code writes nothing on either side")

    done_j = joiner.offer_confirm(off["rendezvous_id"], cl["code"][:3] + " " + cl["code"][3:])
    done_h = host.claim_confirm(cl["rendezvous_id"], cl["code"])
    rj, rh = hp.records.get("macbook") or {}, mac.records.get("hp-laptop") or {}
    if (rj.get("tunnel") or {}).get("side") != 2 or (rh.get("tunnel") or {}).get("side") != 1:
        problems.append("the joiner is side 2 and the host side 1 of the same pair")
    if {k: (rj.get("tunnel") or {}).get(k) for k in ("slot", "dial", "endpoint", "port")} != \
       {k: (rh.get("tunnel") or {}).get(k) for k in ("slot", "dial", "endpoint", "port")}:
        problems.append("both records must state the SAME pair: slot, who dials, and the listening address")
    if (rj.get("tunnel") or {}).get("listen_port") != 51830 or (rh.get("tunnel") or {}).get("listen_port") is not None:
        problems.append("the dialed office records its own listen port; the dialing office records none")
    if rj.get("pair_id") != rh.get("pair_id") or rj.get("identity", {}).get("wg") != mac.home()["identity"]["wg"]:
        problems.append("each record holds the other office's public identity under one pair_id")
    # the link, from each office's own point of view, must be the mirror of the other's
    if done_h["link"]["direction"] != "use" or done_j["link"]["direction"] != "serve":
        problems.append(f"the host uses, the joiner serves: {done_h['link']['direction']}/{done_j['link']['direction']}")
    if hp.vault.get("dgo_link-macbook", {}).get("token") != mac.vault.get("dgo_link-hp-laptop", {}).get("token") \
       or not hp.vault.get("dgo_link-macbook", {}).get("token"):
        problems.append("both vaults hold the same token, each under dgo_link-<peer id>")
    if not (hp.renders and mac.renders):
        problems.append("a confirmed pairing re-renders the tunnel on the side that confirmed")
    if "machine" in rh:
        problems.append("a replaced record keeps nothing of the installed office it replaced")
    if joiner.offer_state(off["rendezvous_id"])["state"] != "confirmed":
        problems.append("a confirmed offer reads as confirmed")
    refused("the same reply confirmed again", joiner.offer_confirm, off["rendezvous_id"], cl["code"])
    refused("a claim confirmed again", host.claim_confirm, cl["rendezvous_id"], cl["code"])

    # REACHABILITY IS A FACT OF THE PAIR (2026-10-12, lnk-032). An office at a public address that
    # reads an offer from an office at home does NOT dial the address her own LAN knows her by — it
    # cannot, and writing that pair is how a link is born dead while both screens say "paired". It
    # publishes its own address and lets her dial, and when it has none to publish the pairing is
    # refused in words that name the address that could not be used.
    cloud = _MemoryPorts("vps1", "VPS", slot=1, listen={"endpoint": "console.staging.example", "port": 51830})
    home = _MemoryPorts("hp-laptop", "HP", slot=2, listen={"endpoint": "192.168.16.100", "port": 51830})
    cloud_office, home_office = Pairing(cloud), Pairing(home)
    at_home = home_office.offer("both")                    # the HP offers, publishing her LAN address
    claimed = cloud_office.claim(at_home["text"])
    if {k: claimed["tunnel"].get(k) for k in ("dial", "endpoint", "port")} != \
            {"dial": "joiner", "endpoint": "console.staging.example", "port": 51830}:
        problems.append(f"a public office cannot dial a private address — the joiner dials it instead: "
                        f"{claimed['tunnel']}")
    # …and a peer with a LAN address is still dialed by an office that is on a LAN itself (the
    # MacBook beside the HP, and the very pairing that worked before this rule existed), and by an
    # office that published nothing at all — it can only dial, so that address is the only one there
    # is (the macOS engine: nothing inbound is possible there).
    mac_at_home = _MemoryPorts("macbook", "MacBook", slot=3, listen={"endpoint": "192.168.16.7", "port": 51830})
    beside = Pairing(mac_at_home).claim(home_office.offer("both")["text"])
    if {k: beside["tunnel"].get(k) for k in ("dial", "endpoint", "port")} != \
            {"dial": "host", "endpoint": "192.168.16.100", "port": 51830}:
        problems.append(f"an office on a LAN dials the peer's LAN address: {beside['tunnel']}")
    deaf = Pairing(_MemoryPorts("office-x", "X", slot=5))
    quiet = deaf.claim(home_office.offer("both")["text"])
    if {k: quiet["tunnel"].get(k) for k in ("dial", "endpoint", "port")} != \
            {"dial": "host", "endpoint": "192.168.16.100", "port": 51830}:
        problems.append(f"an office that published nothing dials the only address there is: {quiet['tunnel']}")
    # THE FAR END OF SOMEBODY'S LINK holds a tunnel address and no record of it: its offer names
    # that slot as used, and the new pair lands on one free on BOTH machines. (And an offer to USE
    # is, from the office that claims it, a link it SERVES.)
    far = _MemoryPorts("vps1", "VPS", slot=0, listen={"endpoint": "vps.example", "port": 51830},
                       addresses=["10.79.2.2", ""])
    lap = _MemoryPorts("hp-laptop", "HP", slot=1)
    lap.records["macbook"] = {"id": "macbook", "kind": declaration.PAIRED, "tunnel": {"slot": 4}}
    asked = Pairing(far).offer("use")
    if 2 not in (asked["offer"].get("used_slots") or []):
        problems.append(f"an offer names the slot of every tunnel address its office holds: {asked['offer'].get('used_slots')}")
    took = Pairing(lap).claim(asked["text"])
    if took["tunnel"]["slot"] != 3 or took["direction"] != "serve":
        problems.append(f"a slot free on both machines, and the claiming office serves: {took['tunnel']} {took['direction']}")

    # GIVING: the office that gives in the new link, and had declared nothing, gives everything; the
    # one that only uses is not touched. (hp-laptop offered to SERVE; the MacBook therefore USES.)
    if hp.served != {"*": {}} or not done_j.get("gave_all"):
        problems.append(f"an office that gives and declared nothing gives every app: {hp.served}")
    if mac.served or done_h.get("gave_all"):
        problems.append("an office that only USES a link declares nothing by pairing")
    g = joiner.giving()
    if g["mode"] != "all" or g["count"] != 3 or g["total"] != 3:
        problems.append(f"`all` reads as every app of the registry given: {g}")
    chosen = joiner.give("some", ["bina", "machine"])["giving"]
    if chosen["mode"] != "some" or [a["alias"] for a in chosen["apps"] if a["given"]] != ["bina", "machine"]:
        problems.append(f"`some` gives exactly the named apps: {chosen}")
    if hp.served != {"bina-ds": {"port": 3080, "agent_api_port": 3081}, "machine": {"port": 8080}}:
        problems.append(f"a chosen app is declared by its id with its port (and its second door): {hp.served}")
    hp.served["bina-ds"]["identity"] = {"to": "owner"}
    joiner.give("some", ["bina-ds"])
    if hp.served != {"bina-ds": {"port": 3080, "agent_api_port": 3081, "identity": {"to": "owner"}}}:
        problems.append("what was declared about an app that stays given is kept")
    refused("an app this office does not run", joiner.give, "some", ["nope"])
    refused("`some` with nothing chosen", joiner.give, "some", [])
    refused("a mode that does not exist", joiner.give, "everything")
    if joiner.give("none")["giving"]["mode"] != "none" or hp.served != {}:
        problems.append("`none` closes the doors: nothing is declared")
    if not joiner.giving()["chosen"]:
        problems.append("after a person chose `none`, the declaration reads as chosen")
    again = joiner.offer("serve")
    cl_again = host.claim(again["text"], replace=True)
    joiner.offer_reply(cl_again["reply_text"], again["rendezvous_id"])
    if joiner.offer_confirm(again["rendezvous_id"], cl_again["code"], replace=True).get("gave_all") or hp.served:
        problems.append("an office whose owner chose to give NOTHING is not made to give by a later pairing")
    host.claim_confirm(cl_again["rendezvous_id"], cl_again["code"], replace=True)
    fresh = Pairing(_MemoryPorts("office-n", "N", 1, listen={"endpoint": "10.0.0.5", "port": 51820}))
    if fresh.giving()["chosen"] or fresh.giving()["mode"] != "none":
        problems.append("an office nobody asked reads as `none`, not chosen")

    # A NAME: the record keeps what the peer called itself, the card follows what it publishes now,
    # and neither is believed when it is the placeholder an unnamed office holds about itself
    card = lambda: next(i for i in host.listing()["items"] if i["office"] == "hp-laptop")["label"]  # noqa: E731
    if card() != "HP":
        problems.append(f"a paired card carries the name the peer gave itself when it paired: {card()!r}")
    mac.published["hp-laptop"] = "הנייד של המשרד"
    if card() != "הנייד של המשרד":
        problems.append("a paired card follows the name the peer publishes NOW")
    mac.published["hp-laptop"] = "הלשכה הזאת"
    if card() != "HP":
        problems.append("a peer that publishes the placeholder is not believed — the paired name stays")
    mac.published["hp-laptop"] = ""
    mac.records["hp-laptop"]["label"] = "הלשכה הזאת"
    if card() != "hp-laptop":
        problems.append("a peer that never had a name is shown by its id, never as „this office”")
    anon = Pairing(_MemoryPorts("office-f", "הלשכה הזאת", 1, listen={"endpoint": "10.0.0.7", "port": 51820}))
    if anon.offer()["offer"].get("label") != "office-f" or anon.listing()["home"]["named"]:
        problems.append("an unnamed office introduces itself by its id, and says it has no name")
    refused("the placeholder as a name", anon.rename, "הלשכה הזאת")
    refused("an empty name", anon.rename, "   ")
    refused("a name with markup in it", anon.rename, "<b>x</b>")
    refused("a name longer than 60 characters", anon.rename, "ש" * 61)
    named = anon.rename("  מחשב   נייד ")["home"]
    if named["label"] != "מחשב נייד" or not named["named"] or anon.offer()["offer"].get("label") != "מחשב נייד":
        problems.append(f"a name is stored trimmed and is what the next offer carries: {named}")
    unnamed_host = Pairing(_MemoryPorts("office-g", "הלשכה הזאת", 1, listen={"endpoint": "10.0.0.8", "port": 51820}))
    named_joiner = Pairing(_MemoryPorts("office-h", "H", 2))
    seen = unnamed_host.claim(named_joiner.offer()["text"])
    if seen["peer"]["label"] != "H":
        problems.append("the host reads the joiner's name off the offer")
    if named_joiner.offer_reply(seen["reply_text"])["peer"]["label"] != "office-g":
        problems.append("an unnamed HOST is, to the joiner, its id — never „this office”")

    # TWO FRESH OFFICES must not share an id: the default comes from the machine's name, and from
    # the key where that name is one every machine of its kind has (converge.default_office_id)
    try:
        import converge as _cv
        ids = [_cv.default_office_id(x) for x in (
            {"office": "DESKTOP-DTFB8I4", "fingerprint": "3A4B-3343-4492-5A1A"},
            {"office": "lima-bbox", "fingerprint": "75FF-E977-0881-0625"},
            {"office": "local", "fingerprint": "AAAA-BBBB-CCCC-DDDD"},
            {"office": "", "fingerprint": ""}, None)]
        if ids != ["desktop-dtfb8i4", "office-75ffe977", "office-aaaabbbb", "local", "local"]:
            problems.append(f"a fresh office's default id is its machine's name, else its key's: {ids}")
        if any(not pairing.OFFICE_RE.match(i) for i in ids):
            problems.append(f"every default id must be one pairing accepts: {ids}")
    except ImportError:
        pass        # the engine's pure half is importable without the app's own modules

    # nobody listens → no direct tunnel can exist. The refusal is a sentence a person can act on —
    # no variable name in it — and each office's own listing says why IT cannot be dialed.
    a, b = Pairing(_MemoryPorts("office-a", "A", 1)), Pairing(_MemoryPorts("office-b", "B", 1))
    refused("a pair in which neither side can be dialed", b.claim, a.offer()["text"])
    try:
        b.claim(a.offer()["text"])
    except PairError as e:
        if e.status != 409 or "DGO_" in str(e) or "relay" in str(e):
            problems.append(f"two dial-only offices are refused in plain words, with 409: {e}")
    a.ports.why = "wsl-nat"
    said = a.listing().get("dial_only") or {}
    if said.get("why") != "wsl-nat" or "mirrored" not in said.get("fix", "") or not said.get("reason"):
        problems.append(f"a dial-only office says why, and what would make it dialable: {said}")
    a.ports.why = "something-new"
    if (a.listing().get("dial_only") or {}).get("why") != "undeclared":
        problems.append("a reason this code does not know reads as `undeclared`, never as a blank")
    if joiner.listing().get("dial_only") is not None:
        problems.append("an office that can be dialed has no dial-only reason")
    whys = [dial_only_why(e) for e in (
        {}, {AUTO_ENV: "0"}, {DIAL_ONLY_ENV: "wsl-nat"}, {DIAL_ONLY_ENV: " Engine-Guest "}, {DIAL_ONLY_ENV: "x"},
        {AUTO_ENV: "0", DIAL_ONLY_ENV: "wsl-nat"},
        {LISTEN_ENDPOINT_ENV: "10.0.0.5", LISTEN_PORT_ENV: "51830", DIAL_ONLY_ENV: "wsl-nat"})]
    if whys != ["undeclared", "declared", "wsl-nat", "engine-guest", "undeclared", "declared", ""]:
        problems.append(f"the reason comes from the environment: the owner's word first, an address beats both: {whys}")
    if any("`" not in fix and why in ("wsl-nat", "declared", "undeclared") for why, (_r, fix) in DIAL_ONLY_HE.items()):
        problems.append("a remedy that names something to type marks it as a token")

    # a refusal from the layer below is a sentence with what to do; anything else is not a refusal
    class _Below(Exception):
        def __init__(self, reason, action=""):
            super().__init__(reason)
            self.reason, self.action = reason, action
    said = [worded_refusal(x) for x in (_Below("אין זהות ללשכה הזאת.", "הרץ `bbox dgo identity mint`."),
                                        _Below("אין זהות"), ValueError("boom"), KeyError("id"))]
    if said != ["אין זהות ללשכה הזאת. הרץ `bbox dgo identity mint`.", "אין זהות", "", ""]:
        problems.append(f"a worded refusal from below is its reason and its action; a crash is not one: {said}")
    # the host listens, the joiner cannot: the joiner dials
    c = Pairing(_MemoryPorts("office-c", "C", 1, listen={"endpoint": "vps.example.org", "port": 51820}))
    cl2 = c.claim(a.offer()["text"])
    if cl2["tunnel"]["dial"] != "joiner" or cl2["tunnel"]["endpoint"] != "vps.example.org":
        problems.append("when only the host can listen, the joiner dials the host's address")
    if cl2["tunnel"]["slot"] != 2:
        problems.append("the pair's slot avoids the slots BOTH offices already use")
    # an expired offer, and a reply for someone else's offer
    clock = [time.time()]
    late = Pairing(_MemoryPorts("office-d", "D", 1, listen={"endpoint": "10.0.0.9", "port": 51820}),
                   now=lambda: clock[0])
    old = late.offer()
    clock[0] += pairing.OFFER_TTL + 5
    refused("an expired offer", Pairing(_MemoryPorts("office-e", "E", 1), now=lambda: clock[0]).claim, old["text"])
    refused("a reply to another office's offer", late.offer_reply, cl["reply_text"])
    # unpair: record and token go together, and only a PAIRED record can be unpaired this way
    refused("unpairing an installed office", host.unpair, "vps1")
    gone = host.unpair("hp-laptop")
    if "hp-laptop" in mac.records or "dgo_link-hp-laptop" in mac.vault:
        problems.append("unpair removes the record and its token together")
    if mac.compiles != 1 or not (gone.get("compiled") or {}).get("ok"):
        problems.append("unpair compiles once — the office's tiles and routes leave with its record — and says how it went")
    if listen_from_env({LISTEN_ENDPOINT_ENV: "192.168.16.102", LISTEN_PORT_ENV: "51830"}) != \
            {"endpoint": "192.168.16.102", "port": 51830} or listen_from_env({}) or \
            listen_from_env({LISTEN_ENDPOINT_ENV: "http://x", LISTEN_PORT_ENV: "1"}):
        problems.append("the listen address comes from the environment, validated, or not at all")
    # WHERE THE OFFICE IS DIALED NOW: its declaration, until every office that reaches it reaches it
    # somewhere else — and never an address made of anything but a host and a port.
    said = {"endpoint": "192.168.16.102", "port": 51830}
    if listen_now(said, {}) != said or listen_now(said, {"macbook": "not an address", "vps1": "x:99999"}) != said:
        problems.append("with nobody reporting an address, the office listens where it declares")
    if listen_now(said, {"macbook": "192.168.16.102:51830", "vps1": "10.0.0.9:51830"}) != said:
        problems.append("while ONE office still reaches the declared address, it stands")
    if listen_now(said, {"macbook": "192.168.16.100:51830"}) != \
            {"endpoint": "192.168.16.100", "port": 51830, "moved_from": "192.168.16.102"}:
        problems.append("an office reached only somewhere else listens THERE, and says where it used to")
    if listen_now({}, {"macbook": "192.168.16.100:51830"}):
        problems.append("an office that declares nothing only dials, whatever a peer reports")
    named = {"endpoint": "office.example.org", "port": 51830}
    if listen_now(named, {"hp-laptop": "31.97.196.82:51830"}) != named:
        problems.append("a declared NAME is a decision, not a lease: the number it resolves to does not replace it")
    # …and WHO says that address: the office that dials the pair, from its tunnel's own reading —
    # never the dialed end (what it measures is the dialer's own source), never a dead tunnel.
    live = {"wg4": {"endpoint": "192.168.16.100:51830", "alive": True}}
    mine = {"id": "hp-laptop", "kind": declaration.PAIRED, "tunnel": {"slot": 4, "role": "joiner", "dial": "joiner"}}
    hers = {"id": "macbook", "kind": declaration.PAIRED, "tunnel": {"slot": 4, "role": "host", "dial": "joiner"}}
    if dials(mine, live) != "192.168.16.100:51830" or listens(mine):
        problems.append("the office that dials a pair says where it reaches the other")
    if dials(hers, live) or not listens(hers):
        problems.append("the dialed end says nothing about the dialer's address, and knows it listens")
    if dials(mine, {"wg4": {"endpoint": "192.168.16.100:51830", "alive": False}}) or dials(mine, {}) \
            or dials({"id": "vps1", "tunnel": {"slot": 4, "role": "joiner", "dial": "joiner"}}, live) or dials(None, live):
        problems.append("no address from a dead tunnel, an unmeasured one, or a record that is not a pair")
    return problems


if __name__ == "__main__":
    bad = selftest()
    for b in bad:
        print("FAIL", b)
    print("pair_api.py selftest:", "PASS" if not bad else f"{len(bad)} problem(s)")
    raise SystemExit(1 if bad else 0)
