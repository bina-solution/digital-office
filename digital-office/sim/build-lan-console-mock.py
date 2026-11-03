#!/usr/bin/env python3
"""Write ci-artifacts/lan-console-mock/index.html: the network app's «local network access» card (DGO-1125).

The owner, 2026-11-02: the MacBook's console on its own LAN address, from his phone, managed from the
network app, later the Dell's and the HP's the same way. This is the interactive mock of the card
(AGENTS.md rule 11): the switch, the address and its QR, the auto-off, the fence it states, who is in.

The palette is theme-tokens.css's block and the QR is the office's vendored generator
(apps/dgo-extend/static/vendor/qrcode/qrcode.min.js, MIT), both inlined.

    python3 digital-office/sim/build-lan-console-mock.py        # ?on=1 · ?theme=dark
"""
import pathlib
import subprocess

repo = pathlib.Path(__file__).resolve().parents[2]
here = pathlib.Path(__file__).resolve().parent

css = (repo / "platform-base/bina-ui/theme-tokens.css").read_text(encoding="utf-8")
tokens = css[css.index("/* @bina-theme-tokens:start */"):css.index("/* @bina-theme-tokens:end */")]
qr_path = "apps/dgo-extend/static/vendor/qrcode/qrcode.min.js"
try:
    qr = (repo / qr_path).read_text(encoding="utf-8")
except OSError:                                    # a checkout behind dgo-stable: read it from there
    qr = subprocess.run(["git", "-C", str(repo), "show", f"origin/dgo-stable:{qr_path}"],
                        capture_output=True, text=True, check=True).stdout
html = (here / "lan-console-mock.src.html").read_text(encoding="utf-8")
html = html.replace("/*TOKENS*/", tokens).replace("/*QRCODE*/", qr)
out = repo / "ci-artifacts/lan-console-mock/index.html"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(html, encoding="utf-8")
print(f"{out} ({len(html)} bytes)")
