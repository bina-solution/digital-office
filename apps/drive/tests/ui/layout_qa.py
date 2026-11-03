"""«קבצים» at every size, in every state — measured, not eyeballed.

    python apps/drive/tests/ui/layout_qa.py [--url http://127.0.0.1:8971/] [--shots DIR] [--only 390x844,1440x900]

Runs the app (by default against tests/ui/dev_server.py and its mock) at phone, tablet, laptop and
desktop sizes, and at the console's smallest desktop window (380×260). In each size it walks the
states a person reaches — home, a folder as a list and as a grid, photos, music with the player
running, the viewer (image, PDF, audio), a menu, a selection, the upload queue, the details pane,
search, the drawer — and asks the page, in each, what a glitch is made of:

  overflow   the page scrolls sideways
  offscreen  a control of the frame (top bar, side, tabs, player, add button, queue, menu, viewer
             bar) is drawn partly outside the window
  overlap    two of those controls, or two of the floating blocks (add button, player, queue, tabs,
             notice), cover each other
  clipped    a label is cut without an ellipsis
  target     a control is smaller than a finger on a touch size (32px)
  error      the page logged an error

Exit 1 if any check fails; screenshots of every state go to --shots (default: a temp folder).
"""
import argparse
import json
import os
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright

SIZES = [(320, 568), (360, 640), (375, 667), (390, 844), (412, 915), (430, 932), (568, 320), (667, 375), (844, 390),
         (600, 960), (768, 1024), (820, 1180), (1024, 768), (1180, 820), (1280, 720), (1366, 768), (1440, 900),
         (1920, 1080), (2560, 1440), (380, 260), (480, 320), (520, 400), (800, 600),
         (628, 567), (560, 580),    # the console's own window, and one just above the short class
         (900, 260), (440, 430), (560, 440),   # widgets: a strip, a square — and the first box that is the app again
         (412, 760), (1280, 900)]   # the round-2 bar: the owner's phone (Samsung Internet, forced dark) and the desk

