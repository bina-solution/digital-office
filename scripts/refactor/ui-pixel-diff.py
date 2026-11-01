#!/usr/bin/env python3
"""ui-pixel-diff — gate G4: the refactored UI renders the same as before the refactor.

    python3 scripts/refactor/ui-pixel-diff.py [--threshold 2.0] [--out ci-artifacts/ui-map/diff]

G1 proves the rendered COMPOSE CONFIG is unchanged. That says nothing about what a user sees: a
compiled console tile can point somewhere subtly wrong, an app can lose its stylesheet, a proxy
alias can resolve to the wrong backend — and every one of those renders a page and passes every
config gate. G4 is the only check that looks at pixels.

    reference   .ci-cd/ui-map/screenshots/    committed pre-refactor baseline
    candidate   ci-artifacts/screenshots-ui/  what `bbox ui-map` just captured

Only views present in BOTH are compared; the candidate legitimately has more (third-party apps
the reference run skipped). A view that vanished from the candidate is a hard failure — that is
a screen the refactor stopped rendering.

NOTE this is deliberately NOT digital-office/verify/ui_map_diff.py. That tool diffs design MOCKS
against real captures and hardcodes a /home/user/... path; it answers "does the build match the
design", not "did the refactor change what renders". Different question, different gate.

% differing = share of pixels whose max per-channel delta exceeds PIXEL_TOL — the same tolerance
the mock gate uses, so antialiasing and font hinting do not register as change.

WHAT THIS GATE CAN AND CANNOT PROVE
-----------------------------------
The seed is NOT deterministic. my-docs items render `created_at` timestamps and generated ids
(`ite_62382341445f48`); mail carries fresh message ids. Those pixels change on every seed run, so
a capture can never be byte-equal to a reference taken on another day, and a low threshold
measures seed churn rather than regression. Verified, not assumed: the worst offenders' UI source
(index.html / app.js / style.css) is BYTE-IDENTICAL across the refactor, while their screenshots
differed by ~14%.

So the gate is scoped to what it can actually decide:
  * a reference view MISSING from the capture is a hard failure at any threshold — that is a
    screen which stopped rendering, and it is completely seed-independent
  * a view over --threshold is structural breakage (blank page, stylesheet lost, layout collapse),
    not a changed date. The default is deliberately loose for that reason.
Refresh the reference (`--rebaseline`) whenever you accept the current UI as correct.
"""
import argparse, json, pathlib, sys

try:
    from PIL import Image, ImageChops
except ImportError:
    sys.exit("Pillow required: pip install pillow")

REPO = pathlib.Path(__file__).resolve().parents[2]
REF = REPO / ".ci-cd/ui-map/screenshots"
CAND = REPO / "ci-artifacts/screenshots-ui"
PIXEL_TOL = 28          # per-channel delta below this is rendering noise, not change


def pct_differing(a: Image.Image, b: Image.Image) -> float:
    if a.size != b.size:
        b = b.resize(a.size)
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    # collapse to the max channel, then count pixels above tolerance via the histogram
    mx = max_channel(diff)
    hist = mx.histogram()
    over = sum(hist[PIXEL_TOL + 1:])
    return 100.0 * over / float(a.size[0] * a.size[1])


def max_channel(img: Image.Image) -> Image.Image:
    r, g, b = img.split()
    return ImageChops.lighter(ImageChops.lighter(r, g), b)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=25.0,
                    help="max %% differing pixels per view before it counts as a regression")
    ap.add_argument("--out", default="ci-artifacts/ui-map/pixel-diff.json")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--rebaseline", action="store_true",
                    help="copy the current capture over the reference set and exit")
    a = ap.parse_args()

    if not REF.is_dir():
        sys.exit(f"no reference set at {REF.relative_to(REPO)}")
    if not CAND.is_dir():
        sys.exit(f"no candidate capture at {CAND.relative_to(REPO)} — run: ./bbox ui-map")

    if a.rebaseline:
        import shutil
        n = 0
        for p in CAND.glob("*.png"):
            shutil.copy2(p, REF / p.name); n += 1
        print(f"rebaselined {n} view(s) into {REF.relative_to(REPO)} — commit them to make this "
              f"the reference the next run is judged against.")
        return 0

    ref = {p.name: p for p in REF.glob("*.png")}
    cand = {p.name: p for p in CAND.glob("*.png")}
    missing = sorted(set(ref) - set(cand))
    common = sorted(set(ref) & set(cand))

    scores = {}
    for name in common:
        try:
            scores[name] = pct_differing(Image.open(ref[name]), Image.open(cand[name]))
        except OSError as e:
            scores[name] = float("inf")
            print(f"  ! {name}: unreadable ({e})")

    over = {n: s for n, s in scores.items() if s > a.threshold}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])

    out = REPO / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "threshold_pct": a.threshold, "pixel_tol": PIXEL_TOL,
        "compared": len(common), "missing_from_candidate": missing,
        "over_threshold": over, "scores": scores,
    }, indent=2), encoding="utf-8")

    print(f"G4 — compared {len(common)} view(s) vs the pre-refactor reference "
          f"(threshold {a.threshold}% differing pixels)")
    worst = [f"{n} {s:.2f}%" for n, s in ranked[:5]]
    print("  worst: " + ", ".join(worst) if worst else "  (nothing compared)")
    if a.verbose:
        for n, s in ranked:
            print(f"    {s:6.2f}%  {n}")

    if missing:
        print(f"\nG4 FAIL — {len(missing)} reference view(s) absent from the capture; the refactor "
              f"stopped rendering them:")
        for n in missing[:12]:
            print(f"  {n}")
        return 1
    if over:
        print(f"\nG4 FAIL — {len(over)} view(s) over {a.threshold}%:")
        for n, s in sorted(over.items(), key=lambda kv: -kv[1]):
            print(f"  {s:6.2f}%  {n}")
        print(f"\n  detail: {a.out}")
        return 1

    print(f"\nG4 PASS — every compared view is within {a.threshold}% of the pre-refactor "
          f"reference. detail: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
