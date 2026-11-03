#!/usr/bin/env python3
"""pinned-credential-lint — gate G87: no committed n8n workflow pins a credential its trigger captured.

    python3 scripts/refactor/pinned-credential-lint.py              # exit 1 on a finding
    python3 scripts/refactor/pinned-credential-lint.py --self-test
    python3 scripts/refactor/pinned-credential-lint.py --files      # list what it reads
    python3 scripts/refactor/pinned-credential-lint.py --fix [file…]   # strip what it finds

WHY THIS EXISTS (DGO-980). A webhook trigger's pinned test data (`pinData`) is the request it
captured, headers included. Three INDOX workflows exported from the hacohen office's n8n
(`apps/indox/app/incoming_documents/context-collection/n8n-workflows/`) kept the caller's
`authorization: Basic …` header there: a working webhook password, in the private repo, and in the
public one, bina-solution/digital-office, from 2026-10-19 until the export's second reader found it
on 2026-10-22 (DGO-975). Nothing read pinData for secrets, because nothing thought of test data as a
place a password lives. n8n since 1.x writes `{"__redacted": true, …}` in its place, which is why
the INDOX blueprints exported later carry no secret; the older exports did, and an export from an
older n8n, or a hand-pinned item, still can.

WHAT IT LOOKS FOR. Inside a workflow's `pinData` only: any object under a key named `headers` that
holds a credential header — authorization, proxy-authorization, cookie, set-cookie, x-api-key,
x-n8n-api-key, x-auth-token, and the platform's own x-authentik-jwt — whose value is a non-empty
string, or a list holding one. n8n's own redaction object is not a credential, nor is an empty value.
A blueprint's pinData line that is not JSON is a finding too: it cannot be judged. A node's
parameters are not pinned data and are not read here: a header a workflow SENDS is an expression or
a credential reference, and G55/G62 judge those. Not read either: a secret pinned outside `headers`
(a body's password, a query's token) — none is in the tree (measured 2026-10-22), and a rule for it
would be a guess at field names. It never prints a value: the line, the node and the header's name.

SCOPE. Every tracked `*.json` that is an n8n workflow (an object with a `nodes` list, or a list of
them) and every `*.workflow.ts` blueprint's `/*__n8n__*/ pinData:` line — legacy/ included: a
committed credential is published whatever directory it sits in. A scan that finds no workflow at
all FAILS: green and blind look alike.

--fix strips the credential headers in place, the rest of the file unchanged: a JSON file loses the
header's line (and the comma before it when it was the last one), a blueprint's pinData line is
written again in its own compact form. Each result is checked against the parsed file with the headers
removed; one that does not match is written whole by `json.dumps`, in the file's own form when it was
one line, or left for a hand (a blueprint whose pinData is not JSON or does not round-trip). Line
endings and a BOM are kept, and a file is replaced only once its new bytes exist, so a value UTF-8
cannot hold never leaves it empty. `bbox n8n pull` and `pull-app` strip the same headers when they
export (apps/n8n/hooks), so a new export cannot add one; this gate is what keeps the rest out.
"""
from __future__ import annotations

import argparse
import codecs
import copy
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]

#: The headers that carry a credential. The same list is in apps/n8n/hooks/pull and pull-app.
#: `x-authentik-jwt` is the platform's own: forward-auth signs every request it passes with it.
CREDENTIAL = ("authorization", "proxy-authorization", "cookie", "set-cookie",
              "x-api-key", "x-n8n-api-key", "x-auth-token", "x-authentik-jwt")
NOT_JSON = "(pinData that is not JSON cannot be judged)"
PIN_TS = re.compile(r"^(\s*/\*__n8n__\*/\s*pinData:\s*)(.*?)(,?\s*)$")
SAYS = ("a credential the trigger captured is pinned in the workflow — strip it with "
        "`python3 scripts/refactor/pinned-credential-lint.py --fix`, and rotate it where it is used")


def is_credential(value) -> bool:
    """A value that holds a secret: a non-empty string, or a list holding one. n8n's own redaction
    object (`{"__redacted": true, …}`) and an empty value hold none."""
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, list):
        return any(is_credential(v) for v in value)
    return False


def pinned_headers(pin):
    """(node, header name, the headers object) for every credential header in pinData."""
    out = []

    def walk(node, o):
        if isinstance(o, list):
            for x in o:
                walk(node, x)
        elif isinstance(o, dict):
            for k, v in o.items():
                if k.lower() == "headers" and isinstance(v, dict):
                    out.extend((node, h, v) for h in list(v) if h.lower() in CREDENTIAL and is_credential(v[h]))
                walk(node, v)

    for node, items in (pin.items() if isinstance(pin, dict) else []):
        walk(node, items)
    return out


