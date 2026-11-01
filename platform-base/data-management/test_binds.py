"""test_binds — what the archive calls a stateful bind, and what finding one may cost.

    python3 platform-base/data-management/test_binds.py

The inventory's last section asks the archiver (`scripts/deployment-archive.py::stateful_binds`)
which writable host directories hold files git does not track, and how big they are. On hp-laptop,
2026-10-07, that question took 39 of an inventory sweep's 54 seconds: the browser's profile is
mounted by five services, so its 2,008 files were walked five times, with two questions to a
Windows mount about every entry. The answer is the same when the directory is walked once — this
holds both: the answer (per file, so a tracked sentinel cannot hide a tree), and the one walk.

It builds a small git repository in a temp directory and gives the archiver a compose configuration
by hand. No docker, no network, nothing of the office is read.
"""
import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve()
spec = importlib.util.spec_from_file_location("archiver", HERE.parents[2] / "scripts" / "deployment-archive.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)


def _repo(tmp: pathlib.Path):
    files = {"data/profile/a.bin": b"x" * 10, "data/profile/sub/b.bin": b"y" * 5,
             "conf/tracked.yml": b"kept: true\n", "conf/generated.yml": b"made: 1\n",
             "alltracked/x.txt": b"in git\n", "single.conf": b"one file\n"}
    for rel, body in files.items():
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp / rel).write_bytes(body)
    git = lambda *a: subprocess.run(["git", "-C", str(tmp), *a], check=True, capture_output=True)
    git("init", "-q")
    git("add", "conf/tracked.yml", "alltracked/x.txt", "single.conf")
    bind = lambda rel, **kw: dict({"type": "bind", "source": str(tmp / rel), "target": "/x"}, **kw)
    return {"services": {
        **{f"s{i}": {"volumes": [bind("data/profile")]} for i in range(1, 6)},       # five services, one directory
        "conf": {"volumes": [bind("conf"), bind("alltracked"), bind("single.conf")]},
        "reader": {"volumes": [bind("data/profile", read_only=True), {"type": "volume", "source": "named", "target": "/v"},
                               {"type": "bind", "source": "/var/run/docker.sock", "target": "/var/run/docker.sock"},
                               {"type": "bind", "source": str(tmp.parent), "target": "/outside"}, bind("")]},
    }}


def test_the_answer_is_per_file_and_a_directory_is_walked_once():
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d).resolve() / "repo"
        tmp.mkdir()
        cfg = _repo(tmp)
        real_repo, real_walk, walks = A.REPO, os.walk, []
        A.REPO = tmp
        A.os.walk = lambda top, *a, **k: (walks.append(pathlib.Path(top).relative_to(tmp).as_posix()), real_walk(top, *a, **k))[1]
        try:
            found = A.stateful_binds(cfg)
        finally:
            A.REPO, A.os.walk = real_repo, real_walk
    # untracked files only, summed per directory; a directory whose every file is tracked is not state
    assert found == {"data/profile": 15, "conf": 8}, found
    assert "alltracked" not in found and "single.conf" not in found
    # the directory five services mount was walked ONCE; so was every other one
    assert sorted(walks) == ["alltracked", "conf", "data/profile"], walks


def test_a_file_that_goes_away_mid_walk_is_not_counted_and_fails_nothing():
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d).resolve() / "repo"
        tmp.mkdir()
        cfg = _repo(tmp)
        real_repo, real_stat = A.REPO, os.stat

        def stat(path, *a, **k):                      # a live browser profile: listed, then gone
            if str(path).endswith("b.bin"):
                raise FileNotFoundError(path)
            return real_stat(path, *a, **k)
        A.REPO, A.os.stat = tmp, stat
        try:
            found = A.stateful_binds(cfg)
        finally:
            A.REPO, A.os.stat = real_repo, real_stat
    assert found["data/profile"] == 10, found


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("  ok  ", t.__name__)
    print(f"archive binds: {len(tests)}/{len(tests)} ok")
