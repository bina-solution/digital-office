"""`op_list` follows Drive's pages, and stops at the caller's limit.

    python3 apps/drive/adapters/test_op_list_pages.py

(run as a script, not under pytest: pytest imports a test beside an `__init__.py` as part of that
package, and importing `adapters` needs the whole service's packages — which only its image has.)

The canonical list op asked Drive for `nextPageToken` and threw it away: a folder of 17,067 files
answered 100, at limit=100 and at limit=1000 alike (issues/drive-op-list-single-page.yaml). The fix
is a loop, and this is what holds it. No network: the adapter's one HTTP door (`_json`) is replaced
by a Drive that serves a folder in pages of ITS OWN size — smaller than asked, which is how
`corpora=allDrives` really answers and why a big pageSize was never a way around it.
"""
import importlib
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # apps/drive


def _have(name):
    """The real module where this machine has it, an empty stand-in where it does not. Nothing of
    either is called here — the adapter's HTTP door is replaced — and without this the test ran
    only inside the drive image: the gate's own host has no `requests`, and reported NOT RUN."""
    try:
        importlib.import_module(name)
    except Exception:                               # noqa: BLE001 — absent, or its own imports are
        sys.modules[name] = types.ModuleType(name)


for _name in ("requests", "connections_client"):
    _have(_name)
# google.py ALONE, as a module of a package that is only this directory: importing `adapters`
# itself pulls the other adapters in, and with them the database driver.
_pkg = types.ModuleType("drive_adapters")
_pkg.__path__ = [HERE]
sys.modules["drive_adapters"] = _pkg
GoogleDriveAdapter = importlib.import_module("drive_adapters.google").GoogleDriveAdapter


class Drive:
    """A folder of `total` files, served at most `page` per request whatever pageSize asks."""

    def __init__(self, total, page):
        self.total, self.page, self.asked = total, page, []

    def __call__(self, method, url, params=None, **kw):
        self.asked.append(dict(params))
        start = int(params.get("pageToken") or 0)
        n = min(int(params["pageSize"]), self.page, self.total - start)
        out = {"files": [{"id": f"f{i}"} for i in range(start, start + n)]}
        if start + n < self.total:
            out["nextPageToken"] = str(start + n)
        return out


def listed(total, page, **kw):
    adapter = GoogleDriveAdapter.__new__(GoogleDriveAdapter)   # no instance, no token: nothing is sent
    adapter._json = drive = Drive(total, page)
    return adapter.op_list(folder_id="F", **kw), drive


def test_a_folder_bigger_than_one_page_is_listed_up_to_the_limit():
    got, drive = listed(17067, 460, limit=1000)
    assert [f["id"] for f in got] == [f"f{i}" for i in range(1000)]
    assert len(drive.asked) == 3                    # 460 + 460 + 80


def test_the_default_limit_is_still_a_hundred_and_costs_one_request():
    got, drive = listed(17067, 460)
    assert len(got) == 100 and len(drive.asked) == 1


def test_a_folder_smaller_than_the_limit_is_listed_whole_and_the_walk_ends():
    got, drive = listed(250, 100, limit=1000)
    assert len(got) == 250 and len(drive.asked) == 3


def test_each_request_carries_the_token_the_one_before_it_was_given():
    _, drive = listed(300, 100, limit=300)
    assert [p.get("pageToken") for p in drive.asked] == [None, "100", "200"]


def test_page_size_stays_inside_what_drive_accepts_whatever_the_limit():
    got, drive = listed(5000, 1000, limit=100000)   # Drive refuses pageSize=100000 outright
    assert len(got) == 5000 and len(drive.asked) == 5
    assert all(1 <= p["pageSize"] <= 1000 for p in drive.asked)


if __name__ == "__main__":
    failed = 0
    for _name, _test in sorted(globals().items()):
        if not _name.startswith("test_"):
            continue
        try:
            _test()
            print("PASS ", _name[5:].replace("_", " "))
        except AssertionError:
            failed += 1
            print("FAIL ", _name[5:].replace("_", " "))
    print(f"\n{failed} failing")
    sys.exit(1 if failed else 0)