def workflows(doc):
    docs = doc if isinstance(doc, list) else [doc]
    return [d for d in docs if isinstance(d, dict) and isinstance(d.get("nodes"), list)]


def tracked(root: pathlib.Path) -> list[str]:
    r = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", "*.json", "*.workflow.ts"],
                       capture_output=True, text=True, encoding="utf-8")
    return [p for p in r.stdout.split("\0") if p]


def load(path: pathlib.Path):
    """(text, bom): the file's own text — its line endings kept, a UTF-8 BOM taken off and noted."""
    raw = path.read_bytes()
    bom = raw.startswith(codecs.BOM_UTF8)
    return raw[len(codecs.BOM_UTF8):].decode("utf-8") if bom else raw.decode("utf-8"), bom


def save(path: pathlib.Path, text: str, bom: bool):
    """Encode first, then replace the file whole: a value that cannot be encoded leaves it as it was."""
    data = (codecs.BOM_UTF8 if bom else b"") + text.encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, path.stat().st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def header_lines(lines, h):
    """The lines where header `h` is written with a credential value, in file order."""
    pat = re.compile(r'^\s*"' + re.escape(h) + r'"\s*:\s*(.*?),?\s*$', re.I)
    out = []
    for i, l in enumerate(lines, 1):
        m = pat.match(l)
        if m:
            try:
                if is_credential(json.loads(m.group(1))):
                    out.append(i)
            except ValueError:
                pass
    return out


def read(root: pathlib.Path, rel: str):
    """(text, bom, kind, [(line, node, header)], pinned) — kind is 'json', 'ts' or '' (not a workflow)."""
    try:
        text, bom = load(root / rel)
    except (OSError, UnicodeDecodeError):
        return "", False, "", [], False
    found, pinned = [], False
    if rel.endswith(".workflow.ts"):
        for n, line in enumerate(text.split("\n"), 1):
            m = PIN_TS.match(line)
            if not m:
                continue
            try:
                pin = json.loads(m.group(2))
            except ValueError:
                found.append((n, "—", NOT_JSON))     # green and blind look alike: say it
                continue
            pinned = pinned or bool(pin)
            found += [(n, node, h) for node, h, _ in pinned_headers(pin)]
        return text, bom, "ts", found, pinned
    try:
        wfs = workflows(json.loads(text))
    except ValueError:
        return text, bom, "", [], False
    if not wfs:
        return text, bom, "", [], False
    lines = text.split("\n")
    seen = {}
    for wf in wfs:
        pin = wf.get("pinData") or {}
        pinned = pinned or bool(pin)
        for node, h, _ in pinned_headers(pin):
            at = header_lines(lines, h)
            k = seen[h.lower()] = seen.get(h.lower(), -1) + 1
            found.append((at[k] if k < len(at) else 1, node, h))
    return text, bom, "json", found, pinned


def stripped(pin):
    pin = copy.deepcopy(pin)
    for _node, h, headers in pinned_headers(pin):
        headers.pop(h, None)
    return pin


def fix_json(text: str) -> str:
    doc = json.loads(text)
    want = copy.deepcopy(doc)
    for wf in workflows(want):
        if wf.get("pinData"):
            wf["pinData"] = stripped(wf["pinData"])
    out = []
    for line in text.split("\n"):
        m = re.match(r'^\s*"([^"]+)"\s*:\s*(.*?)(,?)\s*$', line)
        if m and m.group(1).lower() in CREDENTIAL:
            try:
                val = json.loads(m.group(2))
            except ValueError:
                val = None
            if is_credential(val):
                if not m.group(3):           # the last entry: the one before it loses its comma
                    j = len(out) - 1
                    while j >= 0 and not out[j].strip():
                        j -= 1
                    if j >= 0:
                        out[j] = re.sub(r",(\s*)$", r"\1", out[j])
                continue
        out.append(line)
    new = "\n".join(out)
    try:
        if json.loads(new) == want:
            return new
    except ValueError:
        pass
    # Written again whole: in the file's own form when it was one line (`,` `:` with or without a
    # space, as the dump of the original reproduces it), else as n8n writes it; escaped when a value
    # cannot be written as UTF-8 (a lone surrogate, which JSON.stringify emits for a broken emoji).
    end = text[len(text.rstrip("\r\n")):]
    kw = {"indent": 2, "ensure_ascii": False}
    if "\n" not in text.strip():
        kw = next(({"separators": s, "ensure_ascii": a} for s in ((",", ":"), (", ", ": ")) for a in (False, True)
                   if json.dumps(doc, ensure_ascii=a, separators=s) == text.strip()), kw)
    out = json.dumps(want, **kw)
    try:
        out.encode("utf-8")
    except UnicodeEncodeError:
        out = json.dumps(want, **dict(kw, ensure_ascii=True))
    if "\r\n" in text:                          # a dump writes no raw newline inside a string
        out = out.replace("\n", "\r\n")
    return out + end


