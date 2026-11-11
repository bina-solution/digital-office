#!/usr/bin/env python3
"""handoff-shell-proof — the REAL console shell, driven through a hand-off, checked and photographed (DGO-1434).

The console's own index.html, app.js, desktop.js and handoffs.js from this checkout run in a headless
Chromium (Playwright's chrome-headless-shell), with the few APIs the shell asks for answered inside the page
and a SCRIPTED hand-off record — `needed` at 2 s, `done` at 9 s, as browser42 would publish it — so every step
of «Continue with Google» on the desktop and the phone can be shown and asserted without an office:

    python3 digital-office/sim/handoff-shell-proof.py            # check every scenario (exit 1 on a failure)
    python3 digital-office/sim/handoff-shell-proof.py --shots    # …and photograph each into ci-artifacts/

What a check asserts is the window manager's own model and the page's address, read at a moment of the
script (`dump@<s>`): which windows are open, where (the halves of handoffs.js `beside`, or the place the app
had), which carries the band or the pill, which is focused, where the address points, whether the phone's
way-back band is up. The presses are the person's (`drive=`): «ביטול», the browser window closed, «close all»,
focusing the app or another app, a second press (a new episode).

Two things about the camera, both measured: `--timeout` only bounds the page LOAD (every shot was taken right
after it), so the script runs under `--virtual-time-budget`; and the windows' 0.45 s CSS transition does not
advance there, so it is switched off in the page (the model is what is asserted; the pixels follow it).

The pictures inside the two windows are the owner's own (ci-artifacts/handoff-mock/src, cut from his
screenshot of 14:54; never tracked). Without them the frames are blank. Output: ci-artifacts/handoff-proof/.
A workbench tool: never shipped, never run by CI.
"""
from __future__ import annotations

import argparse
import glob
import html as htmlmod
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
# CONSOLE_STATIC=<dir> runs another copy of the shell (the committed one, to see a check fail on old code)
STATIC = pathlib.Path(os.environ.get("CONSOLE_STATIC") or REPO / "platform-base" / "console" / "static")
PIXELS = REPO / "ci-artifacts" / "handoff-mock" / "src"
OUT = REPO / "ci-artifacts" / "handoff-proof"
CLAUDE, B42 = "bina-claude.hp-laptop", "browser42.hp-laptop"
SENTENCE = "בחרו את חשבון Google שלכם בדפדפן הלשכה — Claude יתחבר מעצמו ותחזרו אליו."

SHIM = r"""<script>
(function () {
  const q = new URLSearchParams(location.search), T0 = Date.now();
  // script=needed@2,done@9 — the record's state by the second; a trailing 2 is a second episode (a new press)
  const SCRIPT = (q.get("script") || "").split(",").filter(Boolean).map(p => p.split("@"));
  const MODS = __MODS__;
  const state = () => { const t = (Date.now() - T0) / 1000; let s = null; for (const [st, at] of SCRIPT) if (t >= +at) s = st; return s; };
  const json = o => new Response(JSON.stringify(o), { status: 200, headers: { "Content-Type": "application/json" } });
  window.fetch = async (url) => {
    const u = String(url);
    if (u.startsWith("/api/me")) return json({ name: "בעלים" });
    if (u.startsWith("/api/modules")) return json({ modules: MODS });
    if (u.startsWith("/api/office")) return json({ installed: true, office: { name: "הלשכה", animal: "eagle", hue: "sky" } });
    if (u.startsWith("/api/version")) return json({ version: "proof" });
    if (u.startsWith("/api/handoffs")) {
      const s = state() || "", ep = /2$/.test(s) ? "e2" : "e1", st = s.replace(/2$/, "");
      return json({ handoffs: st ? [{ at: "__B42__", for: "__CLAUDE__", slug: "claude-signin", state: st, id: ep, age: 1,
        sentence: st === "needed" ? "__SENTENCE__" : st === "failed" ? "לא הושלם" : "" }] : [] });
    }
    if (u.startsWith("/api/")) return json({});
    return new Response("", { status: 404 });
  };
  try {
    sessionStorage.clear(); localStorage.clear();
    if (q.get("theme")) localStorage.setItem("do-theme", q.get("theme"));
    if (q.has("desktop")) {
      // the app's window where the owner had it at 14:54: 29/1199 from the left, 630x443 of a 1199x639 view
      const W = innerWidth, H = innerHeight;
      const wins = [{ mid: "__CLAUDE__", w: Math.round(W * .525), h: Math.round((H - 136) * .86),
                      cx: Math.round(W * .024 + W * .525 / 2), cy: Math.round(48 + (H - 136) * .07 + (H - 136) * .43), lf: 2 }];
      // withbro: the office browser already open, parked on the right flank (where a person watches it from)
      if (q.has("withbro")) wins.push({ mid: "__B42__", w: 640, h: 480, cx: W - 120, cy: Math.round(H / 2), lf: 1 });
      localStorage.setItem("do-desktop-layout", JSON.stringify({ W, wins }));
    }
  } catch (e) {}
  const tile = w => String(w.mid).replace(/^ext:/, "");
  const act = {
    cancel: () => { const b = document.querySelector('.dk-ho [data-ho="cancel"], .handoff-back-btn'); if (b) b.click(); },
    closebro: () => { const x = [...document.querySelectorAll(".dk-win")].find(e => e.querySelector(".dk-ho-pill")); if (x) x.querySelector(".dk-l.close").click(); },
    closeall: () => BinaDesktop.wm.wins().slice().forEach(w => BinaDesktop.wm.close(w)),
    focusapp: () => { const w = BinaDesktop.wm.wins().find(x => tile(x) === "__CLAUDE__"); if (w) BinaDesktop.wm.focus(w); },
    dump: () => {
      const D = window.BinaDesktop && BinaDesktop.isOn();
      const pre = document.createElement("pre"); pre.id = "hdump";
      pre.textContent = JSON.stringify({ hash: location.hash, bar: !!document.querySelector(".handoff-back"),
        focused: D && BinaDesktop.wm.focused() ? tile(BinaDesktop.wm.focused()) : "",
        wins: D ? BinaDesktop.wm.wins().map(w => ({ tile: tile(w), cx: Math.round(w.cx), w: w.w, band: !!w.el.querySelector(".dk-ho"), pill: !!w.el.querySelector(".dk-ho-pill") })) : [] });
      document.body.appendChild(pre);
    },
  };
  for (const [a, at] of (q.get("drive") || "").split(",").filter(Boolean).map(p => p.split("@")))
    setTimeout(() => { if (a.startsWith("focus-")) { const d = document.querySelector('.dk-dock [data-mid="' + a.slice(6) + '"]'); if (d) d.click(); } else if (act[a]) act[a](); }, +at * 1000);
})();
</script>
<style>.dk-win.anim,.dk-win.anim *{transition:none!important}</style>
"""


