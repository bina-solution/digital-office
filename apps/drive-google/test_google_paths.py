"""A Google account is a drive like the office's own: its top, its tree, its paths (DGO-1390).

    python3 apps/drive-google/test_google_paths.py

(run as a script, like test_op_list_pages.py beside it; the engine's modules are imported alone, with
`requests` and the vault client stood in where this machine lacks them.)

The screen, the agents' path verbs (`api/fs`) and the CLI ask a Google account what they ask the local
drive: the top of «הקבצים שלי» is "", a path names a file, a folder has a path, a folder path is made on
demand, a name that is taken gets «(2)». Google answers `parents: [<the root's id>]` for what sits at the
top, hides the parent of what somebody shared, and puts a shared drive outside My Drive — so each of those
is held here against a Drive that answers in Google's own shapes. No network: the adapter's two HTTP doors
(`_json`, `_req`) are replaced.
"""
import importlib
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                           # apps/drive-google


def _have(name):
    try:
        importlib.import_module(name)
    except Exception:                               # noqa: BLE001 — absent, or its own imports are
        sys.modules[name] = types.ModuleType(name)


for _name in ("requests", "connections_client"):
    _have(_name)
G = importlib.import_module("gdrive")
GSA = importlib.import_module("gdrive_sa")
FOLDER = G.FOLDER_MIME


class Resp:
    def __init__(self, status=200, body=None, content=b"", headers=None):
        self.status_code, self._body, self.content, self.headers = status, body, content, headers or {}
        if body is not None and not content:
            self.content = b"{}"

    def json(self):
        return self._body or {}

    def iter_content(self, n):
        yield self.content


class Drive:
    """My Drive (root R): A/ (report.pdf, a Google Doc), A/B/, notes.txt at the top, a folder S somebody
    shared (no parent this account can see), and a shared drive «Team» holding X/."""

    def __init__(self):
        self.items = {
            "A": {"id": "A", "name": "עבודה", "mimeType": FOLDER, "parents": ["R"]},
            "B": {"id": "B", "name": "לקוחות", "mimeType": FOLDER, "parents": ["A"]},
            "S": {"id": "S", "name": "משותף", "mimeType": FOLDER},
            "X": {"id": "X", "name": "נהלים", "mimeType": FOLDER, "parents": ["TD"], "driveId": "TD"},
            "f1": {"id": "f1", "name": "notes.txt", "mimeType": "text/plain", "parents": ["R"], "size": "12"},
            "f2": {"id": "f2", "name": "report.pdf", "mimeType": "application/pdf", "parents": ["A"], "size": "900",
                   "md5Checksum": "abc"},
            "g1": {"id": "g1", "name": "תקציב", "mimeType": "application/vnd.google-apps.document", "parents": ["A"]},
            "h1": {"id": "h1", "name": "page.html", "mimeType": "text/html", "parents": ["R"], "size": "40"},
        }
        self.posts, self.n, self.asked = [], 0, []

    def match(self, q, f):
        for clause in re.split(r" and ", q):
            c = clause.strip()
            if (m := re.fullmatch(r"'([^']+)' in parents", c)):
                pid = "R" if m[1] == "root" else m[1]
                if pid not in (f.get("parents") or []):
                    return False
            elif (m := re.fullmatch(r"name = '(.+)'", c)):
                if f["name"] != m[1].replace("\\'", "'"):
                    return False
            elif c.replace(" ", "") == "trashed=false":
                if f.get("trashed"):
                    return False
            elif c.replace(" ", "") == "trashed=true":
                if not f.get("trashed"):
                    return False
            elif c.replace(" ", "") == f"mimeType='{FOLDER}'":
                if f["mimeType"] != FOLDER:
                    return False
            elif c.replace(" ", "") == f"mimeType!='{FOLDER}'":
                if f["mimeType"] == FOLDER:
                    return False
            else:
                raise AssertionError("the fake Drive does not know the clause " + repr(c))
        return True

    def json(self, method, url, params=None, json=None, **kw):
        params = params or {}
        path = url.split("/drive/v3/", 1)[1]
        if method == "GET" and path == "files/root":
            return {"id": "R"}
        if method == "GET" and path == "drives":
            return {"drives": [{"id": "TD", "name": "Team"}]}
        if method == "GET" and path == "files":
            self.asked.append(dict(params))
            return {"files": [dict(f) for f in self.items.values() if self.match(params["q"], f)]}
        if method == "GET" and path.startswith("files/"):
            return dict(self.items[path.split("/", 1)[1]])
        if method == "POST" and path == "files":
            self.n += 1
            fid = f"new{self.n}"
            self.items[fid] = {"id": fid, "name": json["name"], "mimeType": json["mimeType"], "parents": json.get("parents") or ["R"]}
            self.posts.append(json)
            return dict(self.items[fid])
        raise AssertionError(f"the fake Drive does not know {method} {path}")

    def req(self, method, url, params=None, headers=None, stream=False, **kw):
        params = params or {}
        path = url.split("/drive/v3/", 1)[1] if "/drive/v3/" in url else url
        if path.endswith("/export"):
            self.exported = params["mimeType"]
            return Resp(200, content=b"%PDF", headers={"Content-Type": params["mimeType"]})
        if params.get("alt") == "media":
            return Resp(200, content=b"bytes", headers={"Content-Type": "text/html", "Content-Length": "5"})
        fid = path.split("/", 1)[1]
        return Resp(200, body=dict(self.items[fid])) if fid in self.items else Resp(404, body={"error": {"message": "nf"}})


def adapter(cls=G.GoogleDriveAdapter, name="cid-1"):
    a = cls.__new__(cls)
    a.instance, a.cid, a.owner_email = {"id": name}, name, "me@example.com"
    d = Drive()
    a._json, a._req = d.json, d.req
    G._ROOTS.pop(name, None)
    return a, d


