"""remote — the machines a LINKED office shares with this one (DGO-553).

Why this is its own module
--------------------------
Because the rule it applies is small, sharp, and worth testing without a web server, a vault or a
machine: **a shared machine is a row in this office's fleet, addressed `<machine>.<office>`, and every
op on it goes back over the link to the office that owns it.** Keeping it stdlib-only is what lets
`tests/test_remote_fleet.py` prove the merge, the suffixing and the refusal with a stand-in door,
instead of asking a reviewer to believe a screenshot.

Two directions, two sources, and neither is a list of machines kept here
----------------------------------------------------------------------
* WHAT THIS OFFICE GIVES is `serve.computers.machines` in the link's own declaration (`"*"` or a list
  of ids). It is read from the link app — the app that owns the declaration and has the screen for
  it — and applied on the way IN, where the door already told us which office is asking
  (`x-dgo-office`). A machine that is not given is not listed and not reachable by guessing its id.
* WHAT ANOTHER OFFICE GIVES arrives as `remote.<office>.computers.json` — the compiler's own record
  of where that office's computers app is reachable from here (the door's base and the authority it
  answers under). The machine LIST is not copied into that file: the peer answers its own list,
  already narrowed by its own declaration, so the two offices can never disagree about it.

Nothing crosses the link except HTTP: no key, no secret, no volume. The far office runs the command
with ITS key, on ITS machine — which is the whole point of sharing a machine instead of copying one.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

#: A machine id as the computers app makes one (`<protocol>-<suffix>`), and the office suffix this
#: module adds. The two-part rule is what keeps a shared id from ever looking like a local one: a
#: local id has no dot.
OFFICE_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}\Z")
#: The key `serve:` uses for "everything this office has" — the same one `serve.plan` reads.
WILDCARD = "*"
#: How long a peer's fleet answer is trusted, and how long the `serve` block is. Both are caches of
#: a fact somebody else owns. The second is TEN SECONDS, not a minute, and the reason is a person's
#: act: «הרחבת לשכה» lets an owner share one machine and then cancel, and a minute of cache made the
#: cancel invisible for a minute (measured 2026-11-02: `machines` restored to `"*"` and a peer through
#: the door still got the single machine). This module holds the ONE definition — `app.py` defined the
#: same two names again and read THESE, so tuning the copy in `app.py` changed nothing at all.
REMOTE_TTL = float(os.environ.get("COMPUTERS_REMOTE_TTL", "15"))
SHARE_TTL = float(os.environ.get("COMPUTERS_SHARE_TTL", "10"))

#: where the compiled registry is mounted: docker-compose.yml mounts it at /registry and says so in COMPUTERS_REGISTRY
#: — the name the rest of the app reads (HERD). This module read COMPUTERS_REGISTRY_DIR, which nothing sets, with a
#: default the container does not have, so in the container it found no linked office (DGO-1800). The old name is
#: still taken first, so nothing that set it changes.
DEFAULT_REGISTRY = "/registry"


def registry_dir(value: str | os.PathLike | None = None) -> Path:
    return Path(value or os.environ.get("COMPUTERS_REGISTRY_DIR") or os.environ.get("COMPUTERS_REGISTRY")
                or DEFAULT_REGISTRY)


def apps(base: str | os.PathLike | None = None) -> list[dict]:
    """The linked offices' computers apps, from the compiled registry — one entry per office.

    An office with no `door` in its record is one this office may not proxy (an app that owns its
    origin, or a peer from before the door existed): it is left out rather than called at a URL
    that was never published, because a wrong base is a request into somebody else's app.
    """
    out: list[dict] = []
    try:
        paths = sorted(registry_dir(base).glob("remote.*.computers.json"))
    except OSError:
        return out
    for path in paths:
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or str(rec.get("app") or "") != "computers":
            continue
        door = rec.get("door") if isinstance(rec.get("door"), dict) else {}
        remote = rec.get("remote") if isinstance(rec.get("remote"), dict) else {}
        office = str(remote.get("office") or "").strip().lower()
        base_url = str(door.get("base") or "").rstrip("/")
        if not OFFICE_RE.match(office) or not base_url:
            continue
        label = remote.get("label")
        if isinstance(label, dict):
            label = label.get("he") or label.get("en") or office
        out.append({"office": office, "label": str(label or office), "base": base_url,
                    "host": str(door.get("host") or ""), "machine_prefix": ""})
    return out


def office_of(cid: str, known: list[dict] | None = None) -> tuple[dict | None, str | None]:
    """`computer_ssh-x.macbook` → (that office's computers app, `computer_ssh-x`), else (None, None).

    The LAST dot is the separator, so an office id that itself contains one could never be confused
    with a machine id — and a local id (no dot at all) never reaches the network.
    """
    if not cid or "." not in cid:
        return None, None
    machine, office = cid.rsplit(".", 1)
    office = office.strip().lower()
    for app in (known if known is not None else apps()):
        if app.get("office") == office:
            return app, machine
    return None, None


def supports_shell(app: dict, timeout: float = 4.0) -> bool | None:
    """Does the office behind this door run a version that can open a TERMINAL (`shell`)?

    The op is new (DGO-553) and a peer older than it answers `405` — a person should be told that
    BEFORE they press «התחברות», not after: the screen disables the button and names the reason
    instead of opening a terminal that dies. `None` = could not ask (the office is down); that is
    not "no", and the caller keeps the button off with a different sentence.
    """
    code, data = fetch(app, "GET", "/manifest", timeout=timeout)
    if code >= 300:
        return None
    ops = data.get("ops")
    caps = data.get("capabilities")
    if isinstance(ops, list) and "shell" in ops:
        return True
    if isinstance(caps, dict):
        return bool(caps.get("shell"))
    return False


def as_rows(app: dict, payload: dict, shell: bool | None = None) -> list[dict]:
    """One linked office's answer → rows of THIS fleet, each carrying where it really lives."""
    rows: list[dict] = []
    for m in (payload or {}).get("computers") or []:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        remote = m.get("remote")
        if isinstance(remote, dict) and remote.get("office"):
            continue          # a peer's own shared machines are not re-shared through us
        rows.append({
            **m,
            "id": f"{m['id']}.{app['office']}",
            "label": m.get("label") or m.get("host"),
            "builtin": False,
            "removable": False,
            "remote": {"office": app["office"], "label": app.get("label") or app["office"],
                       "base": app["base"], "host": app.get("host") or "",
                       "machine": m["id"],
                       # can that office open a terminal on this machine? (see supports_shell)
                       "shell": shell},
        })
    return rows


def serves(serve_block, office: str) -> bool:
    """Is the «מחשבים» APP itself served to this office? The question `machines_declared` assumes.

    It exists because "which machines" and "at all" are different refusals, and treating them as one
    was a hole: `machines_declared` answers `"*"` for an office that declared no `machines` key — a
    sensible default *once the app is shared* — and the gate used that answer without asking whether
    the app was shared at all. An office given only `terminal` (which is a real, intended choice)
    therefore reached every machine of this office, list/exec/shell included (found by a second reader,
    2026-11-02).

    The same rules `serve.plan` applies, read once: a per-office `only` list is that office's whole
    grant (and wins over the wildcard), otherwise the wildcard serves everything and a named entry
    serves that app.
    """
    if not isinstance(serve_block, dict) or not serve_block:
        return False
    # `exclude` is the third half of the same decision (`catalog.publishable` applies all three), and
    # leaving it out here would serve machines to an office whose «מחשבים» tile was deliberately
    # withheld: the catalog would not publish the app, but a request that named the host would pass.
    excluded = serve_block.get("exclude")
    if isinstance(excluded, str):
        excluded = [excluded]
    if "computers" in [str(x or "").strip().lower() for x in (excluded or [])]:
        return False
    oid = str(office or "").strip().lower()
    only = serve_block.get("only")
    if isinstance(only, dict) and oid in only:
        listed = only.get(oid) or []
        if isinstance(listed, str):
            listed = [listed]
        return "computers" in [str(x or "").strip().lower() for x in (listed or [])]
    return WILDCARD in serve_block or "computers" in serve_block


def machines_declared(serve_block) -> str | list[str]:
    """`serve.computers.machines` → `"*"` or a list of ids. Anything unreadable admits NOTHING.

    The default is the interesting half: an office that declared no `machines` key at all has not
    said "no" — it has said nothing — so it keeps today's behaviour, which is that sharing the
    computers app shares its machines. A block that IS there but is malformed admits nothing, and it
    is the caller's job to say so: "I could not read your declaration" is not "share everything".
    """
    if not isinstance(serve_block, dict):
        return "*"
    mine = serve_block.get("computers")
    if not isinstance(mine, dict) or "machines" not in mine:
        return "*"
    listed = mine.get("machines")
    if isinstance(listed, str):
        listed = [listed]
    if not isinstance(listed, list):
        return []
    out: list[str] = []
    for x in listed:
        x = str(x or "").strip()
        if x == "*":
            return "*"
        if x:
            out.append(x)
    return out


def is_shared(machines: str | list[str], cid: str) -> bool:
    """Is this machine part of what the office gives? `"*"` is everything; a list is by id."""
    if machines == "*":
        return True
    base = cid.rsplit(".", 1)[0] if "." in cid else cid
    shared = {str(x) for x in (machines or [])}
    return cid in shared or base in shared


def refusal(office: str, machines: str | list[str], cid: str) -> str:
    """The sentence a refused peer gets — or `""` when it may pass. Empty office = a local caller."""
    if not office or is_shared(machines, cid):
        return ""
    return "המחשב הזה לא שותף עם הלשכה שלך"


def fetch(app: dict, method: str, path: str, body: dict | None = None,
          timeout: float = 10.0) -> tuple[int, dict]:
    """One call THROUGH the link's door: its base, addressed by the authority it routes on.

    `requests` is imported here, not at module import, so the pure half of this module can be tested
    in an environment that has no HTTP client at all.
    """
    try:
        import requests
    except ImportError:                       # pragma: no cover — only a stripped-down test box
        return 501, {"error": "אין לקוח HTTP בסביבה הזו"}
    headers = {"Host": app.get("host") or "", "x-dgo-app": "computers"}
    try:
        r = requests.request(method, f"{app['base']}{path}", headers=headers, json=body,
                             timeout=timeout)
    except requests.RequestException as e:
        return 502, {"error": f"הלשכה {app.get('label') or app.get('office')} לא ענתה דרך הקישור",
                     "detail": str(e)}
    try:
        data = r.json() if r.content else {}
    except ValueError:
        data = {"error": f"תשובה לא קריאה מהלשכה {app.get('label') or app.get('office')} "
                         f"({r.status_code})"}
    return r.status_code, (data if isinstance(data, dict) else {})
