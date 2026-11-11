"""egress — where each app of the office may open a connection to the internet, and which flows nobody declared.

DGO-1561, slice 1: declared and MARKED through the API — `/api/outbound` says, per destination, whether every app
that reached it was declared to, `/api/egress` lists what was not, and `/api/summary` counts it. Nothing is dropped
yet: enforcement comes after a week of this on a real office (the item's own order — observe first, as the jails do).

The owner, 2026-11-09: «כרגע אין לאפלקציות שום סיבה לפנות החוצה … ואין יציאות כניסות שהם לא בכוונה על ידנו».

Two sources, merged:
  egress.yaml beside this file      the product's own apps: a compose service name, `@host` for the machine,
                                    `@unnamed` for a container known only by its address or its image;
  SECURITY_EGRESS_EXTRA (.env)      what ONE office adds on purpose: `app=pattern pattern; app=pattern`.

A pattern is one of:
  `name.example`, `*.example`       a name the office's own resolver answered for the address, inside the window
                                    asked (the caller passes DNS names only: a TLS server name is the client's
                                    choice and a PTR the address owner's, so neither may declare anything);
                                    `*.example` is any name UNDER example, never example itself;
  `203.0.113.0/24`, `2001:db8::1`   the address itself;
  `@dns`, `@ntp`                    every port of the flow is 53/udp, or 123/udp (a resolver, a time server: no name);
  `@smtp`                           every port is 25, 465 or 587/tcp (mail goes to each recipient's own server);
  `*`                               anywhere (a browser goes where a person sends it; meeting media to each guest).
Only a flow to a STRANGER is judged: an address the security app already calls by a name of its own (this machine,
a container, a linked office, multicast, a private network — `trust.label`) is never «undeclared». A destination
several apps reached is declared only when every one of them was declared for it.

A file that does not load is an error, never «no rules»: with no rules every flow would read undeclared and the
mark would mean nothing (the second reader). The app keeps running and says so in its health.
"""
from __future__ import annotations

import ipaddress
import os
import re

import yaml

POLICY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "egress.yaml")
PORT_CLASSES = {
    "@dns": {"53/udp"},
    "@ntp": {"123/udp"},
    "@smtp": {"25/tcp", "465/tcp", "587/tcp"},
}
_NAME = re.compile(r"^(\*\.)?[a-z0-9_]([a-z0-9_-]*[a-z0-9_])?(\.[a-z0-9_]([a-z0-9_-]*[a-z0-9_])?)+$")


class PolicyError(ValueError):
    pass


def _norm(name: str) -> str:
    return (name or "").strip().lower().rstrip(".")


def _is_address(text: str) -> bool:
    try:
        ipaddress.ip_network(text, strict=False)
        return True
    except ValueError:
        return False


def _pattern(raw, where: str) -> str:
    if not isinstance(raw, str):
        raise PolicyError(f"{where}: a pattern must be a string, not {type(raw).__name__} ({raw!r})")
    p = raw.strip()
    if p == "*" or p in PORT_CLASSES:
        return p
    if p.startswith("@"):
        raise PolicyError(f"{where}: unknown keyword {p!r} (known: {', '.join(sorted(PORT_CLASSES))})")
    if _is_address(p):
        return p
    n = _norm(p)
    if not _NAME.match(n):
        raise PolicyError(f"{where}: {raw!r} is neither a name, `*.name`, an address, a keyword nor `*`")
    return n


def app_key(app: str) -> str:
    """The rules an app is judged by: a container known only by its address or its image is `@unnamed`."""
    return "@unnamed" if (_is_address(app) or str(app).startswith("image:")) else str(app)


class Policy:
    def __init__(self, rules: dict):
        self.rules = rules

    @classmethod
    def load(cls, path: str = POLICY_FILE, extra: str | None = None) -> "Policy":
        try:
            with open(path, encoding="utf-8") as f:
                doc = yaml.safe_load(f)
        except FileNotFoundError:
            raise PolicyError(f"{path}: missing — the image must carry it (Dockerfile: COPY *.yaml)")
        except yaml.YAMLError as e:
            raise PolicyError(f"{path}: not YAML ({e})")
        apps = (doc or {}).get("apps") if isinstance(doc, dict) else None
        if not isinstance(apps, dict) or not apps:
            raise PolicyError(f"{path}: `apps:` must be a mapping of app → list of patterns")
        rules: dict = {}
        for app, pats in apps.items():
            if not isinstance(pats, list):
                raise PolicyError(f"{path}: {app}: a list of patterns, not {type(pats).__name__}")
            rules.setdefault(str(app), []).extend(_pattern(p, f"{path}: {app}") for p in pats)
        if extra is None:
            extra = os.environ.get("SECURITY_EGRESS_EXTRA", "")
        for part in extra.split(";"):
            if not part.strip():
                continue
            app, sep, pats = part.partition("=")
            if not sep or not app.strip() or not pats.strip():
                raise PolicyError(f"SECURITY_EGRESS_EXTRA: {part.strip()!r} is not `app=pattern pattern`")
            rules.setdefault(app.strip(), []).extend(
                _pattern(p, f"SECURITY_EGRESS_EXTRA: {app.strip()}") for p in pats.replace(",", " ").split())
        return cls(rules)

    @staticmethod
    def _match(pat: str, names: set, ip: str, ports: list) -> bool:
        if pat == "*":
            return True
        if pat in PORT_CLASSES:
            return bool(ports) and all(str(p) in PORT_CLASSES[pat] for p in ports)
        if _is_address(pat):
            try:
                return ipaddress.ip_address(ip) in ipaddress.ip_network(pat, strict=False)
            except ValueError:
                return False
        if pat.startswith("*."):
            return any(n.endswith(pat[1:]) for n in names)
        return pat in names

    def judge(self, apps, names, ip: str, ports=None, local: str = "") -> tuple[bool, str]:
        """(declared, why) for one destination: `why` names the rule each app matched, or the apps nobody
        declared for it. `names` must be the names the office's resolver answered, inside the window."""
        if local:
            return True, "local"
        seen = {_norm(n) for n in (names or []) if n}
        hits, missing = [], []
        for app in (apps or ["?"]):
            rule = next((p for p in self.rules.get(app_key(app), []) if self._match(p, seen, ip, list(ports or []))), None)
            if rule is None:
                missing.append(app)
            else:
                hits.append(f"{app}: {rule}")
        if missing:
            return False, "undeclared: " + ", ".join(missing)
        return True, "; ".join(hits)
