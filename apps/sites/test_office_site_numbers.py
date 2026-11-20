"""sites — what a site the OFFICE serves says on its card is about its visitors, not about the office.

Exampleu's clone (2026-11-09, DGO-1591) has no domain: nobody outside the office can reach it. Its card
said «1011 ביקורים 7 ימים» — every request the office itself made to its copy (the console, the app's
own host, the checks) — and «3 שגיאות פתוחות» — the three scans, each refusing to run without a domain.
This test proves, against a real store in a temporary directory:

  * a request on one of the site's own public domains is a visit; one from the console, the app's own
    host or the internal address is not;
  * a scan of a site the office serves and has not published records ONE «מידע» finding per check and
    no error — and resolves the `no_host` errors an earlier scan left; a site its machine serves with no
    host still gets the error (that one IS misconfigured), and the checks themselves are never called
    for the unpublished one;
  * once published (its public path only, no `hosts`): the scans and the uptime probe are given its
    domain, not «no domain»; the office's own checks arriving through that domain are not visits; a bot
    is a hit and a bot, not a visitor; a visitor is counted once an hour per address, not per request.

    python3 apps/sites/test_office_site_numbers.py
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ["SITES_STATE_DIR"] = tempfile.mkdtemp()
os.environ["SITES_PUBLIC_DIR"] = tempfile.mkdtemp()
os.environ["SITES_SCHEDULER"] = "0"
import checks  # noqa: E402
import public  # noqa: E402
import scheduler  # noqa: E402
import store  # noqa: E402

public.bundle = lambda force=False: None


def visits(sid):
    return store.visits_total(sid, 7).get("hits") or 0


def main():
    store.init()
    draft = {"id": "draft", "public": {"mode": "office", "entries": []}, "hosts": [], "monitor": False}
    live = {"id": "live", "public": {"mode": "office", "entries": [{"domain": "live.co.il", "path": "/"}]}}
    for s in (draft, live):
        store.upsert_site(s)
        root = public.cache_dir(s["id"])
        root.mkdir(parents=True, exist_ok=True)
        (root / "index.html").write_text("<html><head></head><body>x</body></html>")
    draft, live = store.get_site("draft"), store.get_site("live")

    # ── visits: the site's own domain only ──────────────────────────────────────────────────────────
    for host, prefix in (("console.office.example", "/a/sites"), ("sites.office.example", ""),
                         ("sites:8979", ""), ("", "")):
        public.serve(draft, "", host=host, prefix=prefix)
        public.serve(live, "", host=host, prefix=prefix)
    assert visits("draft") == 0 and visits("live") == 0, (visits("draft"), visits("live"))
    public.serve(live, "", host="live.co.il", ip="203.0.113.7")
    public.serve(live, "", host="LIVE.co.il:443", ip="203.0.113.7")
    assert visits("live") == 2, visits("live")

    # ── a published site: the office's own checks, bots and the same visitor twice ───────────────────
    import json as _json
    import checks.http as H
    assert H.UA.startswith(checks.visits.OWN_UA), H.UA          # the marker IS what the checks send
    # …and a machine's log leaves the office's own checks out the same way: not a hit, not a bot
    line = lambda ua: _json.dumps({"t": "2026-11-09T10:00:00+00:00", "ip": "10.0.0.5", "u": "/", "s": 200,
                                   "b": 10, "r": "", "a": ua})
    agg = checks.visits.aggregate([line(H.UA), line("Mozilla/5.0"), line("Googlebot/2.1")])
    assert (agg["hits"], agg["bots"], agg["uniques"]) == (2, 1, 1), agg
    before = store.visits_total("live", 7)
    public.serve(live, "", host="live.co.il", ua=H.UA, ip="10.0.0.5")              # the uptime probe
    public.serve(live, "", host="live.co.il", ua="Mozilla/5.0 (compatible; Googlebot/2.1)", ip="93.184.216.17")
    public.serve(live, "index.html", host="live.co.il", ua="Mozilla/5.0", ip="203.0.113.7")  # same visitor
    public.serve(live, "", host="live.co.il", ua="Mozilla/5.0", ip="198.51.100.9")        # a new one
    after = store.visits_total("live", 7)
    got = {k: (after.get(k) or 0) - (before.get(k) or 0) for k in ("hits", "uniques", "bots")}
    assert got == {"hits": 3, "uniques": 1, "bots": 1}, got           # the probe is not even a hit
    assert (after.get("uniques") or 0) == 2, after                    # 203.0.113.7 once, 198.51.100.9 once
    # a flood of fresh addresses: hits, but no more visitors past the cap (the set stays bounded)
    cap, public.SEEN_CAP = public.SEEN_CAP, len(next(iter(public._seen.values())))
    try:
        public.serve(live, "", host="live.co.il", ua="Mozilla/5.0", ip="192.0.2.1")
        assert (store.visits_total("live", 7).get("uniques") or 0) == 2
        assert max(len(s) for s in public._seen.values()) == public.SEEN_CAP
    finally:
        public.SEEN_CAP = cap

    # ── scans of a draft: information, never an error, and the old errors resolve ───────────────────
    for name in checks.SCAN_CHECKS:                      # what the scans recorded before this change
        store.record_findings("draft", name, [{"code": "no_host", "severity": "error",
                                               "title": "לא הוגדר דומיין לאתר", "url": ""}])
    assert sum(1 for f in store.findings("draft") if f["severity"] == "error") == len(checks.SCAN_CHECKS)
    real_run = checks.run
    checks.run = lambda *a, **k: (_ for _ in ()).throw(AssertionError("a draft has nothing to scan"))
    try:
        out = scheduler.run_scan("draft")
    finally:
        checks.run = real_run
    assert all(v["state"] == "info" for v in out["checks"].values()), out
    open_ = store.findings("draft")
    assert not [f for f in open_ if f["severity"] == "error"], open_
    assert sorted(f["code"] for f in open_) == ["not_published"] * len(checks.SCAN_CHECKS), open_

    # ── published through its public path alone: the checks and the uptime probe get its domain ─────
    store.upsert_site({"id": "pathonly", "hosts": [], "monitor": False, "public": {"mode": "office", "entries": [
        {"domain": "www.e.co.il", "path": "/", "redirect": True}, {"domain": "e.co.il", "path": "/"}]}})
    seen = []
    real_run, real_probe = checks.run, scheduler.uptime.probe
    checks.run = lambda name, site, **k: seen.append((name, site["hosts"])) or {"state": "ok", "findings": []}
    scheduler.uptime.probe = lambda site, **k: seen.append(("uptime", site["hosts"])) or {"ok": True, "url": ""}
    try:
        scheduler.run_scan("pathonly", ["security"])
        scheduler.check_uptime(store.get_site("pathonly"), notify=False)
    finally:
        checks.run, scheduler.uptime.probe = real_run, real_probe
    assert seen == [("security", ["e.co.il"]), ("uptime", ["e.co.il"])], seen
    assert public.public_hosts(store.get_site("draft")) == []            # a draft has none to give

    # ── a site its MACHINE serves, with no host, is still told it has none ──────────────────────────
    store.upsert_site({"id": "bare", "hosts": [], "monitor": False})
    out = scheduler.run_scan("bare", ["security"])
    assert out["checks"]["security"]["state"] == "error", out
    assert [f["code"] for f in store.findings("bare")] == ["no_host"], store.findings("bare")
    print("office site numbers: ok — visits only on the site's own domain (0 from the office, 2 from it); "
          "the office's own probe not counted, a bot a bot, a visitor once an hour; a site published by its "
          f"path alone is scanned and probed on its domain; a draft's {len(checks.SCAN_CHECKS)} scans are "
          "information and its old errors resolved")


if __name__ == "__main__":
    main()
