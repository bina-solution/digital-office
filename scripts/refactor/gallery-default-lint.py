#!/usr/bin/env python3
"""gallery-default-lint — gate G23: gallery apps ship DISABLED, and ship a clean disposition.

    python3 scripts/refactor/gallery-default-lint.py [--self-test]

WHY THIS GATE EXISTS

A fresh install must start the platform and nothing else. Every optional app — the operator tools,
the samples, the things a user chooses — has to be absent until someone installs it. Two ways that
quietly stopped being true:

  * `hello-bina` shipped `enabled: true`. It is the third-party SAMPLE app, and every fresh install
    started it. Nobody asked for a demo.
  * `portainer` shipped `{ state: archived, by: user }`. `archived` is a disposition a USER chose
    (images and containers dropped to reclaim disk, data kept) — it is meaningless as a committed
    default, because a fresh install never had it installed to archive. It also carried
    `by: user` for a user who does not exist yet.

Neither is catchable by reading a manifest: both live in the desired-state file, which is the file
the console writes at runtime, so a local experiment is one `git add -A` away from becoming the
shipped default. That is exactly what happened.

THE RULE

An app in GALLERY_APPS must be committed as `{ enabled: false }` — not archived, not enabled, and
with no `by:` provenance. Everything else in the file is free to be whatever the deployment needs.

WHICH FILE — THIS IS THE HALF THAT WAS WRONG UNTIL 2026-10-09

The gate used to read `platform.state.yaml`, which is the OFFICE's own runtime file: on an office it
therefore judged that office's choices, and in a clean clone it judged whichever office's copy had
been committed last. Both are the wrong question — "what does a fresh install start from?" is a
property of the product, and since the split that is `platform.state.default.yaml` (tracked; written
by nobody; see its header). The default is what this gate judges; `platform.state.yaml` falls back
only for a checkout that predates the split.

GALLERY_APPS is the explicit list rather than something inferred (e.g. "layer 3 and not depended
on"), because which apps are optional is a PRODUCT decision, not a graph property. indox and mail
are layer 3 and nothing requires them either — they are the product.
"""
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
STATE = REPO / "platform.state.yaml"
DEFAULT_STATE = REPO / "platform.state.default.yaml"

GALLERY_APPS = {
    "browser42",
    "google-workspace-agent",
    "hello-bina",
    "ollama",
    "openhands",
    "portainer",
    "redisinsight",
    "supabase",
}


def judge(text: str) -> list[tuple[str, str, str]]:
    """(app, block, why) for every gallery app the given desired-state text gets wrong."""
    problems, seen = [], set()
    for m in re.finditer(r"^\s+([a-z0-9-]+):\s*(\{[^}]*\})\s*$", text, flags=re.M):
        aid, block = m.group(1), m.group(2)
        if aid not in GALLERY_APPS:
            continue
        seen.add(aid)
        if "state:" in block:
            problems.append((aid, block, "ships a `state:` disposition; a gallery default is "
                                         "`{ enabled: false }` — archived/enabled are runtime choices"))
        elif re.search(r"enabled:\s*true", block):
            problems.append((aid, block, "ships ENABLED; a fresh install would start it unasked"))
        elif not re.search(r"enabled:\s*false", block):
            problems.append((aid, block, "does not declare `enabled: false`"))
        if "by:" in block:
            problems.append((aid, block, "carries `by:` provenance for a user who does not exist "
                                         "on a fresh install"))

    for missing in sorted(GALLERY_APPS - seen):
        problems.append((missing, "-", "is not declared in the judged file at all"))
    return problems


def office_file_is_tracked() -> bool:
    """Is the OFFICE's own file still under version control in this checkout?"""
    try:
        out = subprocess.run(["git", "ls-files", "--error-unmatch", STATE.name],
                             cwd=REPO, capture_output=True, text=True, timeout=10)
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _clean_text() -> str:
    """A desired-state text in which every gallery app is exactly `{ enabled: false }`."""
    return "apps:\n" + "".join(f"  {a}: {{ enabled: false }}\n" for a in sorted(GALLERY_APPS))


def self_test() -> int:
    bad = 0

    def check(label, cond):
        nonlocal bad
        bad += 0 if cond else 1
        print(f"  [{'ok ' if cond else 'FAIL'}] {label}")

    check("a clean gallery default passes", judge(_clean_text()) == [])
    check("PROVE IT CAN FAIL — enabled", any("ENABLED" in w for _a, _b, w in judge(
        _clean_text().replace("hello-bina: { enabled: false }", "hello-bina: { enabled: true }"))))
    check("PROVE IT CAN FAIL — a runtime disposition", any("state:" in w for _a, _b, w in judge(
        _clean_text().replace("portainer: { enabled: false }",
                              "portainer: { state: archived, by: user }"))))
    check("PROVE IT CAN FAIL — by: on a disabled app", any("by:" in w for _a, _b, w in judge(
        _clean_text().replace("supabase: { enabled: false }",
                              "supabase: { enabled: false, by: user }"))))
    check("PROVE IT CAN FAIL — a gallery app that is absent", any("not declared" in w for _a, _b, w
        in judge(_clean_text().replace("ollama: { enabled: false }", ""))))
    check("a non-gallery app is not this gate's business", judge(
        _clean_text() + "  mail: { state: disabled, by: cli }\n") == [])
    return bad


def main() -> int:
    # THE DEFAULT IS THE SUBJECT. `platform.state.yaml` is the office's runtime and is judged by
    # nobody here; the fallback exists so a checkout from before the split still reads something.
    target = DEFAULT_STATE if DEFAULT_STATE.exists() else STATE
    if not target.exists():
        print(f"gallery-default-lint: neither {DEFAULT_STATE.name} nor {STATE.name} exists",
              file=sys.stderr)
        return 2
    problems = judge(target.read_text(encoding="utf-8"))

    if problems:
        print("gallery-default-lint: FAIL — a fresh install would not be clean\n")
        for aid, block, why in problems:
            print(f"  {aid}: {block}")
            print(f"      {why}")
        print(f"\nA fresh install starts the platform and nothing else. Commit gallery apps as")
        print(f"`{{ enabled: false }}` in {target.name}; enable them at runtime instead.")
        return 1

    print(f"OK — all {len(GALLERY_APPS)} gallery app(s) ship disabled in {target.name}")
    if target is DEFAULT_STATE and office_file_is_tracked():
        # NOT a failure: stopping to track the office's file is the OWNER's step (a shared resource
        # across three offices), and it is recorded as such on the item. Said on every run so it
        # cannot be forgotten — the split is half-landed while this line prints.
        print(f"  note: {STATE.name} is still TRACKED in this checkout. The split's remaining step "
              f"(the owner's) is to untrack it, so a pull can never carry one office's runtime to "
              f"another. Until then a fresh clone still starts from the committed copy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test() if "--self-test" in sys.argv[1:] else main())
