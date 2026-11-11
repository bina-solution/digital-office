#!/usr/bin/env python3
"""test_cleanup.py — the machine app's cleanup answers what the daemon did, however long a prune takes (DGO-1811).

A prune of the Dell's 22.7 GB build cache outlasted the docker SDK's 60 s read timeout and answered 500 while the
daemon finished it. The docker client is faked here: no daemon, no stack.

    python3 platform-base/machine/test_cleanup.py      (in the machine image: fastapi, docker, requests)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["MACHINE_CLEANUP_ALLOWED_ACTIONS"] = "docker_builder_prune_all,docker_image_prune_all,not_an_action"
os.environ.pop("MACHINE_CLEANUP_TIMEOUT_S", None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import requests  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import app  # noqa: E402

FAIL: list[str] = []


def check(cond, what):
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        FAIL.append(what)


class FakeClient:
    def __init__(self, timeout, outcome):
        self.timeout, self.outcome, self.closed = timeout, outcome, False
        fake = self

        class Api:
            def prune_builds(self, all=False):
                if isinstance(fake.outcome, Exception):
                    raise fake.outcome
                return fake.outcome

        class Images:
            def prune(self, filters=None):
                return {"SpaceReclaimed": 7}

        self.api, self.images = Api(), Images()

    def close(self):
        self.closed = True


made: list[FakeClient] = []


def from_env(outcome):
    def make(timeout=None):
        made.append(FakeClient(timeout, outcome))
        return made[-1]
    return make


def status(call):
    try:
        call()
    except HTTPException as e:
        return e.status_code
    return 200


# a long prune: the client's own timeout is the cleanup's (540 s, under the edge's 600), and it is closed
app.docker.from_env = from_env({"SpaceReclaimed": 22_680_000_000})
answer = app.run_cleanup("docker_builder_prune_all")
check(answer["result"]["SpaceReclaimed"] == 22_680_000_000, "the prune's own result is the answer")
check(made[-1].timeout == 540 and made[-1].closed, "its client: 540 s, closed after")
# the read gives up: 504 that says the daemon may still finish, never 500 «failed»
app.docker.from_env = from_env(requests.exceptions.ReadTimeout("read timed out"))
check(status(lambda: app.run_cleanup("docker_builder_prune_all")) == 504, "a read timeout answers 504")
check(made[-1].closed, "…and its client is closed")
# an unknown action, even when allowed by a typo in the env: 404 before any client is made
n = len(made)
check(status(lambda: app.run_cleanup("not_an_action")) == 404, "an unknown action answers 404")
check(len(made) == n, "…without making a client")
check(status(lambda: app.run_cleanup("docker_container_prune")) == 403, "an action not allowed answers 403")
# the knob: a number is taken, a typo or a non-positive value falls back, never a crash
for value, want in (("120", 120), ("15m", 540), ("0", 540), ("-3", 540), ("", 540)):
    os.environ["MACHINE_CLEANUP_TIMEOUT_S"] = value
    check(app._cleanup_timeout() == want, f"MACHINE_CLEANUP_TIMEOUT_S={value!r} → {want}")

print("PASS" if not FAIL else f"FAILED {len(FAIL)}")
sys.exit(1 if FAIL else 0)