def build(shell: pathlib.Path) -> None:
    shell.mkdir(parents=True, exist_ok=True)
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    page = re.sub(r'(href|src)="/([^"/][^"]*)"', lambda m: f'{m.group(1)}="{(STATIC / m.group(2)).as_uri()}"', page)
    for name, img, pos in (("claude-frame.html", "claude-stream.png", "50% 50%"), ("browser-frame.html", "browser-google.png", "70% 50%")):
        if (PIXELS / img).is_file():
            shutil.copy(PIXELS / img, shell / img)
        (shell / name).write_text('<!doctype html><meta charset="utf-8"><style>html,body{margin:0;height:100%}'
                                  f'img{{width:100%;height:100%;object-fit:cover;object-position:{pos};display:block}}</style>'
                                  f'<img src="{img}" alt="">', encoding="utf-8")
    base = shell.as_uri()
    remote = {"office": "hp-laptop", "label": "HP", "mark": {"color": "grey", "animal": "elephant"}}
    mods = [{"id": CLAUDE, "name": "בינה קלוד", "icon": "sparkles", "group": "ראשי", "order": 1, "embed": base + "/claude-frame.html#", "remote": remote},
            {"id": B42, "name": "דפדפן הלשכה", "icon": "monitor", "group": "ראשי", "order": 2, "embed": base + "/browser-frame.html#", "remote": remote}]
    mods += [{"id": i, "name": n, "icon": ic, "group": "עסק", "order": 10 + k} for k, (i, n, ic) in enumerate(
        [("drive", "קבצים", "folder"), ("mail", "מייל", "mail"), ("chat", "צ׳אט", "message"), ("meet", "פגישות", "mic")])]
    shim = (SHIM.replace("__MODS__", json.dumps(mods, ensure_ascii=False)).replace("__CLAUDE__", CLAUDE)
            .replace("__B42__", B42).replace("__SENTENCE__", SENTENCE))
    (shell / "index.html").write_text(page.replace("<script src=", shim + "<script src=", 1), encoding="utf-8")


