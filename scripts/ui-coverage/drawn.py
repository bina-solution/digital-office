#!/usr/bin/env python3
"""drawn.py — ONE rule of "this screen has said what it has to say", for everything that
photographs a screen or measures one: the live map (live-ui-map.py) and the simulation's map and
flow suites (digital-office/sim/ui-map.py, flow-qa.py).

    python3 scripts/ui-coverage/drawn.py --self-test

WHY THIS EXISTS. Each of those tools opened a screen, waited a fixed time and pressed the shutter.
A screen still loading was photographed as it stood and the picture was filed as the screen: on
2026-10-09 the look at the live «אפליקציות» tile shows six grey placeholder cards, before a change
and after it — the list took 5 to 13 seconds to arrive and the camera waited 4.5. The stack map had
met the same screen on 2026-09-28 (capture.py, `hydrate_frame`: "takes 20-40s on this host") and
answered by waiting longer, so a list that takes that long stayed nobody's bug for eleven days.
The owner, 2026-10-09: «אתה חייב לוודא שהצילומי מסך שלך באמת מספיקים לטעון את המידע שאמור להיות
מוצג ואם לוקח יותר מידי זמן אז לדווח באג».

THE RULE. A screen is DRAWN when, in the page and in every frame of it that is in sight:
  · the document has finished loading;
  · nothing in sight is a placeholder — a skeleton (`.sk`, `.skel`, `.skeleton`), a spinner, an
    element that says it is busy (`aria-busy="true"`), or a line that says «טוען…»;
  · and it has stopped growing: the same number of elements on two looks in a row.
It is ASKED, every POLL_MS, from the moment the screen is opened; no photograph is taken on a guess.
How long that took is the screen's time to drawn, and it is written beside the photograph.

TWO NUMBERS, AND THEY ARE DIFFERENT FINDINGS.
  BUDGET_MS  what a screen may take to open. Over it the screen is SLOW — a bug of its own, to be
             filed with the measured time — however good its picture is in the end.
  CAP_MS     when the camera stops waiting. A screen not drawn by then is photographed as it stands
             and the picture SAYS so: that is a screen that never finished, not a slow one.
NEVER DRAWN is a failure wherever it is seen. Where SLOW is one is each tool's to say, by where it
runs: on a running office the time is a person's wait, and the live map — and the flow suites, with
`--url` — are red for it; in the simulation it is this machine's load as much as the screen's own,
so there it is said beside the picture and the run stays green.

WHAT IT IS NOT. Not a wait for the network: a screen that holds a stream open, or asks again every
second, is never quiet on the wire and is drawn all the same — and a reader sees the screen, not the
wire. A tool that can watch the wire (the live map does) still may; this rule is what all of them
agree on before the shutter. Not a wait for an animation: the tools keep the time a drawer takes
to slide (`at_least_ms`) — that is how long a thing moves, not how long its data takes. And not an
eye inside a frame of ANOTHER origin (an app shown from its own host): the page cannot read it, so
the rule says nothing of what is in it — the live map names those panels for what they are.
"""
import sys
import time

# Hebrew in what this prints (its own words, and a screen's «טוען…»): python's stdout is the ANSI
# codepage on Windows (cp1255) and dies on it. Linux/macOS are already UTF-8 — a no-op there.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BUDGET_MS = 4000      # a screen that needs longer than this to show its information is a bug
CAP_MS = 25000        # the camera's patience: after it the screen is photographed as it stands
POLL_MS = 250

