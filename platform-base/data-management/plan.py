"""plan - the read-only preflight for a restore: what is in this archive, what is on this target,
and what a restore would overwrite, create, or leave behind.

WHY. Before this existed the import screen offered a write with no way to see what it touched, so
approving a restore was a leap rather than a decision. A preflight writes NOTHING - it reads a
manifest and a live inventory and diffs them - which is also why it is available while the import
half itself is blocked.

WHAT IT DELIBERATELY DOES NOT DO: diff the manifest's `facts` against live row counts. The facts are
emitted by each app's own backup hook (FACT lines, deployment-archive.py:681); the live counts in
the inventory come from a different code path and are ESTIMATES - measured 2026-08-24, the archive
recorded ocr_cache=116 while the live inventory reported rows=0 for the same table, because an
un-ANALYZEd table reports 0. Diffing them would have announced catastrophic data loss that had not
happened. The facts are therefore reported VERBATIM, labelled as export-time, and never subtracted
from anything. One definition, or none - the same rule the coverage report follows for `unclaimed`.

Everything this DOES diff is matched by exact name, so it is comparable by construction.
"""

VOL_PREFIX, BIND_PREFIX, SEC_PREFIX, APP_PREFIX = "volumes/", "binds/", "secrets/", "apps/"


def _vol_short(rel):
    """volumes/<short>.tar.gz and volumes/<short>.HANDLED both name the same volume."""
    base = rel[len(VOL_PREFIX):]
    for suffix in (".tar.gz", ".HANDLED", ".tar"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def build_plan(man, live):
    """Pure. Two dicts in, one plan out - no docker, no network, so it is directly testable."""
    arts = man.get("artifacts") or {}
    live_vols = live.get("volumes") or []
    live_short = {v.get("short"): v for v in live_vols if v.get("short")}

    overwrite, create, handled, binds, secrets, app_backups = [], [], [], [], [], []
    for rel in sorted(arts):
        e = arts[rel] or {}
        kind, size = e.get("kind"), e.get("bytes") or 0
        row = {"artifact": rel, "bytes": size, "sha256": e.get("sha256") or "", "kind": kind}
        if rel.startswith(VOL_PREFIX):
            short = _vol_short(rel)
            row["volume"] = short
            if kind == "skipped":
                row["note"] = e.get("note") or ""
                handled.append(row)
            elif short in live_short:
                row["live_size"] = live_short[short].get("size")
                row["live_bytes"] = live_short[short].get("bytes")
                overwrite.append(row)
            else:
                create.append(row)
        elif rel.startswith(BIND_PREFIX):
            binds.append(row)
        elif rel.startswith(SEC_PREFIX):
            secrets.append(row)
        elif rel.startswith(APP_PREFIX):
            row["app"] = rel.split("/")[1] if "/" in rel[len(APP_PREFIX):] + "/" else None
            parts = rel.split("/")
            row["app"] = parts[1] if len(parts) > 2 else None
            app_backups.append(row)

    in_archive = {_vol_short(r) for r in arts if r.startswith(VOL_PREFIX)}
    target_only = [{"volume": v.get("short"), "size": v.get("size"), "bytes": v.get("bytes") or 0,
                    "coverage": v.get("coverage"), "used_by": v.get("used_by")}
                   for v in live_vols if v.get("short") not in in_archive]
    target_only.sort(key=lambda r: -(r["bytes"] or 0))

    same_deployment = bool(man.get("deployment_name")
                           and man.get("deployment_name") == live.get("deployment"))

    warnings = []
    if same_deployment:
        warnings.append(
            "SAME DEPLOYMENT: this archive was taken from the host it would be restored INTO "
            "(%s). A restore overwrites the live data this plan was computed from, and the "
            "archiver refuses it without --force." % man.get("deployment_name"))
    if man.get("mode") and man.get("mode") != "full":
        warnings.append(
            "MODE=%r, not 'full': this archive carries what that mode captures, which is not "
            "necessarily every store on the host. Read the overwrite/create lists as the whole of "
            "what it can restore." % man.get("mode"))
    if not man.get("quiesced", True):
        warnings.append(
            "NOT QUIESCED: the stack was running while this archive was taken, so its stores are "
            "not guaranteed mutually consistent (a dump and a volume tar may disagree).")
    if secrets:
        warnings.append(
            "CARRIES %d SECRET ARTIFACT(S) including the environment file: restoring replaces "
            "credentials on the target, not just data." % len(secrets))
    if target_only:
        warnings.append(
            "%d live volume(s) are NOT in this archive. A restore does not delete them - they "
            "SURVIVE - so the result is the archive's data plus this leftover state, which is not "
            "a faithful clone of the source." % len(target_only))
    empty = [r for r in (overwrite + create + binds + app_backups) if not r["bytes"]]
    if empty:
        warnings.append(
            "%d artifact(s) are ZERO BYTES: %s. An empty artifact restores as empty."
            % (len(empty), ", ".join(sorted(r["artifact"] for r in empty))[:200]))

    return {
        "archive": {k: man.get(k) for k in
                    ("deployment_name", "compose_project", "created_utc", "mode", "quiesced",
                     "format_version", "total_bytes")},
        "target": {"deployment": live.get("deployment"), "project": live.get("project")},
        "same_deployment": same_deployment,
        "counts": {"overwrite": len(overwrite), "create": len(create), "handled": len(handled),
                   "binds": len(binds), "secrets": len(secrets), "app_backups": len(app_backups),
                   "target_only": len(target_only)},
        "volumes": {"overwrite": overwrite, "create": create, "handled_by_app_hook": handled,
                    "target_only": target_only},
        "app_backups": app_backups,
        "binds": binds,
        "secrets": secrets,
        # Verbatim, and never diffed. See the module docstring.
        "facts_at_export": man.get("facts") or {},
        "warnings": warnings,
    }


def self_test():
    man = {
        "deployment_name": "posnet", "mode": "config", "quiesced": False, "total_bytes": 10,
        "facts": {"indox": {"incoming_documents": "1"}},
        "artifacts": {
            "volumes/keep.tar.gz": {"kind": "volume", "bytes": 5, "sha256": "a"},
            "volumes/brandnew.tar.gz": {"kind": "volume", "bytes": 7, "sha256": "b"},
            "volumes/hooked.HANDLED": {"kind": "skipped", "bytes": 0, "note": "claimed by n8n"},
            "binds/some__path.tar.gz": {"kind": "bind", "bytes": 3, "sha256": "c"},
            # 0 bytes and NOT a HANDLED marker - the case the zero-byte warning is for. A
            # HANDLED artifact is 0 bytes by design and must never trip it.
            "binds/empty__path.tar.gz": {"kind": "bind", "bytes": 0, "sha256": ""},
            "secrets/.env": {"kind": "secret", "bytes": 9, "sha256": "d"},
            "apps/n8n/n8n.dump": {"kind": "app-backup", "bytes": 11, "sha256": "e"},
        },
    }
    live = {"deployment": "posnet", "project": "p",
            "volumes": [{"short": "keep", "size": "1KB", "bytes": 1024},
                        {"short": "leftover", "size": "2KB", "bytes": 2048}]}
    p = build_plan(man, live)

    cases = [
        ("a volume in both is an OVERWRITE", p["counts"]["overwrite"], 1),
        ("a volume only in the archive is a CREATE", p["counts"]["create"], 1),
        ("a HANDLED volume is not counted as a write", p["counts"]["handled"], 1),
        ("a live volume absent from the archive is target_only",
         [r["volume"] for r in p["volumes"]["target_only"]], ["leftover"]),
        ("the overwrite row carries what it replaces",
         p["volumes"]["overwrite"][0]["live_size"], "1KB"),
        ("app backups are attributed", p["app_backups"][0]["app"], "n8n"),
        ("binds and secrets are separated", (p["counts"]["binds"], p["counts"]["secrets"]), (2, 1)),
        ("same deployment is detected", p["same_deployment"], True),
        ("facts are carried verbatim, not diffed",
         p["facts_at_export"], {"indox": {"incoming_documents": "1"}}),
    ]
    # Every warning below is one a reviewer must see before approving a write.
    joined = " | ".join(p["warnings"])
    for label, needle in (("same-deployment", "SAME DEPLOYMENT"), ("partial mode", "MODE="),
                          ("not quiesced", "NOT QUIESCED"), ("secrets", "SECRET ARTIFACT"),
                          ("survivors", "SURVIVE"), ("zero-byte", "ZERO BYTES")):
        cases.append(("warns about %s" % label, needle in joined, True))

    bad = 0
    for name, got, want in cases:
        ok = got == want
        bad += 0 if ok else 1
        print("  [%s] %s (got %r, want %r)" % ("ok " if ok else "FAIL", name, got, want))
    print("")
    print("plan self-test: %d/%d passed" % (len(cases) - bad, len(cases)))
    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    sys.exit(self_test())
