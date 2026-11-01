"""dgo-extend.identity — one Ed25519 key and one WireGuard key per office.

Why an office has an identity at all
------------------------------------
A link is a one-way trust between two office instances, and the tunnel under it is WireGuard.
Both need something that names THIS office and cannot be forged: the WireGuard key is what makes a peer's
packets its own, and the Ed25519 key is what lets a claim ("this key is mine", "this grant is
addressed to you") be verified by the other side without a shared secret.

Where it lives — and where it must NOT live
-------------------------------------------
In its own volume (`dgo_identity`, mounted here at `/identity`), mode 0700/0600, owned by root. NOT
in the vault: the vault is the credential plane for accounts the owner connects (a Telegram login, a
GitHub token), and this key is not an account — it IS the office. It is declared in app.json
`data.volumes`, which is what makes `bbox export` carry it, so a rebuilt office keeps its name on the
network instead of announcing itself as a stranger.

How it is minted
----------------
`openssl` — present on every machine this platform installs — for BOTH curves, and only the last 32
bytes of each DER blob are kept (the raw key, which is what WireGuard's `base64` and an Ed25519
signature API want). Deliberately no Python crypto dependency: this module runs inside the app
(reading, no secrets leave) and inside `hooks/identity` on a machine that has nothing installed yet,
and a `pip install` in the middle of that is a failure mode, not a step.

The public half is what crosses the wire. `public()` is the only thing any route or log may use.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

#: The volume's mount point in the app. The hook passes its own directory.
DIR_ENV = "DGO_IDENTITY_DIR"
FILE = "identity.json"

#: THE OFFICE'S MARK — a colour and an animal — and the closed vocabularies they come from.
#:
#: A NAME crosses the wire, never a hex (owner, 2026-10-08; flt-002/flt-004): the palette owns the
#: VALUE, in `platform-base/bina-ui/theme-tokens.css` under `[data-office-hue="<name>"]`, and this
#: file owns the vocabulary's NAMES. The animal is a glyph of `bina-icons.js` under the same name.
#: Two facts, two owners, and a screen says only `data-office-hue="lime"` + the glyph.
#:
#: The pools are what make "a colour and an animal for every office" possible ten or twenty offices
#: later without inventing a value per office: the three the owner named keep theirs by name, and a
#: new office takes a pair by hash of its own name — deterministic, so two machines that mint an
#: identity for the same office agree, and legal, so a screen never has to guess.
#:
#: EVERY NAME HERE IS A PALETTE FAMILY, and that is the only reason the list is this short: the rule
#: that turns a name into a value lives in theme-tokens.css (`[data-office-hue="<name>"]`), so a name
#: with no family — "sand", "rose", "teal" in an earlier draft of this line — would resolve to an
#: undefined variable and draw nothing. Seven hues × ten animals is seventy distinguishable marks,
#: which is what "ten or twenty offices" needs; `--red` and `--ok` are deliberately NOT among them
#: (they mean "danger" and "well" on every screen, and an office must not).
OFFICE_HUES = ("grey", "lime", "sky", "olive", "plum", "blue", "violet")
OFFICE_ANIMALS = ("elephant", "deer", "eagle", "owl", "fox", "horse", "raven", "hare", "lion", "swan")
#: ONE HUE, ONE NAME — and the other name for it is accepted, not stored. The compiler's `office:`
#: block (the wizard's own record, written through the control plane) names the palette's VARIABLE
#: for grey — `muted` — while the owner's word for this office, and the name this module derives and
#: publishes, is `grey`. Both are honest spellings of one fact, so the boundary normalizes instead
#: of the vocabulary forking: whoever writes `muted` gets `grey` back, on the wire and on the screen.
HUES_ALIAS = {"muted": "grey"}
#: The three the owner named himself (2026-10-09, ai/context/fleet-colours-and-animals.md), by office
#: name — so this office and the Mac read the same pair for themselves without being told.
NAMED_MARKS = {"hp": ("grey", "elephant"), "macbook": ("lime", "deer"), "vps": ("sky", "eagle")}
#: …and the SAME three offices as their machines name themselves. A link record carries an id, not the
#: owner's word (`home.id` is `hp-laptop`; his staging record calls the VPS `vps1`), and a surface that
#: derives a mark from that id must reach the same pair — one office, one colour, whatever it is called.
HANDLE_ALIASES = {"hp-laptop": "hp", "vps1": "vps"}


def _named(office: str) -> tuple[str, str] | None:
    """The owner's pair for this office, if the name is one he named.

    An office has two names and they are the same office: his word for it, and the id its own link record
    carries (`/api/link` → `home.id`, `hp-laptop` here; `vps1` for the staging box in his own record). A
    handle is matched through `HANDLE_ALIASES` rather than by guessing from the string — `vps2`, the day
    there is one, is a DIFFERENT office and must not be handed the first VPS's colour."""
    name = (office or "").strip().lower()
    return NAMED_MARKS.get(name) or NAMED_MARKS.get(HANDLE_ALIASES.get(name, ""))