def fix_ts(text: str) -> str | None:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = PIN_TS.match(line)
        if not m:
            continue
        try:
            pin = json.loads(m.group(2))
        except ValueError:
            return None                      # not JSON: nothing here can be judged, so nothing is written
        if json.dumps(pin, ensure_ascii=False, separators=(",", ":")) != m.group(2):
            return None                      # it would not be written back as it was: a hand's job
        lines[i] = m.group(1) + json.dumps(stripped(pin), ensure_ascii=False, separators=(",", ":")) + m.group(3)
    return "\n".join(lines)


def check(root: pathlib.Path, list_only=False, fix=False, only=None) -> int:
    files = tracked(root)
    if only:
        want = {str(pathlib.Path(p).resolve()) for p in only}
        files = [f for f in files if str((root / f).resolve()) in want]
    n_wf = n_pinned = 0
    findings = []
    for rel in files:
        text, bom, kind, found, pinned = read(root, rel)
        if not kind:
            continue
        n_wf += 1
        n_pinned += pinned
        if list_only:
            print(rel)
            continue
        if found and fix:
            new = fix_json(text) if kind == "json" else fix_ts(text)
            if new is None:
                print(f"  {rel}: its pinData is not JSON or does not round-trip — strip the header by hand")
            else:
                save(root / rel, new, bom)
                print(f"  {rel}: stripped {len(found)} credential header(s)")
                _t, _b, _k, found, _p = read(root, rel)
        findings += [(rel, *f) for f in found]
    if list_only:
        return 0
    if n_wf == 0:
        print("pinned-credential-lint — G87 FAIL: no n8n workflow found to read — a gate that reads "
              "nothing passes everything")
        return 1
    if findings:
        print(f"pinned-credential-lint — G87 FAIL: {len(findings)} finding(s) in the pinned data of "
              f"committed workflows ({SAYS}):")
        for rel, line, node, h in findings:
            print(f"  {rel}:{line}  " + (h if h == NOT_JSON else f"node «{node}»  header `{h}`"))
        return 1
    print(f"pinned-credential-lint — G87 PASS: {n_wf} tracked n8n workflow file(s) read, {n_pinned} with "
          "pinned data, and none pins a credential its trigger captured")
    return 0


