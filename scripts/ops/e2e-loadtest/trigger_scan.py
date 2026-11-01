#!/usr/bin/env python3
"""trigger_scan.py — manually kick the sync scanner once, instead of waiting up to 15 minutes for
the natural schedule, so a proof run gets a real timing number promptly. Reuses demo.py's own
login()/run_wf() against SyncScanner00001 (same workflow `bbox indox demo run <name> --wait` calls
in its own wait loop)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                                "apps", "indox", "hooks"))
import demo  # noqa: E402

if __name__ == "__main__":
    ck = demo.login()
    if not ck:
        sys.exit("n8n login failed")
    print("[trigger_scan] running SyncScanner00001 ...")
    print("[trigger_scan] result:", demo.run_wf(ck, demo.SCANNER_WF, timeout=90))