PROBE = r"""() => {
  const out = [], vw = innerWidth, vh = innerHeight, fx = document.querySelector('.fx');
  const narrow = fx && fx.dataset.w === 'n', drawer = !!document.querySelector('.fx-side.open');
  const desc = (el) => (el.getAttribute('title') || el.getAttribute('aria-label') || el.textContent || el.className || el.tagName).trim().slice(0, 40);
  /* what of an element is really on screen: its box cut by every ancestor that clips (a scroll box,
     overflow:hidden) — a row scrolled out of its list is not "overlapping" what lies beyond the list */
  const box = (el) => { let r = el.getBoundingClientRect(), x0 = r.left, y0 = r.top, x1 = r.right, y1 = r.bottom;
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.overflowX !== 'visible' || s.overflowY !== 'visible') { const q = a.getBoundingClientRect();
        x0 = Math.max(x0, q.left); y0 = Math.max(y0, q.top); x1 = Math.min(x1, q.right); y1 = Math.min(y1, q.bottom); } }
    return { left: x0, top: y0, right: x1, bottom: y1, width: Math.max(0, x1 - x0), height: Math.max(0, y1 - y0) }; };
  const vis = (el) => { const r = box(el), s = getComputedStyle(el);
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.05; };
  if (document.documentElement.scrollWidth > vw + 1) out.push(['overflow', 'page', document.documentElement.scrollWidth - vw]);
  const content = document.querySelector('.fx-content');
  if (content && content.scrollWidth > content.clientWidth + 1) out.push(['overflow', 'content', content.scrollWidth - content.clientWidth]);
  const sel = '.fx-top button,.fx-top a,.fx-top input,.fx-side a,.fx-side button,.fx-tabs a,.fx-tabs button,.fx-player button,.fx-player input,' +
              '.up button,.menu .mi,.vw-top button,.vw-nav,.selbar button,.dlg button,' +
              '.rc-top button,.rc-dock button,.rc-sheet button,.rc-pctl button,.rc-acts button,.rc-left button,.rc-play,' +
              '.wg button,.wg-r,.wg [role=slider]';
  const viewer = !!document.querySelector('.vw');
  const ctl = [...document.querySelectorAll(sel)].filter(vis).filter((el) => {
    if (viewer && !el.closest('.vw')) return false;                       // under the viewer nothing else is reachable
    if (el.closest('.fx-side') && narrow && !drawer) return false;        // the closed drawer is meant to be out of sight
    if (drawer && narrow && !el.closest('.fx-side')) return false;        // …and an open one covers everything else
    if (document.querySelector('.menu') && !el.closest('.menu') && !el.closest('.vw')) return false;
    return true;
  });
  for (const el of ctl) {
    const r = el.getBoundingClientRect();
    if (r.left < -1 || r.right > vw + 1 || r.top < -1 || r.bottom > vh + 1) {
      const scroller = el.closest('.side-scroll,.up-l,.menu,.dlg-b,.wg-rows,.rc-list');
      if (!scroller) out.push(['offscreen', desc(el), [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)]]);
    }
    if (matchMedia('(pointer: coarse)').matches && (r.width < 32 || r.height < 32) && !el.matches('input[type=range]'))
      out.push(['target', desc(el), [Math.round(r.width), Math.round(r.height)]]);
  }
  const hit = (a, b) => { const x = Math.min(a.right, b.right) - Math.max(a.left, b.left), y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top); return x > 2 && y > 2 ? x * y : 0; };
  for (let i = 0; i < ctl.length; i++) for (let j = i + 1; j < ctl.length; j++) {
    const a = ctl[i], b = ctl[j];
    if (a.contains(b) || b.contains(a)) continue;
    if (hit(box(a), box(b))) out.push(['overlap', desc(a), desc(b)]);
  }
  const blocks = (drawer && narrow ? [] : ['.fx-player', '.up', '.fx-tabs', '.fx-top', '#bina-tell', '.rc-top', '.rc-dock', '.rc-sheet',
                  '.wg-h', '.wg-now', '.wgf-top', '.wgf-cap']).map((s) => document.querySelector(s)).filter((e) => e && vis(e));
  for (let i = 0; i < blocks.length; i++) for (let j = i + 1; j < blocks.length; j++)
    if (hit(box(blocks[i]), box(blocks[j]))) out.push(['overlap', blocks[i].className || blocks[i].id, blocks[j].className || blocks[j].id]);
  /* a viewer that shows nothing: whatever the stage holds must fill most of it, or be its message */
  const pane = document.querySelector('.vw-pane');
  if (pane && pane.firstElementChild && !pane.querySelector('.vw-msg,.vw-spin,.audio-stage')) {
    const r = pane.firstElementChild.getBoundingClientRect(), s = pane.getBoundingClientRect();
    if (r.height < s.height * 0.6 || r.width < s.width * 0.6) out.push(['blank', 'viewer content', [Math.round(r.width), Math.round(r.height), Math.round(s.width), Math.round(s.height)]]);
  }
  /* the navigation keeps its words whole at every size: a tab or a place is never cut (a folder's own
     long name in the side list may fold to an ellipsis — the navigation's words may not) */
  for (const el of document.querySelectorAll('.tab span:last-child, .nav-i.place .lbl')) {
    if (!vis(el) || (el.closest('.fx-side') && narrow && !drawer)) continue;
    if (el.scrollWidth > el.clientWidth) out.push(['clipped', 'navigation label', el.textContent]);
  }
  /* a picture that failed gives way to its glyph — a broken image is never left on screen */
  for (const i of document.querySelectorAll('img')) {
    if (!vis(i) || !i.getAttribute('src') || !i.complete || i.naturalWidth > 0) continue;
    const host = i.closest('[data-id]'); out.push(['broken', 'picture', host ? host.dataset.id : i.parentElement.className]); break;
  }
  /* the viewer's title is readable on its own ground, light or dark (the dark lightbox once turned light grey
     with dark letters on the dark theme, because its colours were steps that turn with the theme) */
  const rgb = (c) => { const m = String(c).match(/[\d.]+/g); if (!m) return null; const k = String(c).startsWith('color(') ? 255 : 1; return m.slice(0, 3).map((v) => +v * k); };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const vwEl = document.querySelector('.vw'), vt = document.querySelector('.vw-title b');
  if (vwEl && vt && vis(vt)) {
    const a = rgb(getComputedStyle(vt).color), g = rgb(getComputedStyle(vwEl).backgroundColor);
    if (a && g) { const x = lum(a), y = lum(g), cr = (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); if (cr < 4.5) out.push(['contrast', 'viewer title', cr.toFixed(2)]); }
    /* …and a photo's lightbox is dark on both grounds */
    if (vwEl.classList.contains('dark') && g && lum(g) > 0.06) out.push(['theme', 'lightbox is not dark', lum(g).toFixed(2)]);
  }
  /* a canvas draws text in its own direction: a PDF page drawn right to left has colliding letters */
  for (const c of document.querySelectorAll('.page canvas')) if (getComputedStyle(c).direction !== 'ltr') { out.push(['bidi', 'pdf canvas is right-to-left']); break; }
  /* a player is a stage, not a document: it fits its window without scrolling */
  const stage = document.querySelector('.audio-stage'), apane = stage && stage.closest('.vw-pane');
  if (apane && apane.scrollHeight > apane.clientHeight + 1) out.push(['overflow', 'audio stage', apane.scrollHeight - apane.clientHeight]);
  /* a window too small for the app is a widget: one thing, whole — none of the app's frame squeezed into
     it, and nothing in it larger than its box (only a list may scroll, inside itself) */
  const small = innerHeight < 300 || (innerWidth < 560 && innerHeight < 440), rc = document.querySelector('.rc');
  if (fx && small !== fx.hasAttribute('data-tiny')) out.push(['widget', small ? 'a small window shows the whole app' : 'a large window shows the widget']);
  if (rc && small !== rc.hasAttribute('data-tiny')) out.push(['widget', small ? 'a small window shows the whole recorder' : 'a large window shows the recorder widget']);
  if (fx && fx.hasAttribute('data-tiny') && document.querySelector('.fx-side,.fx-top,.fx-tabs,.fx-player,.fx-content'))
    out.push(['widget', 'the app frame is drawn inside the widget']);
  for (const el of document.querySelectorAll('.wg,.wgp,.wg-list,.wgf')) {
    if (vis(el) && el.scrollHeight > el.clientHeight + 1) out.push(['overflow', el.className, el.scrollHeight - el.clientHeight]);
    if (vis(el) && el.scrollWidth > el.clientWidth + 1) out.push(['overflow', el.className + ' (sideways)', el.scrollWidth - el.clientWidth]);
  }
  for (const el of document.querySelectorAll('.rc[data-tiny] .rc-list')) if (vis(el) && el.scrollHeight > el.clientHeight + 1) out.push(['overflow', 'recorder list in a widget', el.scrollHeight - el.clientHeight]);
  /* the current folder's name must be readable in full (the path may fold, the title may not) */
  const cur = document.querySelector('.crumb[aria-current="page"]');
  if (cur && vis(cur) && cur.scrollWidth > cur.clientWidth && cur.textContent.length <= 18) out.push(['clipped', 'current folder title', cur.textContent]);
  const labels = '.nav-i .lbl,.crumb,.tab span,.vw-title b,.pl-now b,.selbar b,.up-h b,.chip,.btn,.mi .lbl,.side-brand b,.sect h2,.fcard b,.tr .t b,.month,' +
                 '.rc-title b,.rc-hint,.rc-sheet-h b,.rc-clock,.wg-place b,.wgf-cap b,.wgp .ttl b,.wg-now-open b,.wg-r .meta';
  for (const el of document.querySelectorAll(labels)) {
    if (!vis(el) || (el.closest('.fx-side') && narrow && !drawer)) continue;
    if (el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).textOverflow !== 'ellipsis' && !el.querySelector('.stem'))
      out.push(['clipped', desc(el), el.scrollWidth - el.clientWidth]);
  }
  /* a size inside Hebrew text is an isolated left-to-right token — otherwise the line reads "MB 41.4" */
  const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = tw.nextNode());) {
    const t = n.nodeValue, m = /\d[\d.,]*\s?(?:B|KB|MB|GB|TB)\b/.exec(t), el = n.parentElement;
    if (!m || !el || !vis(el) || el.closest('.textdoc, .code, .doc-pane, .vw-pane iframe')) continue;
    if (getComputedStyle(el).direction === 'ltr' || t.slice(0, m.index).includes(String.fromCharCode(0x2066))) continue;
    out.push(['bidi', 'size not isolated', t.trim().slice(0, 40)]); break;
  }
  /* one is said in words: «קובץ אחד», never «1 קבצים» */
  const one = /(^|[^\d.,])1 (קבצים|עמודים|פריטים|נבחרו|העלאות|תיקיות)/;
  for (const el of document.querySelectorAll('.fx *, .vw *, .rc *')) {
    if (el.children.length || !vis(el)) continue;
    if (one.test(el.textContent)) { out.push(['copy', 'one in the plural', el.textContent.trim().slice(0, 40)]); break; }
  }
  /* the browser's own link underline is not part of the design (a document's own links may keep theirs) */
  for (const el of document.querySelectorAll('a, a *')) {
    if (!vis(el) || el.closest('.textdoc, .doc-pane, iframe')) continue;
    if (getComputedStyle(el).textDecorationLine.includes('underline')) { out.push(['underlined', desc(el.closest('a'))]); break; }
  }
  return out;
}"""

