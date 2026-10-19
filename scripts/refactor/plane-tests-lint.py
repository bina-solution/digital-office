#!/usr/bin/env python3
"""plane-tests-lint — gate G72: a test that lives beside a plane or an app is RUN by the gate suite.

    python3 scripts/refactor/plane-tests-lint.py              # run them; exit 1 if one fails
    python3 scripts/refactor/plane-tests-lint.py --strict     # …and if one could not be run here
    python3 scripts/refactor/plane-tests-lint.py --in-images  # …on an office: in its own app's image
    python3 scripts/refactor/plane-tests-lint.py --self-test

WHY THIS EXISTS. The planes keep their unit tests beside their code — `platform/manager/test_*.py`,
`platform-base/<plane>/test_*` — and what those tests hold are DECISIONS no running stack can be
made to show on demand: when the sign-in hook restarts the server and when it must not, what the
readiness probe calls "served", what a bring-up refuses, whether a machine has room for an app.
On 2026-10-06 there were ten such files and ci-verify.yml ran three of them (G14, G16, G17). The
other seven ran when their author remembered to — which is the state `GATES.md` calls
documentation: "A gate that runs nowhere". One of them had been passing only inside its own
container ever since it was written (it ran a hook from `/repo`), and nobody could have known.

THE APPS, TOO (2026-10-07). An app keeps the same kind of file — `apps/<app>/test_*`, one directory
below it (`tests/`, `mailapi/`), and the self-checks in its `tools/`. Twenty-one of them, and one was a
step in ci-verify.yml; the other twenty ran when somebody remembered. `apps/git/tools/ui-selfcheck.mjs`
is why they are here: it holds the rule "the first paint never says CONNECTED before a credential is
probed", and a header reworded that very day broke it — found only because the file was run by hand.

AND THE SELF-TESTS (2026-10-07, later). `platform/manager/catalog_selftest.py` — twenty-two refusals
of the signed catalog: a forged index, a wrong hash, an app claiming another's route — and
`apps/dgo-extend/tests/connect-selftest.mjs` (the pairing offer's format) were run by nothing at
all. They are discovered by where they sit: beside the compiler, and in an app's `tests/`. NOT by
name alone, on purpose: `apps/git/selftest.py` creates and deletes a repository on the owner's
real account, and `platform-base/data-management/selftest_sweep.py` needs its running service —
a gate that ran every file called "selftest" would have run those.

AND THE MAP'S OWN TOOLS (2026-10-09). `scripts/ui-coverage/test_guards.py` — eleven guards that keep
the UI inventory's denominator from shrinking in silence — had been run by nothing since it was
written, and the rule every photograph waits for (`drawn.py`: when a screen has said what it has to
say, and when it took too long) arrived the same way: the only gate that noticed the new file was
the one that reads its encoding. A tool that decides what the maps may call a screen is a plane's
decision in everything but its directory; `scripts/ui-coverage/test_*` is discovered with the rest.

WHAT IT DOES. Every `test_*.py` / `test_*.sh` / `test_*.mjs` directly inside `platform/manager`, a
`platform-base/<plane>` directory, an `apps/<app>` directory or one directory below it, or
`scripts/ui-coverage` — and every
`*selfcheck*` in an app's `tools/`, every `*selftest*` beside the compiler or in an app's `tests/` —
is run with the interpreter its name asks for, from the repo root:
a `.py` with top-level `def test_…` and no `__main__` block through pytest, any other `.py` as a
script, `.sh` through bash, `.mjs` through node. A test that ci-verify.yml already runs as a step of
its own is NOT run a second time — it is listed, with the reason.

THREE OUTCOMES, AND NONE OF THEM IS SILENT:
  PASS      it ran and exited 0;
  FAIL      it ran and did not — the gate exits 1;
  NOT RUN   it could not be run on THIS machine: it imports a package only its own image has
            (`fastapi`, `requests`), or its interpreter is missing (node, bash, pytest). Named, with
            what it needs. That is not a pass, and under `--strict` it is a failure; without it the
            gate still exits 0, because a lane that has no node is not a lane with a broken dock.

IN ITS OWN IMAGE (`--in-images`, 2026-10-07). Sixteen of the forty-six could not be run where the
gate runs — the console's, the mail backend's, data-management's, apitools' — and no lane ran them
in the image that has their packages either: the mail backend's `thread(bodies=false)` was a 500
with a test file sitting next to it. On an office, a test this machine cannot run is run in the
image its app is built into: a throwaway container, no network, the checkout's tracked files
unpacked over the image's own in its working directory (a copy inside the container: a test may
write a log beside its code, and nothing reaches the checkout). Which image is asked of the
office's compiled project (the directory each service builds from), never of a list. The images carry no pytest, and a test
is not a reason to ship one: this interpreter's own is lent to the container, at the END of its
module path, so every package the image has stays the image's. What still cannot run is named with
why: its app is not part of this office, its image is not on this engine, or it is not a unit test
at all (it asked for a service on the loopback, and a container with no network has none).
`run-gates.py --live` — `bbox baseline`'s live lane — runs the gate this way.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
CI = REPO / ".github" / "workflows" / "ci-verify.yml"


def discover(repo: pathlib.Path) -> list[pathlib.Path]:
    """The test files beside the planes of `repo`, sorted. An empty answer is a FAILURE of the gate
    (`check`), never a pass: a discovery that finds nothing has measured nothing."""
    return sorted({f for pattern in ("platform/manager/test_*", "platform-base/*/test_*",
                                     "apps/*/test_*", "apps/*/*/test_*", "apps/*/tools/*selfcheck*",
                                     "platform/manager/*selftest*", "apps/*/tests/*selftest*",
                                     "scripts/ui-coverage/test_*")
                   for f in repo.glob(pattern) if f.is_file() and f.suffix in (".py", ".sh", ".mjs")})


def runner(test: pathlib.Path) -> tuple[list[str] | None, str]:
    """(command prefix, "") for this test, or (None, what is missing here)."""
    if test.suffix == ".sh":
        if os.name == "nt" or not shutil.which("bash"):
            return None, "a POSIX bash"
        return ["bash"], ""
    if test.suffix == ".mjs":
        return (["node"], "") if shutil.which("node") else (None, "node")
    src = test.read_text(encoding="utf-8", errors="replace")
    if re.search(r"^def test_", src, re.M) and "__main__" not in src:
        return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], ""
    return [sys.executable], ""


def run(test: pathlib.Path, repo: pathlib.Path) -> tuple[str, str]:
    """("PASS" | "FAIL" | "NOT RUN", what it said / what it needs)."""
    cmd, missing = runner(test)
    if cmd is None:
        return "NOT RUN", f"needs {missing}"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run(cmd + [str(test.relative_to(repo))], cwd=repo, env=env, timeout=900,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return "FAIL", "still running after 900 s"
    out = (r.stdout or "") + (r.stderr or "")
    last = ([ln.strip() for ln in out.splitlines() if ln.strip()] or [f"exit {r.returncode}"])[-1][:110]
    if r.returncode == 0:
        return "PASS", last
    # Both spellings: an import inside the test ("ModuleNotFoundError: No module named 'fastapi'")
    # and the interpreter refusing `-m pytest` ("python3: No module named pytest").
    absent = re.search(r"No module named '?([A-Za-z0-9_.]+)'?", out)
    if absent:
        return "NOT RUN", f"needs the package `{absent.group(1).split('.')[0]}` (its own image has it)"
    return "FAIL", last


def built_images(repo: pathlib.Path) -> dict[str, str] | None:
    """{the directory an image is built from (repo-relative): the image} for THIS office's compiled
    project — or None where there is no office to ask (no engine, no rendered project): CI, a clone."""
    if os.name == "nt" or not shutil.which("docker") or not shutil.which("bash"):
        return None
    try:
        r = subprocess.run(["bash", "scripts/dc", "config", "--format", "json"], cwd=repo, timeout=180,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        doc = json.loads(r.stdout[r.stdout.index("{"):]) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        doc = None
    if not doc:
        return None
    built: dict[str, str] = {}
    for name, svc in (doc.get("services") or {}).items():
        b = svc.get("build")
        ctx = b.get("context") if isinstance(b, dict) else b
        if not ctx:
            continue
        try:
            rel = pathlib.Path(ctx).resolve().relative_to(repo.resolve()).as_posix()
        except ValueError:
            continue
        built.setdefault(rel, svc.get("image") or f"{doc.get('name')}-{name}")
    return built


def image_for(rel: str, built: dict[str, str]) -> tuple[str, str] | None:
    """(directory, image) of the image whose build holds this test — the deepest such directory."""
    inside = [(ctx, image) for ctx, image in built.items() if rel.startswith(ctx.rstrip("/") + "/")]
    return max(inside, key=lambda pair: len(pair[0])) if inside else None


def pytest_kit(into: pathlib.Path) -> bool:
    """pytest as THIS interpreter has it, copied into one directory to lend to a container."""
    import importlib
    for name in ("pytest", "_pytest", "py", "pluggy", "iniconfig", "packaging", "pygments",
                 "exceptiongroup", "tomli", "typing_extensions"):
        try:
            src = pathlib.Path(importlib.import_module(name).__file__)
        except (ImportError, TypeError):
            if name == "pytest":
                return False
            continue
        if src.name == "__init__.py":
            shutil.copytree(src.parent, into / src.parent.name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, into / src.name)
    return True


def verdict_in_image(returncode: int, out: str, image: str) -> tuple[str, str]:
    """What a run inside an image says, in the gate's three words."""
    # the last line that SAYS something: a script's closing rule of dashes is not its verdict
    last = ([ln.strip() for ln in out.splitlines() if re.search(r"[^\W_]", ln)] or [f"exit {returncode}"])[-1][:90]
    if returncode == 0:
        return "PASS", f"in its image ({image}): {last}"
    absent = re.search(r"No module named '?([A-Za-z0-9_.]+)'?", out)
    if absent:
        return "NOT RUN", f"its image ({image}) has no `{absent.group(1).split('.')[0]}` either"
    if re.search(r"Connection refused|Max retries exceeded|Failed to establish a new connection", out):
        return "NOT RUN", "not a unit test: it asks a running service on the loopback (a lane of its app's own)"
    return "FAIL", f"in its image ({image}): {last}"