def self_test() -> int:
    def wf(headers):
        return {"name": "t", "nodes": [{"name": "Webhook"}], "connections": {},
                "pinData": {"Webhook": [{"json": {"headers": headers, "body": {"x": 1}}}]}}

    basic = {"host": "n8n.example", "authorization": "Basic REDACTED", "accept": "*/*"}
    cases = {
        "a Basic header a webhook captured": (wf(basic), 1),
        "a cookie, and a set-cookie list": (wf({"cookie": "sid=1", "set-cookie": ["a=b"]}), 2),
        "upper case": (wf({"Authorization": "Bearer abc"}), 1),
        "the platform's forward-auth JWT": (wf({"X-authentik-jwt": "eyJ.x.y"}), 1),
        "n8n's own redaction": (wf({"authorization": {"__redacted": True, "reason": "x", "canReveal": False}}), 0),
        "an empty value": (wf({"authorization": ""}), 0),
        "no credential header": (wf({"accept": "*/*", "host": "x"}), 0),
        "a header a node SENDS (parameters, not pinned)": (
            {"nodes": [{"name": "h", "parameters": {"headers": {"authorization": "={{ $env.X }}"}}}],
             "connections": {}, "pinData": {}}, 0),
    }
    got = {k: len([f for wfd in workflows(d) for f in pinned_headers(wfd.get("pinData") or {})])
           for k, (d, _n) in cases.items()}
    ok = all(got[k] == n for k, (_d, n) in cases.items())
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        subprocess.run(["git", "init", "-q", str(tmp)], check=True)
        ok = ok and check(tmp) == 1                                           # nothing to read
        d = tmp / "apps" / "x"
        d.mkdir(parents=True)
        body = json.dumps(wf(basic), indent=2) + "\n"
        (d / "w.json").write_text(body, encoding="utf-8")
        last = json.dumps(wf({"host": "n8n.example", "authorization": "Basic REDACTED"}), indent=2) + "\n"
        (d / "last.json").write_text(last, encoding="utf-8")     # the last header: the comma before goes
        ts = ("export class W {\n    /*__n8n__*/ pinData: "
              + json.dumps({"Webhook": [{"json": {"headers": dict(basic)}}]}, separators=(",", ":"))
              + ",\n}\n")
        (d / "w.workflow.ts").write_text(ts, encoding="utf-8")
        # each written back in its own form: CRLF, one compact line, a BOM — and a value UTF-8 cannot
        # hold (a lone surrogate, as JSON.stringify writes a broken emoji) never empties the file
        (d / "crlf.json").write_bytes(body.replace("\n", "\r\n").encode("utf-8"))
        one = json.dumps(wf(basic), separators=(",", ":")) + "\n"
        (d / "one.json").write_text(one, encoding="utf-8")
        sur = json.dumps(dict(wf(basic), note="NOTE"), separators=(",", ":")).replace('"NOTE"', '"x\\ud83dy"')
        (d / "sur.json").write_text(sur, encoding="utf-8")
        (d / "bom.json").write_bytes(codecs.BOM_UTF8 + body.encode("utf-8"))
        # the fallback path in their own form too: a set-cookie list spans lines (CRLF kept), and a
        # one-line export written ASCII-escaped stays one escaped line
        cookie = dict(wf(dict(basic, **{"set-cookie": ["a=1", "b=2"]})), name="שם")
        crlf2 = json.dumps(cookie, indent=2, ensure_ascii=False).replace("\n", "\r\n") + "\r\n"
        (d / "crlf2.json").write_bytes(crlf2.encode("utf-8"))
        esc = json.dumps(dict(wf(basic), name="שם"), separators=(",", ":"), ensure_ascii=True) + "\n"
        (d / "esc.json").write_text(esc, encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp), "add", "-A"], check=True)
        ok = ok and check(tmp) == 1                                           # all found
        ok = ok and check(tmp, fix=True) == 0                                 # and stripped
        for name in ("crlf.json", "one.json", "sur.json", "bom.json"):
            raw = (d / name).read_bytes()
            text = raw[3:].decode("utf-8") if raw.startswith(codecs.BOM_UTF8) else raw.decode("utf-8")
            ok = ok and "authorization" not in text and json.loads(text)["pinData"]["Webhook"][0]["json"]["headers"]["accept"] == "*/*"
        crlf = (d / "crlf.json").read_bytes()
        ok = ok and b"\r\n" in crlf and re.search(rb"[^\r]\n", crlf) is None
        ok = ok and (d / "one.json").read_text(encoding="utf-8").count("\n") == 1
        ok = ok and (d / "bom.json").read_bytes().startswith(codecs.BOM_UTF8)
        crlf2 = (d / "crlf2.json").read_bytes()
        ok = ok and re.search(rb"[^\r]\n", crlf2) is None and b"set-cookie" not in crlf2 and b"authorization" not in crlf2
        esc = (d / "esc.json").read_text(encoding="utf-8")
        ok = ok and esc.count("\n") == 1 and "\\u05e9" in esc and "authorization" not in esc
        after = (d / "w.json").read_text(encoding="utf-8")
        gone = [l for l in body.split("\n") if l not in after.split("\n")]
        ok = ok and len(gone) == 1 and "authorization" in gone[0]             # one line, that line
        ok = ok and json.loads(after)["pinData"]["Webhook"][0]["json"]["headers"] == {"host": "n8n.example", "accept": "*/*"}
        after_last = (d / "last.json").read_text(encoding="utf-8")
        ok = ok and len(after_last.split("\n")) == len(last.split("\n")) - 1
        ok = ok and json.loads(after_last)["pinData"]["Webhook"][0]["json"]["headers"] == {"host": "n8n.example"}
        ok = ok and "authorization" not in (d / "w.workflow.ts").read_text(encoding="utf-8")
        ok = ok and check(tmp) == 0
        # a blueprint whose pinData is not JSON is a finding, and --fix leaves it as it was
        bad = "export class B {\n    /*__n8n__*/ pinData: {notjson},\n}\n"
        (d / "bad.workflow.ts").write_text(bad, encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp), "add", "-A"], check=True)
        ok = ok and check(tmp) == 1 and check(tmp, fix=True) == 1
        ok = ok and (d / "bad.workflow.ts").read_text(encoding="utf-8") == bad
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("\npinned-credential-lint self-test: "
          + ("a captured Basic header, a cookie and a set-cookie list, an upper-case name and the platform's "
             "forward-auth JWT are caught; n8n's redaction, an empty value, a plain header and a header a "
             "node sends are not; --fix strips one line from a JSON export (and the comma before a last one) "
             "and the header from a blueprint, keeps CRLF, a one-line export and a BOM in their own form, "
             "never empties a file a lone surrogate cannot be written to; a blueprint's pinData that is not "
             "JSON is a finding --fix leaves alone; and an empty scan fails"
             if ok else "FAILED — got " + str(got)))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--files", action="store_true", help="list the workflow files this gate reads")
    ap.add_argument("--fix", action="store_true", help="strip the credential headers it finds")
    ap.add_argument("paths", nargs="*", help="with --fix: only these files")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    return check(REPO, list_only=a.files, fix=a.fix, only=a.paths or None)


if __name__ == "__main__":
    sys.exit(main())