STATES = [
    ("home", "F.go({view:'home'})"),
    ("files-list", "F.set({layout:'list'}); F.go({view:'folder', id:''})"),
    ("folder-grid", "F.set({layout:'grid'}); F.go({view:'folder', id: F.state.folders.find(f=>f.name==='תמונות מהשטח').id})"),
    ("photos", "F.go({view:'photos'})"),
    ("music-player", "F.go({view:'music'})", "F.player.play(F.state.list.files, 0)"),
    ("menu", "F.set({layout:'list'}); F.go({view:'folder', id:''})", "document.querySelector('.lr .rowact').click()"),
    ("selection", "F.go({view:'folder', id:''})", "F.set({sel: F.state.list.files.slice(0,2).map(f=>f.id).concat(F.state.list.folders.slice(0,1).map(f=>f.id))})"),
    ("details", "F.go({view:'folder', id: F.state.folders.find(f=>f.name==='מסמכים').id})", "F.set({sel:[F.state.list.files[0].id], details:true})"),
    ("upload", "F.go({view:'home'})", "F.upload.enqueue([new File([new Uint8Array(3e6)], 'צילום מסך 2026-10-28 בשעה 13.40.12 עם שם ארוך.png', {type:'image/png'}), new File([new Uint8Array(9e5)], 'report.pdf')])"),
    ("search", "F.go({view:'search', q:'הקלטה'})"),
    ("viewer-image", "F.go({view:'photos'})", "F.viewer.open(F.state.list.files.filter(f=>f.mime.startsWith('image')), 0)"),
    ("viewer-pdf", "F.go({view:'folder', id: F.state.folders.find(f=>f.name==='חשבוניות 2026').id})", "F.viewer.open(F.state.list.files, 0)"),
    ("viewer-audio", "F.go({view:'folder', id: F.state.folders.find(f=>f.name==='הקלטות').id})", "F.viewer.open(F.state.list.files, 0)"),
    ("trash", "F.go({view:'trash'})"),
    ("new-version", "F.go({view:'home'})", "F.set({newBuild:true})"),
]
NARROW_ONLY = [("drawer", "F.go({view:'home'})", "F.set({drawer:true})")]