#: One look at the page and at every frame of it that is in sight (a frame that is not drawn —
#: another screen's, kept alive — is not this screen). -> {nodes, unready, loading, what}
LOOK_JS = r"""(() => {
  const PLACEHOLDER = '.sk, .skel, .skeleton, .spinner, [aria-busy="true"]';
  const SAYS = /^טוען(\s[^\n]{1,22})?(…|\.\.\.)$/;
  const out = { nodes: 0, unready: 0, loading: 0, what: [] };
  const note = (w) => { out.loading += 1; if (out.what.length < 4 && !out.what.includes(w)) out.what.push(w); };
  const look = (d) => {
    if (!d || !d.body || d.readyState !== 'complete') { out.unready += 1; return; }
    out.nodes += d.getElementsByTagName('*').length;
    for (const el of d.querySelectorAll(PLACEHOLDER)) {
      if (!el.getClientRects().length) continue;
      note(el.getAttribute('aria-busy') === 'true' ? el.tagName.toLowerCase() + '[aria-busy]' : '.' + el.classList[0]);
    }
    const walk = d.createTreeWalker(d.body, NodeFilter.SHOW_TEXT);
    for (let t = walk.nextNode(); t; t = walk.nextNode()) {
      if (t.nodeValue.length > 200) continue;      // (an inline script is ONE text node, and can be megabytes long)
      const s = t.nodeValue.trim();
      if (s.length < 32 && SAYS.test(s) && t.parentElement && t.parentElement.getClientRects().length) note('«' + s + '»');
    }
    for (const f of d.querySelectorAll('iframe')) {
      if (!f.getClientRects().length) continue;
      let inner = null;
      try { inner = f.contentDocument; } catch (e) { /* another origin: its own screen, not ours to read */ }
      if (!inner) continue;
      // A frame that was told where to go and still holds the blank page it was born with: its screen
      // has not ARRIVED (the server has not answered yet). That blank page calls itself complete.
      const src = f.getAttribute('src') || '';
      if (src && src !== 'about:blank' && inner.location.href === 'about:blank') { out.unready += 1; continue; }
      // …or still holds the page it had BEFORE it was sent on: a frame keeps its old document until
      // the new one answers, and the old screen is drawn, complete — and the wrong one (seen on the
      // running office, 2026-10-09: «ניהול נתונים» was slow to answer, and the apps screen that stood
      // in its frame was read as it). Its page has to be under the place the frame was sent to.
      if (src && /^https?:$/.test(inner.location.protocol)
          && !inner.location.pathname.startsWith(new URL(src, d.baseURI).pathname.replace(/[^/]*$/, ''))) {
        note('a frame that still holds the page it had before'); continue;
      }
      look(inner);
    }
  };
  look(document);
  return out;
})()"""


def wait(evaluate, sleep, since=None, at_least_ms=0, cap_ms=CAP_MS, clock=time.monotonic):
    """Ask the rule until the screen is drawn — or the cap. Engine-agnostic:

        evaluate(js) -> the value of a JS expression in the PAGE (Playwright's `page.evaluate`, the
                        live map's `Panel.js`); an error while the page navigates is "not yet"
        sleep(ms)       the engine's own wait

    `since`        the `clock()` reading when the screen was opened: the time to drawn counts from
                   it. Default: now — which is the form to use before a shutter, AFTER an action
                   was run on a screen already open (then only `drawn` is the question).
    `at_least_ms`  do not return before this much of `since` has passed (an animation's time). The
                   looks go on meanwhile, so the time to drawn is still the screen's own.

    -> {"drawn", "ms", "slow", "loading", "what"}: `ms` is when the screen FIRST stood drawn and
    then stayed so; with drawn False it is how long was waited, and `what` names what was in the way.
    """
    t0 = clock() if since is None else since
    now = lambda: int((clock() - t0) * 1000)                             # noqa: E731
    began = now()
    stood_at, nodes = None, None
    while True:
        try:
            got = evaluate(LOOK_JS) or {}
        except Exception:                                                # noqa: BLE001
            got = {}
        at = now()
        clear = bool(got) and not got.get("unready") and not got.get("loading")
        if not clear:
            stood_at, nodes = None, None
        elif nodes != got.get("nodes"):                                  # in sight, and still growing
            stood_at, nodes = at, got.get("nodes")
        elif at >= at_least_ms:
            return {"drawn": True, "ms": stood_at, "slow": stood_at > BUDGET_MS, "loading": 0, "what": []}
        if at - began >= cap_ms:
            what = got.get("what") or (["still growing"] if clear else ["the page had not finished loading"])
            return {"drawn": False, "ms": at, "slow": True, "loading": got.get("loading", 0), "what": what}
        sleep(POLL_MS)


def said(r):
    """One verdict in words, for a log line or a failed check."""
    if not r["drawn"]:
        return (f"NEVER DRAWN — after {r['ms'] / 1000:.1f}s still: " + ", ".join(r["what"])
                + (f" ({r['loading']} in sight)" if r["loading"] > 1 else ""))
    if r["slow"]:
        return f"SLOW — {r['ms'] / 1000:.1f}s to its information (a screen may take {BUDGET_MS / 1000:g}s)"
    return f"drawn in {r['ms'] / 1000:.1f}s"


