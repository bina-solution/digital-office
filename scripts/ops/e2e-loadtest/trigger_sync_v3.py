#!/usr/bin/env python3
"""trigger_sync_v3.py — manually kicks the REAL v3 sync engine (`syncV3Main0001`, "Sync v3
Reconcile") instead of the legacy `SyncScanner00001`, which explicitly skips every registry entry
with `engine:'v3'` (all of ours). This is the same workflow the natural 15-minute schedule fires;
triggering it manually just runs that pass early — it processes the WHOLE registry (all real pipes
too), same as the schedule would, not something additional/riskier."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                                "apps", "indox", "hooks"))
import demo  # noqa: E402

if __name__ == "__main__":
    ck = demo.login()
    if not ck:
        sys.exit("n8n login failed")
    print("[trigger_sync_v3] running syncV3Main0001 (Sync v3 Reconcile) ...")
    print("[trigger_sync_v3] result:", demo.run_wf(ck, "syncV3Main0001", timeout=180))