# a window too small for the app (under 300 tall, or under 560×440) is a widget: these are its faces
WIDGET_RESET = "F.set({ wgList: false, wgAs: {} });"
WIDGET_STATES = [
    ("w-home", "F.go({view:'home'})"),
    ("w-files", "F.go({view:'folder', id:''})"),
    ("w-docs", "F.go({view:'folder', id: F.state.folders.find(f=>f.name==='מסמכים').id})"),
    ("w-photo-folder", "F.go({view:'folder', id: F.state.folders.find(f=>f.name==='תמונות מהשטח').id})"),
    ("w-photos", "F.go({view:'photos'})"),
    ("w-photos-step", "F.go({view:'photos'})", "document.querySelector('.wgf-nav.next').click()"),
    ("w-photos-as-list", "F.go({view:'photos'})", "F.set({ wgAs: { 'photos:': 'list' } })"),
    ("w-videos", "F.go({view:'videos'})"),
    ("w-music", "F.go({view:'music'})"),
    ("w-player", "F.go({view:'music'})", "F.player.play(F.state.list.files, 0)"),
    ("w-player-folded", "F.go({view:'music'})", "F.player.play(F.state.list.files, 0); F.set({ wgList: true })"),
    ("w-menu", "F.go({view:'folder', id:''})",
     "document.querySelector('.wg-r:not(:has(.folder))').dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true, clientX: 120, clientY: 120}))"),
    ("w-switch", "F.go({view:'home'})", "document.querySelector('.wg-place').click()"),
    ("w-upload", "F.go({view:'home'})", "F.upload.enqueue([new File([new Uint8Array(3e6)], 'צילום מסך 2026-10-28 בשעה 13.40.12 עם שם ארוך.png', {type:'image/png'}), new File([new Uint8Array(9e5)], 'report.pdf')])"),
    ("w-viewer-image", "F.go({view:'photos'})", "F.viewer.open(F.state.list.files.filter(f=>f.mime.startsWith('image')), 0)"),
    ("w-viewer-pdf", "F.go({view:'folder', id: F.state.folders.find(f=>f.name==='חשבוניות 2026').id})", "F.viewer.open(F.state.list.files, 0)"),
    ("w-viewer-audio", "F.go({view:'folder', id: F.state.folders.find(f=>f.name==='הקלטות').id})", "F.viewer.open(F.state.list.files, 0)"),
    ("w-trash", "F.go({view:'trash'})"),
    ("w-search", "F.go({view:'search', q:'הקלטה'})"),
    ("w-starred-empty", "F.go({view:'starred'})", "F.set({ list: { ...F.state.list, files: [], folders: [] } })"),
]
REC_WIDGET_STATES = [("rec-face", "F.recorder.load()", "F.player.play(F.state.recList.files, 0); F.set({ recFace: true })")]