def tracked_tar(repo: pathlib.Path, ctx: str, also: pathlib.Path) -> bytes | None:
    """The checkout's tracked files under `ctx` (as they are on disk now), and the test itself, as a
    tar — what the container is given. Tracked only: a build directory's untracked bulk stays out."""
    try:
        listed = subprocess.run(["git", "-C", str(repo / ctx), "ls-files", "-z"], capture_output=True, timeout=60)
        names = {n for n in listed.stdout.split(b"\0") if n and (repo / ctx / n.decode("utf-8", "replace")).is_file()}
        names.add(also.relative_to(repo / ctx).as_posix().encode("utf-8"))
        tar = subprocess.run(["tar", "-C", str(repo / ctx), "--null", "-T", "-", "-cf", "-"],
                             input=b"\0".join(sorted(names)), capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return tar.stdout if tar.returncode == 0 and tar.stdout else None


#: What runs inside the container: unpack the checkout's files over the image's own, lend pytest at
#: the END of the module path, then run the test the way its file asks — through pytest, or as the
#: script it is (its own directory first on the path, as `python3 file.py` has it).
IN_IMAGE = (
    "import os, runpy, sys, tarfile\n"
    "pack = tarfile.open(fileobj=sys.stdin.buffer, mode='r|')\n"
    "pack.extractall('.', **({'filter': 'data'} if hasattr(tarfile, 'data_filter') else {}))\n"
    "sys.path.append('/zz-pytest')\n"
    "rel, how = sys.argv[1], sys.argv[2]\n"
    "if how == 'pytest':\n"
    "    import pytest\n"
    "    sys.exit(pytest.main(['-q', '-p', 'no:cacheprovider', rel]))\n"
    "sys.argv = [rel]\n"
    "sys.path.insert(0, os.path.dirname(os.path.abspath(rel)))\n"
    "runpy.run_path(rel, run_name='__main__')\n"
)


def run_in_image(test: pathlib.Path, repo: pathlib.Path, built: dict[str, str], kit: pathlib.Path | None,
                 tars: dict[str, bytes | None] | None = None) -> tuple[str, str]:
    """Run one test in the image its app is built into: a throwaway container with no network, the
    checkout's tracked files unpacked over the image's own in its working directory. A copy inside
    the container, not a mount: a test may write beside its code (a log, a scratch directory), and
    nothing it writes reaches the checkout."""
    found = image_for(test.relative_to(repo).as_posix(), built)
    if not found:
        return "NOT RUN", "its app is not part of this office (nothing here is built from its directory)"
    ctx, image = found
    seen = subprocess.run(["docker", "image", "inspect", "-f", "{{.Config.WorkingDir}}", image],
                          capture_output=True, text=True)
    if seen.returncode != 0:
        return "NOT RUN", f"its image ({image}) is not on this engine"
    work = seen.stdout.strip() or "/zz-work"
    src = test.read_text(encoding="utf-8", errors="replace")
    how = "pytest" if re.search(r"^(async )?def test_", src, re.M) and "__main__" not in src else "script"
    if how == "pytest" and kit is None:
        return "NOT RUN", "needs pytest, and this machine has none to lend its image"
    tars = {} if tars is None else tars
    if ctx not in tars:
        tars[ctx] = tracked_tar(repo, ctx, test)
    if tars[ctx] is None:
        return "NOT RUN", "this machine could not pack its app's files (git and tar are needed)"
    lend = ["-v", f"{kit}:/zz-pytest:ro"] if kit is not None else []
    try:
        r = subprocess.run(["docker", "run", "--rm", "-i", "--network", "none", "--user", "0:0", *lend, "-w", work,
                            "-e", f"PYTHONPATH={work}", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "PYTHONIOENCODING=utf-8",
                            "--entrypoint", "python3", image, "-c", IN_IMAGE,
                            test.relative_to(repo / ctx).as_posix(), how],
                           input=tars[ctx], timeout=900, capture_output=True)
    except subprocess.TimeoutExpired:
        return "FAIL", f"in its image ({image}): still running after 900 s"
    said, noise = ((x or b"").decode("utf-8", "replace") for x in (r.stdout, r.stderr))
    # a test that passed is quoted by what it SAID: a fake peer's dropped connection on stderr is not its verdict
    return verdict_in_image(r.returncode, said if r.returncode == 0 and said.strip() else said + noise, image)


def own_steps(tests: list[pathlib.Path], repo: pathlib.Path) -> set[pathlib.Path]:
    """The tests ci-verify.yml already runs as a step of their own — not to be run twice."""
    try:
        ci = (repo / ".github" / "workflows" / "ci-verify.yml").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return {t for t in tests if t.relative_to(repo).as_posix() in ci}


def check(repo: pathlib.Path, strict: bool, in_images: bool = False) -> int:
    tests = discover(repo)
    elsewhere = own_steps(tests, repo)
    counts = {"PASS": 0, "FAIL": 0, "NOT RUN": 0}
    failed: list[str] = []
    print("plane-tests-lint — G72: the tests beside the planes and the apps")
    built = built_images(repo) if in_images else None
    kit_dir = pathlib.Path(tempfile.mkdtemp(prefix="zz-pytest-")) if built is not None else None
    kit = kit_dir if kit_dir is not None and pytest_kit(kit_dir) else None
    tars: dict[str, bytes | None] = {}                       # one pack of an app's files, however many tests
    if in_images and built is None:
        print("  --in-images: there is no office to ask here (no engine, or no compiled project) — "
              "every test is run on this machine only")
    try:
        for t in tests:
            rel = t.relative_to(repo).as_posix()
            if t in elsewhere:
                print(f"  step      {rel}  — a step of its own in ci-verify.yml; not run a second time")
                continue
            verdict, said = run(t, repo)
            if verdict == "NOT RUN" and built is not None and t.suffix == ".py":
                verdict, said = run_in_image(t, repo, built, kit, tars)
            counts[verdict] += 1
            print(f"  {verdict:8}  {rel}  — {said}")
            if verdict == "FAIL":
                failed.append(f"  FAIL      {rel}  — {said}")
    finally:
        if kit_dir is not None:
            shutil.rmtree(kit_dir, ignore_errors=True)
    if not tests:
        print("  FAIL      no test was found beside any plane or app — the discovery is broken, not they")
        return 1
    bad = counts["FAIL"] + (counts["NOT RUN"] if strict else 0)
    # What failed is said AGAIN, last. The gates lane shows a failing gate's last eight lines, and a
    # test that failed among the first of fifty is not in them: "1 failed", and nothing to say which
    # (2026-10-09 — one did, in a run under load, and three runs after it could not find it again).
    if failed:
        print("\n  the ones that failed:")
        for line in failed[-5:]:
            print(line)
    print(f"\nG72 {'FAIL' if bad else 'PASS'} — {counts['PASS']} ran and passed, {counts['FAIL']} failed, "
          f"{counts['NOT RUN']} could NOT be run on this machine"
          + (" or in an image of this office" if built is not None else "") + f", {len(elsewhere)} are steps of their own"
          + (" (--strict: a test that was not run is a failure)" if strict and counts["NOT RUN"] else ""))
    return 1 if bad else 0


def self_test() -> int:
    """A tree with one test of each outcome: the gate must tell them apart, and must not be green."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        plane = tmp / "platform-base" / "thing"
        plane.mkdir(parents=True)
        (tmp / "platform" / "manager").mkdir(parents=True)
        (plane / "test_passes.py").write_text('if __name__ == "__main__":\n    print("fine")\n', encoding="utf-8")
        (plane / "test_fails.py").write_text('if __name__ == "__main__":\n    raise SystemExit(3)\n', encoding="utf-8")
        (plane / "test_needs.py").write_text('import a_package_no_machine_has\nif __name__ == "__main__":\n    pass\n',
                                             encoding="utf-8")
        # …and the way an interpreter without pytest says it, which is not a traceback
        (plane / "test_no_runner.py").write_text(
            'import sys\nif __name__ == "__main__":\n'
            '    sys.exit(sys.executable + ": No module named pytest")\n', encoding="utf-8")
        (plane / "helper.py").write_text("raise SystemExit(9)\n", encoding="utf-8")   # not a test: never run
        # an app's: beside it, one directory below it, and the self-check in its tools/
        app = tmp / "apps" / "thing"
        for sub, name in (("", "test_beside.py"), ("tests", "test_below.py"), ("tools", "ui-selfcheck.py")):
            (app / sub).mkdir(parents=True, exist_ok=True)
            (app / sub / name).write_text('if __name__ == "__main__":\n    print("fine")\n', encoding="utf-8")
        (app / "tools" / "build.py").write_text("raise SystemExit(9)\n", encoding="utf-8")       # a tool, not a check
        # self-tests: beside the compiler and in an app's tests/ — never one at an app's root, which
        # is where the kind that talks to a real account lives
        for where, name in ((tmp / "platform" / "manager", "catalog_selftest.py"), (app / "tests", "connect-selftest.py")):
            (where / name).write_text('if __name__ == "__main__":\n    print("fine")\n', encoding="utf-8")
        (app / "selftest.py").write_text("raise SystemExit(9)\n", encoding="utf-8")
        (app / "tests" / "deep").mkdir()
        (app / "tests" / "deep" / "test_too_deep.py").write_text("raise SystemExit(9)\n", encoding="utf-8")
        # the map's own tools: a test beside them, and not one of any other directory of scripts/
        for where, name, body in (("ui-coverage", "test_map_tool.py", 'if __name__ == "__main__":\n    print("fine")\n'),
                                  ("ops", "test_elsewhere.py", "raise SystemExit(9)\n")):
            (tmp / "scripts" / where).mkdir(parents=True)
            (tmp / "scripts" / where / name).write_text(body, encoding="utf-8")
        got = {t.name: run(t, tmp)[0] for t in discover(tmp)}
        want = {"test_fails.py": "FAIL", "test_needs.py": "NOT RUN", "test_no_runner.py": "NOT RUN",
                "test_passes.py": "PASS", "test_beside.py": "PASS", "test_below.py": "PASS", "ui-selfcheck.py": "PASS",
                "catalog_selftest.py": "PASS", "connect-selftest.py": "PASS", "test_map_tool.py": "PASS"}
        ok = got == want and check(tmp, strict=False) == 1
        (plane / "test_fails.py").unlink()
        ok = ok and check(tmp, strict=False) == 0 and check(tmp, strict=True) == 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # …and the half that runs a test in its app's image: which image, and what its answer means
    built = {"apps/mail": "mail-all", "apps/mail/mailapi": "mailapi", "platform-base/console": "console"}
    image = [
        image_for("apps/mail/mailapi/test_latency_cache.py", built) == ("apps/mail/mailapi", "mailapi"),   # the deepest
        image_for("apps/mail/tests/test_x.py", built) == ("apps/mail", "mail-all"),
        image_for("apps/mailbox/test_x.py", built) is None,              # a name that only starts the same
        image_for("apps/drive/test_x.py", built) is None,                # an app this office does not build
        verdict_in_image(0, "17 passed in 0.4s", "console") == ("PASS", "in its image (console): 17 passed in 0.4s"),
        verdict_in_image(1, "E  assert 1 == 2\n1 failed", "console")[0] == "FAIL",
        verdict_in_image(1, "ModuleNotFoundError: No module named 'cv2'", "console")[0] == "NOT RUN",
        verdict_in_image(1, "requests.exceptions.ConnectionError: … Connection refused", "apitools")[0] == "NOT RUN",
    ]
    ok = ok and all(image)
    print("\nplane-tests-lint self-test: "
          + ("10/10 outcomes told apart (planes, apps, self-tests, the map's tools); a failing test fails the gate, an unrunnable one "
             f"only under --strict; {sum(image)}/{len(image)} about a test's own image"
             if ok else "FAILED — got " + str(got) + " · image cases " + str(image)))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="a test that could not be run here is a failure")
    ap.add_argument("--in-images", action="store_true",
                    help="on an office: a test this machine cannot run is run in its own app's image")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    return self_test() if a.self_test else check(REPO, a.strict, a.in_images)


if __name__ == "__main__":
    sys.exit(main())
