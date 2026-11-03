#!/usr/bin/env python3
"""Store a meeting's tasks as approved, each with the Plane item it already has — so the meeting page shows «ב-Plane ·
FPG-622» on it and approving it again files nothing (approve_task answers the stored link). Plane stays the one place
tasks are managed; the page points at it.

    docker exec -i meet-start-<office> python - ROOM '<json>'|@<file> < link_tasks.py
    json: [{"id": "T1", "key": "FPG-622", "url": "https://…", "text": "…", "t": 97}]

Runs inside meet-start: it uses that server's own store (Drive, or MEET_FLOW_DATA) and its own item_after(). It is a
process of its own, so the running server's store lock does not cover it: run it while nobody is editing that meeting
(a change made in the page in between would be lost), right after build_flow.py. Every id must be a task of the
meeting's data.js. A task already approved with a link is left as it is. Exit 0 done, 2 refused (nothing written).
"""
import json
import sys

sys.path.insert(0, "/app")
import server  # noqa: E402  (meet-start's own module)


def main(argv):
    if len(argv) != 2 or not server.FLOW_ROOM_RE.fullmatch(argv[0] or ""):
        print("usage: link_tasks.py ROOM '<json list of {id, key, url, text?, t?}>'", file=sys.stderr)
        return 2
    room = argv[0]
    try:
        if argv[1].startswith("@"):                     # @<file>: the list in a file (Hebrew survives no shell quoting)
            with open(argv[1][1:], encoding="utf-8") as f:
                argv[1] = f.read()
        rows = json.loads(argv[1])
        assert isinstance(rows, list) and rows
        for r in rows:
            assert server.FLOW_ID_RE.fullmatch(str(r["id"])) and r["key"] and str(r["url"]).startswith("https://")
    except (ValueError, KeyError, TypeError, AssertionError):
        print("link_tasks: each row needs id, key and an https url", file=sys.stderr)
        return 2
    missing = [r["id"] for r in rows if not server.data_item(room, "task", str(r["id"]))]
    if missing:                                         # a link on no task of the page would be shown nowhere
        print(f"link_tasks: not tasks of {room}'s data.js: {', '.join(missing)}", file=sys.stderr)
        return 2
    who = {"name": "Claude (עיבוד הפגישה)", "username": "claude"}
    done = []
    with server._store:
        items = server.items_of(room, strict=True, fresh=True)
        for r in rows:
            key = f"task:{r['id']}"
            have = items.get(key) or {}
            if have.get("state") == "approved" and have.get("plane"):
                done.append({"id": r["id"], "plane": have["plane"].get("key"), "kept": True})
                continue
            fields = {}
            if str(r.get("text") or "").strip():
                fields["text"] = str(r["text"]).strip()
            if isinstance(r.get("t"), (int, float)) and r["t"] >= 0:
                fields["t"] = float(r["t"])
            e = server.item_after(have or None, "task", r["id"], "approve", {}, who)
            if fields and not e["fields"]:
                e["fields"] = fields
            e["plane"] = {"key": r["key"], "url": r["url"], "id": r.get("plane_id") or ""}
            items[key] = e
            done.append({"id": r["id"], "plane": r["key"]})
        server.meta_put(room, "items.json", server.meta_dump(items))
    print(json.dumps({"ok": True, "room": room, "tasks": done}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