def is_widget(w, h):
    return h < 300 or (w < 560 and h < 440)

# «הקלטות» — the same page under /rec (--surface recorder); a fake microphone answers getUserMedia
REC_RESET = "F.set({ recOpen: null, recSaving: {}, recLeft: [], newBuild: false }); if (F.state.rec.phase !== 'idle') { F.recorder.eng.rec = null; F.set({ rec: { phase: 'idle' } }); }"
REC_STATES = [
    ("rec-list", "F.recorder.load()"),
    ("rec-open", "F.recorder.load()", "F.set({ recOpen: F.state.recList.files[0].id })"),
    ("rec-empty", "F.set({ recList: { loading: false, files: [], error: '', folder: null } })"),
    ("rec-recording", "F.recorder.load()", "F.recorder.start()"),
    ("rec-paused", "F.recorder.load()", "F.recorder.start().then(() => setTimeout(F.recorder.pause, 300))"),
    ("rec-denied", "F.recorder.load()", "F.set({ rec: { phase: 'denied' } })"),
    ("rec-saving", "F.recorder.load()", "F.set({ uploads: [{ key: 9001, name: 'הקלטה 28.10.2026 16.42.webm', size: 2e6, sent: 7e5, state: 'sending', dest: {} }],"
                                         " recSaving: { tq: { key: 9001, take: { name: 'הקלטה 28.10.2026 16.42.webm' } } } })"),
    ("rec-newver", "F.recorder.load()", "F.set({ newBuild: true })"),
    ("rec-left", "F.recorder.load()", "F.set({ recLeft: [{ id: 'tl', name: 'הקלטה 27.10.2026 18.20.webm', duration: 754, at: Date.now() - 864e5, mime: 'audio/webm' }] })"),
]