def _self_test():
    """The loop against screens that are scripted: what each look answers, and when."""
    def run(looks, **kw):
        t, it, last = [0.0], iter(looks), [None]

        def evaluate(_js):
            last[0] = next(it, last[0])                                  # the last look goes on for ever
            if isinstance(last[0], Exception):
                raise last[0]
            return last[0]
        return wait(evaluate, lambda ms: t.__setitem__(0, t[0] + ms / 1000), clock=lambda: t[0], **kw)

    ok = {"nodes": 90, "unready": 0, "loading": 0, "what": []}
    sk = {"nodes": 60, "unready": 0, "loading": 6, "what": [".sk"]}
    cases = [
        ("a screen that is there at the first look is drawn at once",
         run([ok]), lambda r: r["drawn"] and r["ms"] == 0 and not r["slow"]),
        ("a skeleton for three seconds, then the list: drawn at three seconds, inside the budget",
         run([sk] * 12 + [ok]), lambda r: r["drawn"] and r["ms"] == 3000 and not r["slow"]),
        ("a skeleton for six seconds: drawn, and SLOW",
         run([sk] * 24 + [ok]), lambda r: r["drawn"] and r["ms"] == 6000 and r["slow"]),
        ("a skeleton that never goes: never drawn, and what was in the way is named",
         run([sk]), lambda r: not r["drawn"] and r["slow"] and r["what"] == [".sk"] and r["loading"] == 6 and r["ms"] >= CAP_MS),
        ("a list that keeps growing is not drawn until it stops",
         run([dict(ok, nodes=n) for n in (10, 40, 90, 90)]), lambda r: r["drawn"] and r["ms"] == 500),
        ("a list that never stops growing is never drawn, and that is what is said",
         run(dict(ok, nodes=n) for n in range(1, 400)), lambda r: not r["drawn"] and r["what"] == ["still growing"]),
        ("a page that is navigating (the look throws, the document is not complete) is not drawn yet",
         run([RuntimeError("navigating"), dict(ok, unready=1), ok]), lambda r: r["drawn"] and r["ms"] == 500),
        ("a page that never finishes loading is never drawn, and that is what is said",
         run([dict(ok, unready=1)]), lambda r: not r["drawn"] and r["what"] == ["the page had not finished loading"]),
        ("the animation's time is kept, and the time to drawn is still the screen's own",
         run([ok], at_least_ms=2600), lambda r: r["drawn"] and r["ms"] == 0),
        ("a screen that falls back into loading during the animation's time is timed from when it came back",
         run([ok, ok, sk, sk, ok], at_least_ms=2000), lambda r: r["drawn"] and r["ms"] == 1000),
        ("the clock starts when the screen was opened, not when the looking began",
         run([sk, sk, ok], since=-2.0), lambda r: r["drawn"] and r["ms"] == 2500),
        ("…and the camera's patience counts from when the looking began",
         run([sk], since=-20.0), lambda r: not r["drawn"] and r["ms"] >= 20000 + CAP_MS),
    ]
    words = [
        ("a drawn screen is said with its time", said({"drawn": True, "ms": 420, "slow": False, "loading": 0, "what": []}),
         lambda s: s == "drawn in 0.4s"),
        ("a slow screen is said with its time and the budget",
         said({"drawn": True, "ms": 12900, "slow": True, "loading": 0, "what": []}),
         lambda s: s.startswith("SLOW — 12.9s") and "4s" in s),
        ("a screen that never finished is said with what was in the way",
         said({"drawn": False, "ms": 25000, "slow": True, "loading": 6, "what": [".sk"]}),
         lambda s: s.startswith("NEVER DRAWN") and ".sk" in s and "6 in sight" in s),
    ]
    bad = 0
    for name, got, holds in cases + words:
        good = bool(holds(got))
        bad += not good
        print(("  PASS  " if good else "  FAIL  ") + name + ("" if good else f" — {got}"))
    print(f"drawn: {len(cases) + len(words) - bad}/{len(cases) + len(words)} hold")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    print(__doc__)
