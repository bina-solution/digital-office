"""firsts.py — the first time an address gets into this office: a line for the owner, with «חסום» (DGO-1329).

The owner, 2026-11-03 (the group): «כל פעם שip חדש פונה אלינו באחת הלשכות ואז אני יכול גם להגיב אם לחסום». A new
address is news only when it GOT IN — the evidence the new-country alert needs since e47f83b6 (2026-11-04: 40 alerts
in three days were scanners bounced to the sign-in page): an address that completed a sign-in here (SSO or SSH,
Trust.signed — 30 days), a real status (200–399), a way in (private, remote, auth) and a path that is not the sign-in
page. Each address once; the addresses already signed in when the app starts are its past, not news.

Pure: app.py hands in the batch, what it already knows and Trust.signed — so the decision is tested without the app.
"""
WAYS_IN = ("private", "remote", "auth")


def new_addresses(batch, known, signed):
    """The hits, one per address, of addresses that got in and are not in `known`. The CALLER adds an address to
    `known` once it has decided about it — so an address whose notice failed half-way is judged again at its next hit,
    never lost (the second reader)."""
    out, seen = [], set()
    for h in batch or []:
        ip = h.get("ip") or ""
        if not ip or ip in known or ip in seen or ip not in signed or h.get("kind") not in WAYS_IN:
            continue
        try:
            status = int(h.get("status") or 0)
        except (TypeError, ValueError):
            continue
        if not 200 <= status < 400 or str(h.get("path") or "").startswith("/login"):
            continue
        seen.add(ip)
        out.append(h)
    return out


def is_news(why, first_ok, watching_since):
    """Whether an address that got in is news for the owner: a public address that is not this office's own or the
    herd's (Trust.why says «signed-in» — never the HP's home address after its provider changed it, or a new office's
    tunnel peer), whose FIRST successful sign-in is after this process began watching — the sign-ins before that, a
    first install reading six hours of logs back included, are the past, on the board."""
    return why == "signed-in" and bool(first_ok) and float(first_ok) > float(watching_since or 0)


def ban_answer(ip):
    """The «חסום» a notice offers: this office's own ban (the security app's POST /api/bans), executed HERE — a linked
    office may read this office's security and never write it (app.py guard_write)."""
    return [{"id": "block", "label": "חסום", "op": "security.ban", "args": {"ip": ip}}]
