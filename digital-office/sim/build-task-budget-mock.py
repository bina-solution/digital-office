#!/usr/bin/env python3
"""build-task-budget-mock — one self-contained page for the model the owner stated on 2026-10-13.

WHY A BUILDER RATHER THAN A HAND-WRITTEN PAGE. Three of the things the demo must not paraphrase
arrive at build time, from the real sources, so the artifact cannot drift from them:

  * the office's price book and its arithmetic — `apps/bina-ds/plugins/cost-meter/lib/pricing.js` and
    `lib/cost.js`, embedded as module source that the page loads as Blob modules. Every figure in the
    money column is computed by the code that will compute it in the product;
  * the office palette, inlined from `platform-base/bina-ui/theme-tokens.css` — the same rule the
    other builders follow: the artifact carries a copy, so it lives under the gitignored
    `ci-artifacts/` and never becomes a second palette in a tracked surface (gate G27);
  * the numbers the demo opens with are the ones measured on 2026-10-13 for the item it shows
    (`ui2-060`: 502 requests, 235M tokens, $1.26), written in the SOURCE once, not typed in the page.

    python3 digital-office/sim/build-task-budget-mock.py
    python3 digital-office/sim/build-task-budget-mock.py --out ci-artifacts/task-budget-mock

Output (build artifact, gitignored): ci-artifacts/task-budget-mock/task-budget-mock.html
"""
from __future__ import annotations

import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SRC = HERE / "task-budget-mock.src.html"
PLUGIN = REPO / "apps" / "bina-ds" / "plugins" / "cost-meter"
TOKENS = REPO / "platform-base" / "bina-ui" / "theme-tokens.css"
DEFAULT_OUT = REPO / "ci-artifacts" / "task-budget-mock"


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
    target = args.out / "task-budget-mock.html"
    target.write_text(html, encoding="utf8")
    print(f"{target}  ({target.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