def headless() -> str:
    found = os.environ.get("HEADLESS_SHELL") or next(iter(sorted(glob.glob(os.path.expanduser(
        "~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell")) +
        glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell")))), "")
    if not found:
        sys.exit("needs Playwright's chrome-headless-shell (HEADLESS_SHELL=<path>)")
    return found


def run(hs: str, url: str, size: str, ms: int, shot: pathlib.Path | None = None) -> str:
    args = [hs, "--headless", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
            "--allow-file-access-from-files", f"--window-size={size}", f"--virtual-time-budget={ms}"]
    args += [f"--screenshot={shot}"] if shot else ["--dump-dom"]
    r = subprocess.run(["perl", "-e", "alarm 60; exec @ARGV", *args, url], capture_output=True, text=True)
    return r.stdout


# W=1440: the app's own place (the seeded layout) and the two halves handoffs.js `beside` gives
DESK, PHONE = "1440,900", "390,844"
OWN = {"cx": round(1440 * .024 + 1440 * .525 / 2), "w": round(1440 * .525)}
HALF = 688
LEFT, RIGHT = round(720 - 8 - HALF / 2), round(720 + 8 + HALF / 2)
ON = "script=needed@2,done@9"

# name: (size, query, the moment to read, what must hold)
SCENARIOS = {
    "desk-open":        (DESK, f"desktop&{ON}", 6.5, {"focused": B42, CLAUDE: (LEFT, HALF, True, False), B42: (RIGHT, HALF, False, True)}),
    "desk-return":      (DESK, f"desktop&{ON}", 13.5, {"focused": CLAUDE, CLAUDE: (OWN["cx"], OWN["w"], False, False), B42: None}),
    "desk-cancel":      (DESK, f"desktop&{ON}&drive=cancel@5", 7.5, {"focused": CLAUDE, CLAUDE: (OWN["cx"], OWN["w"], False, False), B42: None}),
    "desk-close-bro":   (DESK, f"desktop&{ON}&drive=closebro@4.5", 7.0, {"focused": CLAUDE, CLAUDE: (OWN["cx"], OWN["w"], False, False), B42: None}),
    "desk-close-all":   (DESK, f"desktop&{ON}&drive=closeall@5", 12.5, {"focused": "", CLAUDE: None, B42: None}),
    "desk-on-app":      (DESK, f"desktop&{ON}&drive=focusapp@5", 12.5, {"focused": CLAUDE, CLAUDE: (OWN["cx"], OWN["w"], False, False), B42: None}),
    "desk-away":        (DESK, f"desktop&{ON}&drive=focus-mail@5", 12.5, {"focused": "mail", CLAUDE: (OWN["cx"], OWN["w"], False, False), B42: None}),
    "desk-press-again": (DESK, "desktop&script=needed@2,needed2@7,done2@12&drive=closebro@4.5", 9.5,
                         {"focused": B42, CLAUDE: (LEFT, HALF, True, False), B42: (RIGHT, HALF, False, True)}),
    # a browser window he already had, parked on a flank: beside for the errand, then back on its flank, open
    "desk-had-browser": (DESK, f"desktop&withbro&{ON}", 13.5, {"focused": CLAUDE, CLAUDE: (OWN["cx"], OWN["w"], False, False),
                                                              B42: (1440 - 120, 640, False, False)}),
    "desk-had-browser-open": (DESK, f"desktop&withbro&{ON}", 6.5, {"focused": B42, CLAUDE: (LEFT, HALF, True, False), B42: (RIGHT, HALF, False, True)}),
    "phone-open":       (PHONE, ON, 6.5, {"hash": f"#/m/{B42}/handoff/claude-signin", "bar": True}),
    "phone-return":     (PHONE, ON, 13.5, {"hash": f"#/m/{CLAUDE}", "bar": False}),
    "phone-cancel":     (PHONE, f"{ON}&drive=cancel@5", 8.0, {"hash": f"#/m/{CLAUDE}", "bar": False}),
}


def check(name: str, got: dict, want: dict) -> list[str]:
    bad = []
    wins = {w["tile"]: w for w in got.get("wins", [])}
    for k, v in want.items():
        if k in ("focused", "hash", "bar"):
            if got.get(k) != v:
                bad.append(f"{k}: {got.get(k)!r}, wanted {v!r}")
        elif v is None:
            if k in wins:
                bad.append(f"{k}: open, wanted closed")
        else:
            w = wins.get(k)
            if not w:
                bad.append(f"{k}: closed, wanted open")
                continue
            have = (w["cx"], w["w"], w["band"], w["pill"])
            if have != v:
                bad.append(f"{k}: (cx, w, band, pill) = {have}, wanted {v}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--shots", action="store_true", help="photograph each scenario too")
    ap.add_argument("only", nargs="*", help="scenario names (default: all)")
    a = ap.parse_args()
    shell = OUT / "shell"
    build(shell)
    hs = headless()
    failed = 0
    for name, (size, query, at, want) in SCENARIOS.items():
        if a.only and name not in a.only:
            continue
        read = f"{query},dump@{at}" if "drive=" in query else f"{query}&drive=dump@{at}"
        url = f"{(shell / 'index.html').as_uri()}?{read}#/m/{CLAUDE}"
        dom = run(hs, url, size, int((at + 0.4) * 1000))
        m = re.search(r'<pre id="hdump">(.*?)</pre>', dom, re.S)
        got = json.loads(htmlmod.unescape(m.group(1))) if m else {}
        bad = check(name, got, want) if m else ["no reading (the page did not get that far)"]
        failed += bool(bad)
        print(f"{'ok  ' if not bad else 'FAIL'} {name}" + "".join(f"\n       {b}" for b in bad))
        if a.shots:
            run(hs, f"{(shell / 'index.html').as_uri()}?{query}#/m/{CLAUDE}", size, int((at + 0.4) * 1000), OUT / f"{name}.png")
    print(f"\n{'all hold' if not failed else str(failed) + ' FAILED'}" + (f" — shots in {OUT.relative_to(REPO)}" if a.shots else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
