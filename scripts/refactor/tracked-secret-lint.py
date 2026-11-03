#!/usr/bin/env python3
"""tracked-secret-lint — gate G92: no tracked file carries a private key or a provider's token.

    python3 scripts/refactor/tracked-secret-lint.py               # every tracked text file; exit 1 on a finding
    python3 scripts/refactor/tracked-secret-lint.py --self-test   # prove it can fail, on made-up text

WHY (DGO-1223). A GCP service-account key sat in apps/chat/trash/users_sheet.js until it was found by hand
(S2, DGO-852), and the public repo's own history was found holding real data on 2026-11-03 (DGO-1232). The
public export scrubs what it publishes (scripts/release/public-export.py), but nothing asked the PRIVATE repo,
where every office's checkout — a client's server included — reads it. This gate asks. Its first run found an
OpenSSH private key in ai/context/OWNER-MESSAGES-FULL.md, its public half still trusted on the Dell (removed
that night, 029d4899).

WHAT IS A SECRET here is the export's own definition, loaded from it, never copied: its TOKENS (a provider's
key or token by its prefix and shape — ghp_, sk-, AKIA, AIza, ya29., xox…, a Telegram bot token, a JWT, …) and
its KEY_BEGIN, a PEM private-key header — counted only when a key BODY follows it: on the header's own line, or
on the first line within four below it that is neither blank nor an armor header (Proc-Type:, DEK-Info:,
Version: …), a run of 40+ base64 characters with a capital letter in it, quoted, commented or concatenated as it
may be. A doc or a regex that names the header is not a finding. A text file over the export's MAX_TEXT is not
read, and fails: it is a file nothing asked. A tree without scripts/release/ (the public copy drops it) has no
definition to ask with and SKIPs; a tree with the directory and not the export FAILS, so a rename cannot turn
this into a silent pass.

IT NEVER PRINTS A VALUE: a finding is `path:line kind`, the line counted on "\\n" as grep -n counts it. A
finding that is not a secret — a fixture's made-up token, the export's own patterns — is declared in ALLOWED as
a COUNT per kind per file, with its reason, so one more of a kind in that file (a real token beside the fake
ones) fails, and so does a declaration that outlived what it declared: fewer of a kind than declared, a file no
longer read or no longer tracked. `.env.ex` is declared with its four until DGO-1220 empties it; its entry then
fails until it is removed.
"""
import argparse
import collections
import importlib.util
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RELEASE = os.path.join(REPO, "scripts", "release")

# path → ({kind: how many}, and why they are not a leak to fix here)
ALLOWED = {
    ".env.ex": ({"jwt": 3, "anthropic-key": 1},
                "the template's own values; DGO-1220 part 2 empties them, and this entry then fails until it is removed"),
    "scripts/release/public-export.py": ({"aws-key-id": 1, "jwt": 1}, "the export's own patterns and stand-ins"),
    "scripts/release/public-export-selftest.py": ({"jwt": 2, "slack-webhook": 1, "google-client-secret": 1,
                                                   "stripe-webhook-secret": 1},
                                                  "the export's own cases: made-up tokens it must scrub"),
    "digital-office/sim/mocks/connections.js": ({"google-oauth-token": 1, "google-refresh-token": 1,
                                                 "private-key": 1, "openai-key": 1},
                                                "the simulator's made-up connection values — shorter than real ones "
                                                "(ya29 82 chars vs ~170, refresh 42 vs ~100, a key body of 8), "
                                                "measured by the release session 2026-11-03 (DGO-1223)"),
}
RUN = re.compile(r"[A-Za-z0-9+/]{40,}")
ARMOR = re.compile(r"^[\s>#/*'\"]*[A-Za-z][A-Za-z-]*:\s")   # Proc-Type: 4,ENCRYPTED — DEK-Info: — Version: —
BELOW = 4