def mark_for(office: str) -> dict:
    """The `{color, animal}` an office name gets when nobody chose one."""
    name = (office or "").strip().lower()
    named = _named(name)
    if named:
        color, animal = named
    else:
        # The hues the owner's three offices WEAR are not handed out again. A colour is the half of the
        # mark a person reads without reading, so two offices drawn in one hue on one screen is the mark
        # failing at its only job — and it happened: this office's name is its HOST name, not `hp`, so it
        # missed its own row above and a hash handed it `lime`, the MacBook's. Measured 2026-10-11 in the
        # console's own registry: `bina.macbook` and this office, one colour, two machines.
        free = [h for h in OFFICE_HUES if h not in {c for c, _ in NAMED_MARKS.values()}]
        digest = int(hashlib.sha256(name.encode()).hexdigest()[:8], 16)
        color = free[digest % len(free)]
        animal = OFFICE_ANIMALS[(digest // len(free)) % len(OFFICE_ANIMALS)]
    return {"color": color, "animal": animal}


def clean_mark(mark) -> dict | None:
    """A mark as it may be stored or published, or None when it is not one.

    Refusing here rather than at the screen is deliberate: an office whose colour is a raw hex (a
    value, which the palette owns and this file may not write — G82) or whose animal is a string
    nobody drew would reach a tile as a blank mark, and "the linked office has no colour" is a defect
    nobody traces back to a typo in a wizard."""
    if not isinstance(mark, dict):
        return None
    color = str(mark.get("color") or "").strip().lower()
    color = HUES_ALIAS.get(color, color)
    animal = str(mark.get("animal") or "").strip().lower()
    if color not in OFFICE_HUES or animal not in OFFICE_ANIMALS:
        return None
    return {"color": color, "animal": animal}


class IdentityError(RuntimeError):
    """Minting or reading failed, with a sentence the operator can act on."""


def directory(explicit: str | os.PathLike | None = None) -> Path:
    if explicit:
        return Path(explicit)
    if os.environ.get(DIR_ENV):
        return Path(os.environ[DIR_ENV])
    return Path("/identity")


def load(where: str | os.PathLike | None = None) -> dict | None:
    p = directory(where) / FILE
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _openssl_curve(algorithm: str) -> tuple[str, str]:
    """(private, public) as base64 of the RAW 32-byte keys, minted by openssl."""
    try:
        priv_der = subprocess.run(["openssl", "genpkey", "-algorithm", algorithm, "-outform", "DER"],
                                  capture_output=True, check=True).stdout
        pub_der = subprocess.run(["openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"],
                                 input=priv_der, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise IdentityError(f"לא ניתן למנות מפתח {algorithm} (openssl): {e}") from e
    if len(priv_der) < 32 or len(pub_der) < 32:
        raise IdentityError(f"openssl החזיר מפתח {algorithm} קצר מהצפוי")
    b64 = lambda raw: base64.b64encode(raw).decode()          # noqa: E731
    return b64(priv_der[-32:]), b64(pub_der[-32:])


def fingerprint(doc: dict) -> str:
    """A short, stable name for this office's keys — what two screens compare out loud."""
    material = (doc.get("ed25519", {}).get("public", "") + doc.get("wg", {}).get("public", ""))
    digest = hashlib.sha256(material.encode()).hexdigest().upper()
    return "-".join(digest[i:i + 4] for i in range(0, 16, 4))


def mint(where: str | os.PathLike | None = None, force: bool = False, label: str = "",
         mark: dict | None = None) -> dict:
    """Mint and store the office's keys. Idempotent: an existing identity is never overwritten unless
    `force` — a new key is a new office as far as every peer is concerned, and it must be announced.

    `mark` is the wizard's choice (flt-001). Absent, the office takes the pair its NAME gets: the
    owner's three by name, the next free pair otherwise. It is part of the identity and not of the
    configuration, so it survives a re-install, a re-pair and a move — the same record the backup
    carries."""
    d = directory(where)
    existing = load(d)
    if existing and not force:
        return existing
    ed_priv, ed_pub = _openssl_curve("ED25519")
    wg_priv, wg_pub = _openssl_curve("X25519")
    office = label or os.environ.get("DEPLOYMENT_NAME") or os.uname().nodename
    doc = {"office": office,
           "created_at": int(time.time()),
           "ed25519": {"private": ed_priv, "public": ed_pub},
           "wg": {"private": wg_priv, "public": wg_pub}}
    doc["mark"] = clean_mark(mark) or mark_for(office)
    doc["fingerprint"] = fingerprint(doc)
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    tmp = d / (FILE + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(d / FILE)
    return doc


def public(doc: dict | None = None, where: str | os.PathLike | None = None) -> dict:
    """The half that may cross the wire, appear in a log, or be shown on a screen."""
    doc = doc or load(where) or {}
    return {"office": doc.get("office"), "fingerprint": doc.get("fingerprint") or fingerprint(doc),
            "created_at": doc.get("created_at"),
            # The mark travels with the public half: a peer drawing this office's tile needs the
            # colour's NAME and the animal's NAME and nothing else. An office minted before marks
            # existed answers with the pair its name gets — never a blank.
            "mark": clean_mark(doc.get("mark")) or mark_for(str(doc.get("office") or "")),
            "ed25519": doc.get("ed25519", {}).get("public"),
            "wg": doc.get("wg", {}).get("public")}


def set_mark(mark: dict, where: str | os.PathLike | None = None) -> dict:
    """Choose this office's colour and animal — what the install wizard calls (flt-001).

    A mark is not a key: changing it changes nothing about who this office IS, so unlike `mint` this
    rewrites in place, keeps the keys and the fingerprint, and announces nothing to peers beyond the
    catalog they read anyway. Refused when the pair is not one a screen can draw."""
    clean = clean_mark(mark)
    if not clean:
        raise IdentityError(f"mark {mark!r} is not one of the office vocabularies: "
                            f"colour from {', '.join(OFFICE_HUES)}; animal from "
                            f"{', '.join(OFFICE_ANIMALS)}")
    d = directory(where)
    doc = load(d)
    if not doc:
        raise IdentityError("no identity on this machine yet — run: bbox dgo identity mint")
    doc["mark"] = clean
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / (FILE + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(d / FILE)
    return doc


def main(argv: list[str]) -> int:
    """`python3 identity.py [--dir D] [--label L] [--color C --animal A] [mint|set|public|fingerprint]`
    — the hook's entry point.

    `public` is the default and never mints: a machine answering a question about itself must not
    silently create an identity as a side effect of being asked.
    """
    where, label, verb, force = None, "", "public", False
    color, animal = "", ""
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--dir" and args:
            where = args.pop(0)
        elif a == "--label" and args:
            label = args.pop(0)
        elif a == "--color" and args:
            color = args.pop(0)
        elif a == "--animal" and args:
            animal = args.pop(0)
        elif a == "--force":
            force = True
        elif a in ("mint", "set", "public", "fingerprint"):
            verb = a
        else:
            print(f"unknown argument: {a}", file=os.sys.stderr)
            return 2
    chosen = {"color": color, "animal": animal} if (color or animal) else None
    try:
        if verb == "mint":
            doc = mint(where, force=force, label=label, mark=chosen)
            print(json.dumps(public(doc), indent=2))
            return 0
        if verb == "set":
            doc = set_mark(chosen or {}, where)
            print(json.dumps(public(doc), indent=2))
            return 0
        doc = load(where)
        if not doc:
            print("no identity on this machine yet — run: bbox dgo identity mint", file=os.sys.stderr)
            return 1
        if verb == "fingerprint":
            print(doc.get("fingerprint") or fingerprint(doc))
        else:
            print(json.dumps(public(doc), indent=2))
        return 0
    except IdentityError as e:
        print(str(e), file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(os.sys.argv[1:]))
