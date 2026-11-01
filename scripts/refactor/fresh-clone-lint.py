#!/usr/bin/env python3
"""fresh-clone-lint — gate G11: a tracked file may not depend on an untracked one.

    python3 scripts/refactor/fresh-clone-lint.py

The platform claims `git clone && ./bbox run` reaches a healthy stack on any machine. That claim is
only true if everything the tracked files reach for is itself tracked. Nothing enforced it, and the
gap was invisible locally because the missing file was sitting right there in the working tree.

That is exactly how it went wrong: `.gitignore` has `scripts/_*` for disposable one-off helpers,
and `scripts/_built_images.py` — the helper that tells a clean rebuild which images to delete — was
named into that namespace. It was never committed. `scripts/first-party-images` (tracked) called
it, so on a fresh clone that command dies with "No such file or directory", while on the laptop
that wrote it everything worked for weeks.

The check: for every tracked text file, find repo-relative paths it mentions, and fail on any that
exists on disk but is excluded by .gitignore. Existence matters — an unresolvable path is a typo or
a runtime-generated artifact, and neither is this bug. `.generated/` is exempt: it is compiled by
`reconcile.py` before use, and being absent from a fresh clone is the point.
"""
import pathlib, re, subprocess, sys

REPO = pathlib.Path(__file__).resolve().parents[2]

# Compiled at runtime, deliberately not committed — the compiler builds it before anything reads it.
EXEMPT_PREFIXES = (".generated/", "data/", "ci-artifacts/", ".refactor/")

# Declared exemptions: path -> why it is right for a fresh clone NOT to have this. Explicit and
# reasoned, like G1's __expected_diffs__, and stale entries are reported — an exemption list that
# nobody has to justify is just a slower way of deleting the gate.
EXEMPT = {
    "platform-base/authentik/blueprints/zz-generated-apps.yaml":
        "compiled by reconcile.py from app.json before authentik reads it",
    "apps/portainer/portainer_password.txt":
        "secret, generated on first `bbox run`; committing it would publish a credential",
    "platform-base/traefik/config/acme.json":
        "traefik's ACME account key + issued certificates, written at runtime by the "
        "certificate resolver. Committing it would publish a private key, and it is "
        "gitignored (.gitignore:148) for exactly that reason. Its only reference, "
        "scripts/deployment-archive.py:85, already treats it as optional -- the comment "
        "six lines above says 'a deployment that never issued a certificate has no "
        "acme.json'. On this host it is 0 bytes, which is that case.",
    "platform-base/traefik/config/zz-serve.yaml":
        "compiled by reconcile.py (render_serve) from the `remote:` block of platform.state.yaml "
        "-- the routers of the apps other offices give this one -- and REMOVED by the same render "
        "when nothing is given. A fresh clone is an office linked to nobody, so it has no such "
        "file and needs none. Both references treat it as an output: reconcile.py writes it, and "
        "apps/dgo-extend/tests/phase3.py compares it with the declaration and expects it ABSENT "
        "when nothing is declared. Without this entry the gate was red on exactly the offices "
        "that are linked (measured on the HP office 2026-10-05: a checkout that both had a link "
        "and ran the gates).",
}

# Paths that appear inside a repo-relative reference: scripts/x.py, platform/manager/y.py, apps/…
PATHISH = re.compile(r"(?<![\w./-])((?:scripts|platform|platform-base|apps|hooks)/[\w./-]+\.\w+)")
# Files that can actually RUN something. Prose is excluded on purpose and not as a convenience:
# ai/context/*.md and the Obsidian notes mention one-off debug helpers by name as a historical
# record, and a note recalling that `scripts/_trig.py` once existed is not a dependency on it.
# .gitignore is excluded for the same reason — listing a path is definitionally not depending on it.
TEXT_SUFFIXES = {"", ".py", ".sh", ".yml", ".yaml", ".json", ".cfg", ".toml"}


def _strip_prose(text, suffix):
    """Remove the parts that can only DESCRIBE a path, never invoke it: # / // line comments
    everywhere, plus triple-quoted docstrings in Python. Deliberately conservative — it is fine to
    keep something that turns out to be prose (a stray false negative), but a path a running script
    actually reaches for must survive."""
    if suffix == ".py":
        text = re.sub(r'"""[\s\S]*?"""', " ", text)
        text = re.sub(r"'''[\s\S]*?'''", " ", text)
    return re.sub(r"(?m)(^|\s)(#|//).*$", " ", text)


def tracked_files():
    out = subprocess.run(["git", "-C", str(REPO), "ls-files"],
                         capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if l]


def ignored(paths):
    """Which of these paths does .gitignore exclude? One git call, not one per path."""
    if not paths:
        return set()
    # -z on BOTH sides. Without it git quotes paths it considers unusual and terminates lines with
    # the platform's newline, so on Windows every result came back as "scripts/_x.py\r" — quoted,
    # CR-suffixed, and matching nothing.
    p = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-z", "--stdin"],
                       input="\0".join(paths), capture_output=True, text=True)
    return {s for s in p.stdout.split("\0") if s}


def main() -> int:
    tracked = set(tracked_files())
    refs = {}                                  # candidate path -> [referencing files]
    for rel in tracked:
        f = REPO / rel
        if f.suffix not in TEXT_SUFFIXES or not f.is_file() or rel == ".gitignore":
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # Strip comments/docstrings first. A path NAMED in prose is not a dependency — and this
        # gate's own docstring cites `scripts/_trig.py` as an example of exactly that, so an
        # unfiltered scan reported the gate as its own violation. Same lesson as G9's comment strip.
        code = _strip_prose(text, f.suffix)
        for m in PATHISH.finditer(code):
            cand = m.group(1)
            if cand in tracked or cand.startswith(EXEMPT_PREFIXES):
                continue
            if not (REPO / cand).exists():
                continue                        # typo or runtime artifact, not this bug
            refs.setdefault(cand, []).append(rel)

    bad = ignored(sorted(refs)) - set(EXEMPT)
    stale = set(EXEMPT) - ignored(sorted(set(EXEMPT)))
    if not bad:
        print(f"G11 PASS — every path a runnable tracked file reaches for is itself tracked "
              f"({len(tracked)} tracked file(s) scanned, {len(EXEMPT)} declared exemption(s)).")
        if stale:
            print(f"  note: {len(stale)} exemption(s) no longer needed: {sorted(stale)}")
        return 0

    print(f"G11 FAIL — {len(bad)} file(s) exist here but are NOT in the repo, so a fresh clone "
          f"breaks:")
    for cand in sorted(bad):
        print(f"  {cand}")
        for src in sorted(set(refs[cand]))[:4]:
            print(f"      referenced by {src}")
    print("  -> commit it (git add -f), or rename it out of the ignored namespace")
    return 1


if __name__ == "__main__":
    sys.exit(main())
