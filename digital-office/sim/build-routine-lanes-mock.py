#!/usr/bin/env python3
"""build-routine-lanes-mock — one self-contained page for «עזריה שגרה» (lanes, budgets, the gate).

WHY A BUILDER. The page must compute its money with the office's own code and draw its sidebar with
the harness's own words, so both arrive here from their real sources instead of a copy:

  * `apps/bina-ds/plugins/cost-meter/lib/pricing.js` + `lib/cost.js` — inlined and loaded by the page
    as Blob modules: every ₪ in the demo is produced by the arithmetic that will produce it live;
  * `platform-base/bina-ui/theme-tokens.css` — the office palette, verbatim (the artifact is
    gitignored for exactly this reason: a palette copy lives in a build artifact, never in a tracked
    surface — gate G27).

    python3 digital-office/sim/build-routine-lanes-mock.py

Output (build artifact, gitignored): ci-artifacts/routine-lanes-mock/routine-lanes-mock.html
"""
from __future__ import annotations

import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SRC = HERE / "routine-lanes-mock.src.html"
PLUGIN = REPO / "apps" / "bina-ds" / "plugins" / "cost-meter"
TOKENS = REPO / "platform-base" / "bina-ui" / "theme-tokens.css"
DEFAULT_OUT = REPO / "ci-artifacts" / "routine-lanes-mock"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    for path in (SRC, PLUGIN / "lib" / "pricing.js", PLUGIN / "lib" / "cost.js", TOKENS):
        if not path.exists():
            sys.exit(f"missing source {path} — this builder reads the product, it does not copy it")
    args.out.mkdir(parents=True, exist_ok=True)
    html = SRC.read_text(encoding="utf8")
    html = html.replace("__PRICING_SRC__", (PLUGIN / "lib" / "pricing.js").read_text(encoding="utf8"))
    html = html.replace("__COST_SRC__", (PLUGIN / "lib" / "cost.js").read_text(encoding="utf8"))
    html = html.replace(
        '<link rel="stylesheet" href="../../platform-base/bina-ui/theme-tokens.css" />',
        "<style>\n" + TOKENS.read_text(encoding="utf8") + "\n</style>",
    )
    target = args.out / "routine-lanes-mock.html"
    target.write_text(html, encoding="utf8")
    print(f"{target}  ({target.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