def test_the_top_of_my_drive_is_the_empty_folder_and_a_shared_drive_is_a_place_of_its_own():
    a, _ = adapter()
    f = {x["id"]: x for x in a.folders()}
    assert f["A"]["parent"] is None and f["B"]["parent"] == "A"
    assert f["TD"]["parent"] is None and f["TD"]["drive"] and f["X"]["parent"] == "TD"
    assert f["S"]["shared"] and f["S"]["parent"] is None          # shared with me: not in the tree
    assert [x["id"] for x in a.subfolders("")] == ["TD", "A"]     # the top lists My Drive and the shared drive


def test_a_service_account_has_what_was_shared_with_it_at_its_top():
    a, _ = adapter(GSA.GoogleServiceAccountAdapter, "sa-1")
    f = {x["id"]: x for x in a.folders()}
    assert not f["S"].get("shared") and f["S"]["parent"] is None
    assert "S" in [x["id"] for x in a.subfolders("")]


def test_the_top_lists_its_own_files_with_folder_empty():
    a, _ = adapter()
    got = {x["id"]: x for x in a.files("")}
    assert set(got) == {"f1", "h1"} and got["f1"]["folder"] == ""
    # app.py's api/files passes the local engine's paging to every engine that lists trashed folders
    assert {x["id"] for x in a.files("A", False, limit="1000", offset="0")} == {"f2", "g1"}


def test_a_folder_listing_never_reads_all_drives_at_once():
    a, d = adapter()
    a.files("A")
    assert "corpora" not in d.asked[-1]                     # My Drive: read exactly as it always was
    a.files("X")
    assert d.asked[-1]["corpora"] == "drive" and d.asked[-1]["driveId"] == "TD"   # a shared drive's folder: that drive


def test_a_path_names_a_file_a_folder_or_nothing():
    a, _ = adapter()
    kind, item = a.resolve_path("/עבודה/report.pdf")
    assert kind == "file" and item["id"] == "f2" and item["md5"] == "abc"
    assert a.resolve_path("/עבודה/לקוחות")[1]["id"] == "B"
    assert a.resolve_path("/Team/נהלים")[1]["id"] == "X"
    assert a.resolve_path("/משותף")[1]["id"] == "S"             # a shared folder is reached by its name
    assert a.resolve_path("/") == ("folder", {"id": "", "name": "", "path": "/"})
    assert a.resolve_path("/אין/כזה") is None and a.resolve_path("/report.pdf") is None


def test_a_folder_has_its_path():
    a, _ = adapter()
    assert a.path_of("B") == "/עבודה/לקוחות" and a.path_of("") == "/" and a.path_of("X") == "/Team/נהלים"


def test_a_folder_path_is_made_once():
    a, d = adapter()
    fid = a.ensure_path("/עבודה/חדש")
    assert len(d.posts) == 1 and d.posts[0]["parents"] == ["A"] and d.items[fid]["name"] == "חדש"
    assert a.ensure_path("/עבודה/חדש") == fid and len(d.posts) == 1


def test_a_taken_name_gets_a_number():
    a, _ = adapter()
    assert a.free_name("A", "report.pdf") == "report (2).pdf" and a.free_name("A", "other.pdf") == "other.pdf"


def test_a_google_doc_is_exported_and_a_users_page_never_runs_here():
    a, d = adapter()
    status, hdrs, _ = a.content("g1", None, "inline")
    assert status == 200 and d.exported == "application/pdf" and "inline" in hdrs["Content-Disposition"]
    a.content("g1", None, "attachment")
    assert d.exported.endswith("wordprocessingml.document")
    _, hdrs, _ = a.content("h1", None, "inline")
    assert hdrs["Content-Type"].startswith("text/plain") and "sandbox" in hdrs["Content-Security-Policy"]


def test_every_shared_drive_is_read_across_pages():
    a, d = adapter()
    pages = {None: {"drives": [{"id": "TD", "name": "Team"}], "nextPageToken": "p2"},
             "p2": {"drives": [{"id": "TE", "name": "Sales"}]}}
    plain = d.json
    d.json = lambda m, url, params=None, **kw: (pages[(params or {}).get("pageToken")]
                                                if url.endswith("/drives") else plain(m, url, params=params, **kw))
    a._json = d.json
    assert [x["id"] for x in a._drives()] == ["TD", "TE"]


def test_the_trash_folders_are_paged_up_to_the_callers_limit():
    a, d = adapter()
    trashed = [{"id": f"t{i}", "name": f"ישן {i}", "mimeType": FOLDER, "parents": ["R"], "trashed": True} for i in range(5)]
    asked = []

    def json(m, url, params=None, **kw):
        if not url.endswith("/files"):
            return Drive.json(d, m, url, params=params, **kw)
        asked.append(dict(params))
        start = int(params.get("pageToken") or 0)
        rows = trashed[start:start + 2]
        return {"files": rows, **({"nextPageToken": str(start + 2)} if start + 2 < len(trashed) else {})}
    a._json = json
    got = a.trashed_folders()
    assert [f["id"] for f in got] == [f"t{i}" for i in range(5)] and all(f["trashed"] for f in got)
    assert all("nextPageToken" in p["fields"] for p in asked) and len(asked) == 3
    assert [f["id"] for f in a.trashed_folders(limit=3)] == ["t0", "t1", "t2"]


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS ", name)
            except Exception as e:                     # noqa: BLE001
                failed += 1
                print("FAIL ", name, "—", repr(e))
    print("OK" if not failed else f"FAILED: {failed}")
    sys.exit(1 if failed else 0)
