"""test_modal_over_desktop — every dialog of the console opens OVER its desktop (DGO-1634).

On Exampleu, 2026-11-09, «חיבור חשבון חדש» in an app's accounts menu did nothing on a computer and worked on a phone.
The wizard was there: `.modal-ov` (the shared modal block, z-index 50) is appended to <body>, and the desktop
(desktop.css `.dk`, fixed over the whole page) sits at 100, so every dialog opened under it. The phone has no
desktop. DGO-1434 had lifted two dialogs by name; the next dialog was missed, as a list by name always misses one.

So the order is read from the files the browser reads, not restated: the z-index the cascade gives `.modal-ov` (the
last plain `.modal-ov` rule of style.css) must be above `.dk`'s, every rule that names a kind of `.modal-ov` with a
z-index of its own must be too, and every dialog the console's scripts make must go to <body> (inside `.dk` a z-index
counts only among the desktop's own layers).

Run: python3 -m pytest platform-base/console/test_modal_over_desktop.py   (or python3 … directly)
"""
import pathlib
import re

STATIC = pathlib.Path(__file__).resolve().parent / "static"


def rules(css):
    """(selector, body) of every rule, comments removed; an @media block's rules are read like the others."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(s.strip(), b) for s, b in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def z_of(body):
    m = re.search(r"(?:^|;)\s*z-index\s*:\s*(-?\d+)", body)
    return int(m.group(1)) if m else None


def desktop_z():
    zs = [z_of(b) for s, b in rules((STATIC / "desktop.css").read_text(encoding="utf-8")) if s == ".dk"]
    zs = [z for z in zs if z is not None]
    assert zs, "desktop.css has no `.dk { z-index }` rule — the desktop's layer moved; read it from where it is now"
    return zs[-1]


def test_a_dialog_opens_over_the_desktop():
    plain = [z_of(b) for s, b in rules((STATIC / "style.css").read_text(encoding="utf-8")) if s == ".modal-ov"]
    plain = [z for z in plain if z is not None]
    assert plain, "style.css gives `.modal-ov` no z-index"
    assert plain[-1] > desktop_z(), (f"`.modal-ov` is at z-index {plain[-1]}, the desktop at {desktop_z()}: "
                                     "every dialog opens under the desktop on a computer")


def test_no_kind_of_dialog_is_put_back_under_it():
    low = [(s, z_of(b)) for s, b in rules((STATIC / "style.css").read_text(encoding="utf-8"))
           if ".modal-ov" in s and s != ".modal-ov" and z_of(b) is not None and z_of(b) <= desktop_z()]
    assert not low, f"under the desktop: {low}"


def test_every_dialog_goes_to_the_page_not_into_the_desktop():
    made = 0
    for js in sorted(STATIC.glob("*.js")):
        src = js.read_text(encoding="utf-8")
        for m in re.finditer(r"\b(\w+)\s*=\s*el\(\s*\"div\",\s*\"modal-ov[^\"]*\"\)"
                             r"|(\w+)\.className\s*=\s*\"modal-ov|(\w+)\.classList\.add\(\s*\"modal-ov\"", src):
            made += 1
            var = m.group(1) or m.group(2) or m.group(3)
            rest = src[m.end():m.end() + 6000]           # a dialog's body is written before it is put anywhere
            put = re.search(r"([\w.]+)\.appendChild\(\s*" + re.escape(var) + r"\s*\)", rest)
            assert put and put.group(1) == "document.body", (
                f"{js.name}: the dialog `{var}` is put into {put.group(1) if put else 'nothing that can be read'}, "
                "not <body> — inside the desktop its z-index counts only among the desktop's own layers")
    # two since DGO-1624: the signed-out card (app.js) and the hand-off's (handoffs.js); the health panel's and the
    # connect wizard's went with the shell's account bar. Fewer means the scan lost where dialogs are made.
    assert made >= 2, f"read only {made} dialog(s) in static/*.js — the scan no longer finds where they are made"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS ", name)