def definitions(release=RELEASE):
    """('skip', None) for a tree without scripts/release/, ('missing', None) for one with the directory and not
    the export, else ('ok', the export's module)."""
    if not os.path.isdir(release):
        return "skip", None
    path = os.path.join(release, "public-export.py")
    if not os.path.isfile(path):
        return "missing", None
    spec = importlib.util.spec_from_file_location("public_export", path)
    pe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pe)
    return "ok", pe


def tracked():
    out = subprocess.run(["git", "-C", REPO, "ls-files", "-z"], capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def keyish(s):
    return any(re.search(r"[A-Z]", m.group()) for m in RUN.finditer(s))


def body_below(lines, n):
    """Line n (1-based) is a key header: is its body on the first line below it that is not blank or armor?"""
    for nxt in lines[n:n + BELOW]:
        if not nxt.strip() or ARMOR.match(nxt):
            continue
        return keyish(nxt)
    return False


def scan(pe, text):
    """[(line, kind)] for one file's text; lines counted on "\\n", as grep -n counts them."""
    found, lines = [], text.split("\n")
    for n, line in enumerate(lines, 1):
        for kind, rx, _ in pe.TOKENS:
            if rx.search(line):
                found.append((n, kind))
        m = pe.KEY_BEGIN.search(line)
        if m and (keyish(line[m.end():]) or body_below(lines, n)):
            found.append((n, "private-key"))
    return found


def judge(results, allowed, tracked_paths):
    """results: path → [(line, kind)] for every file read. → ([(path, line, kind)] that fail, [stale sentence])."""
    fails, stale = [], []
    for path, found in sorted(results.items()):
        declared = allowed.get(path, ({}, ""))[0]
        held = collections.Counter(kind for _, kind in found)
        for kind in sorted(set(held) | set(declared)):
            count = declared.get(kind, 0)
            if held[kind] > count:
                more = f" (more than the {count} it declares)" if count else ""
                fails += [(path, n, k + more) for n, k in found if k == kind]
            elif held[kind] < count:
                stale.append(f"{path} declares {count} {kind} and holds {held[kind]}: lower its count in ALLOWED")
    for path in sorted(allowed):
        if path not in tracked_paths:
            stale.append(f"{path} is declared in ALLOWED and no longer tracked: remove it")
        elif path not in results:
            stale.append(f"{path} is declared in ALLOWED and was not read (missing on disk, binary, a link, "
                         "or over MAX_TEXT)")
    return fails, stale


def self_test(pe):
    """Made-up text, built at run time, so this file never holds the shapes it looks for."""
    tok = "gh" + "p_" + "Zx9" * 11
    head = "-----BEGIN " + "RSA " + "PRIVATE KEY-----"
    end = "-----END " + "RSA " + "PRIVATE KEY-----"
    body = "MII" + "Ab1+/" * 12
    key = [(1, "private-key")]
    scans = [
        ("a token, its line counted on \\n (U+2028 ends no line)", "x y\n" + tok, [(2, "github-token")]),
        ("a key, its body below", head + "\n" + body + "\n" + end, key),
        ("a key under an armor header and a blank line", head + "\nProc-Type: 4,ENCRYPTED\n\n" + body, key),
        ("a quoted key", "> " + head + "\n> " + body, key),
        ("a commented key", "# " + head + "\n# " + body, key),
        ("a key concatenated in code", "'" + head + "\\n' +\n'" + body + "\\n' +", key),
        ("a key on one escaped line", '"' + head + "\\n" + body + '\\n"', key),
        ("a header named in prose", "the header " + head + " opens a key\nand nothing follows it", []),
        ("a header with no body before its end", head + "\n" + end, []),
        ("a lowercase hex run is no body", head + "\n" + "0123456789abcdef" * 4, []),
    ]
    bad = []
    for name, text, want in scans:
        got = scan(pe, text)
        if got != want:
            bad.append(f"{name}: got {got}, want {want}")
    one = {"f": ({"k": 1}, "x")}
    judged = [
        ("one more than declared fails, every line of that kind",
         judge({"f": [(1, "k"), (2, "k")]}, one, {"f"}),
         ([("f", 1, "k (more than the 1 it declares)"), ("f", 2, "k (more than the 1 it declares)")], 0)),
        ("a kind it does not declare fails, and the one it lost is stale",
         judge({"f": [(2, "j")]}, one, {"f"}), ([("f", 2, "j")], 1)),
        ("an undeclared file's finding fails", judge({"g": [(3, "k")]}, {}, {"g"}), ([("g", 3, "k")], 0)),
        ("as declared passes", judge({"f": [(1, "k")]}, one, {"f"}), ([], 0)),
        ("fewer than declared is stale", judge({"f": []}, one, {"f"}), ([], 1)),
        ("declared and not read is stale", judge({}, one, {"f"}), ([], 1)),
        ("declared and not tracked is stale", judge({}, one, set()), ([], 1)),
    ]
    for name, (fails, stale), (want_fails, want_stale) in judged:
        if fails != want_fails or len(stale) != want_stale:
            bad.append(f"{name}: got {fails} and {len(stale)} stale")
    with tempfile.TemporaryDirectory() as tmp:
        release = os.path.join(tmp, "scripts", "release")
        states = [("a tree without scripts/release/ skips", definitions(release)[0], "skip")]
        os.makedirs(release)
        states.append(("a scripts/release/ without the export fails", definitions(release)[0], "missing"))
    for name, got, want in states:
        if got != want:
            bad.append(f"{name}: got {got}")
    for b in bad:
        print(f"  FAIL  {b}")
    total = len(scans) + len(judged) + len(states)
    print(f"G92 self-test: {total - len(bad)}/{total} passed")
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--self-test", action="store_true", help="prove the gate can fail, on made-up text")
    a = ap.parse_args(argv)
    state, pe = definitions()
    if state == "skip":
        print("G92 SKIP — no scripts/release/ in this tree (the public copy drops it): no definition of a secret to ask with")
        return 0
    if state == "missing":
        print("G92 FAIL — scripts/release/ is here and scripts/release/public-export.py is not: the definition of a "
              "secret moved, and this gate must follow it")
        return 1
    if a.self_test:
        return self_test(pe)
    files = tracked()
    results, over = {}, []
    for path in files:
        full = os.path.join(REPO, path)
        try:
            if os.path.islink(full) or not os.path.isfile(full):
                continue
            with open(full, "rb") as f:
                if b"\0" in f.read(8192):          # a binary file: no line to point at
                    continue
                if os.path.getsize(full) > pe.MAX_TEXT:
                    over.append(path)
                    continue
                f.seek(0)
                raw = f.read()
        except OSError:
            continue
        results[path] = scan(pe, raw.decode("utf-8", "replace"))
    if not results:
        print(f"G92 FAIL — read 0 of {len(files)} tracked file(s): a scan that reads nothing proves nothing")
        return 1
    fails, stale = judge(results, ALLOWED, set(files))
    for path, n, kind in fails:
        print(f"  FAIL  {path}:{n}  {kind}")
    for s in stale:
        print(f"  FAIL  {s}")
    for path in over:
        print(f"  FAIL  {path} is a text file over the export's {pe.MAX_TEXT // 2**20} MiB: not read, so not asked")
    declared = sum(min(sum(1 for _, k in results.get(p, []) if k == kind), c)
                   for p, (kinds, _) in ALLOWED.items() for kind, c in kinds.items())
    ok = not fails and not stale and not over
    print(f"G92 {'PASS' if ok else 'FAIL'} — {len(results)} tracked text file(s) read of {len(files)}, {len(over)} over "
          f"the export's {pe.MAX_TEXT // 2**20} MiB; {len(fails)} finding(s) outside ALLOWED, {declared} declared in "
          f"{len(ALLOWED)} file(s), {len(stale)} stale declaration(s); no value is ever printed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