def run(url, shots, only, scheme="light", surface="files", forced=False):
    os.makedirs(shots, exist_ok=True)
    report, fails = [], 0
    with sync_playwright() as p:
        # forced dark = the owner's Samsung Internet, emulated as the UI map does: Chrome's WebContentsForceDark
        b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
                              + (["--enable-features=WebContentsForceDark"] if forced else []))
        for (w, h) in SIZES:
            if only and f"{w}x{h}" not in only:
                continue
            touch = w < 1024 and max(w, h) <= 1366
            ctx = b.new_context(viewport={"width": w, "height": h}, locale="he-IL", has_touch=touch, is_mobile=touch and w < 760,
                                device_scale_factor=2 if touch else 1, color_scheme=scheme)
            ctx.grant_permissions(["microphone"])
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)[:200]))
            pg.on("console", lambda m: m.type == "error" and errs.append(m.text[:200]))
            rec = surface == "recorder"
            pg.goto(url + ("rec/" if rec else ""), wait_until="networkidle")
            pg.wait_for_function("window.F && F.state && " + ("F.state.recList && !F.state.recList.loading" if rec else "F.state.folders.length > 0"), timeout=15000)
            small = is_widget(w, h)
            states = (REC_STATES + (REC_WIDGET_STATES if small else [])) if rec else WIDGET_STATES if small else STATES + (NARROW_ONLY if w < 760 else [])
            for st in states:
                name, setup = st[0], st[1]
                pg.evaluate("() => { F.set({menu:null, sel:[], details:false, drawer:false, dialog:null, newBuild:false}); F.viewer.close(); F.player.close(); "
                            + (REC_RESET + " F.set({ recFace: false });" if rec else WIDGET_RESET) + (" F.set({ uploads: [] });" if small else "") + " }")
                pg.evaluate("() => { " + setup + " }")
                if rec:
                    pg.wait_for_function("() => !F.state.recList.loading", timeout=15000)
                else:
                    pg.wait_for_function("(() => { const r = F.state.route, l = F.state.list;"
                                         " return l.key === [r.view, r.id || '', r.q || ''].join('\\u241f') && !l.loading; })()",
                                         timeout=15000)
                pg.wait_for_timeout(250)
                if len(st) > 2:
                    pg.evaluate("() => { " + st[2] + " }")
                    pg.wait_for_timeout(900 if name.startswith("viewer") else 350)
                # the pictures in view have arrived (or failed) before anything is judged or photographed.
                # An <img> with no src yet counts as "complete", and the mock sets src only once it has
                # drawn the bytes — so a picture in view must have a src AND be complete. One that never
                # arrives is reported, not waited for longer.
                drawn = ("[...document.images].filter((i) => { const r = i.getBoundingClientRect();"
                         " return r.width > 0 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth; })"
                         ".filter((i) => !(i.getAttribute('src') && i.complete)).length")
                try:
                    pg.wait_for_function(drawn + " === 0", timeout=8000)
                    late = 0
                except Exception:
                    late = pg.evaluate(drawn)
                found = pg.evaluate(PROBE)
                if late:
                    found.append(["never drawn", f"{late} picture(s) in view after 8 s"])
                tag = f"{w}x{h}-{name}"
                pg.screenshot(path=os.path.join(shots, tag + ".png"))
                if found:
                    fails += len(found)
                report.append({"state": tag, "issues": found})
            if errs:
                fails += len(errs)
                report.append({"state": f"{w}x{h}-console", "issues": [["error", e] for e in errs]})
            ctx.close()
        b.close()
    bad = [r for r in report if r["issues"]]
    print(json.dumps(bad, ensure_ascii=False, indent=1))
    print(f"\n{len(report)} states, {len(bad)} with issues, {fails} issues — screenshots in {shots}")
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8971/")
    ap.add_argument("--shots", default=os.path.join(tempfile.gettempdir(), "files-layout-qa"))
    ap.add_argument("--only", default="")
    ap.add_argument("--dark", action="store_true", help="the dark ground (prefers-color-scheme: dark)")
    ap.add_argument("--forced-dark", action="store_true", help="the owner's phone: Chrome's forced dark on the dark ground")
    ap.add_argument("--surface", default="files", choices=["files", "recorder"], help="which app of the page: «קבצים» or «הקלטות» (/rec)")
    a = ap.parse_args()
    t0 = time.time()
    code = run(a.url, a.shots, set(filter(None, a.only.split(","))), "dark" if (a.dark or a.forced_dark) else "light", a.surface, a.forced_dark)
    print(f"({time.time() - t0:.0f}s)")
    sys.exit(code)
