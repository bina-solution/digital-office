#!/usr/bin/env python3
"""Close a meeting's decisions and questions in bulk, through meet-start's own change_item() — the same path as the
page's buttons (approve a decision = «אושרה», approve a question = «נענתה», reject = dismissed). Tasks are refused here:
approving one files a Plane item, which is link_tasks.py's or the page's business.

    docker exec -i meet-start-<office> python - '<json>' < close_items.py
    json: [{"room": "fpg2", "kind": "question", "id": "Q12", "action": "reject"}, …]

DGO-1183 (the owner: «I come into the document and I see like 300 questions open … close everything. So really we
get only the questions we really need, if any»). A separate process from the server: the server's store lock does not
cover it, so it must NOT run while anyone has those meetings' pages open — an edit made there in between is lost —
and the meetings list may show the old counts for a minute (the server's own caches). Prints one line per room: how many were changed, and what is still open.
"""
import json
import sys

sys.path.insert(0, "/app")
import server  # noqa: E402  (meet-start's own module)

WHO = {"name": "Claude (סגירת שאלות, DGO-1183)", "username": "claude"}


def main(argv):
    try:
        rows = json.loads(argv[0])
        assert isinstance(rows, list) and rows
        assert all(r["kind"] in ("decision", "question") and r["action"] in ("approve", "reject") for r in rows)
    except (IndexError, ValueError, KeyError, TypeError, AssertionError):
        print("usage: close_items.py '<json list of {room, kind: decision|question, id, action: approve|reject}>'",
              file=sys.stderr)
        return 2
    done, failed = {}, []
    for r in rows:
        try:
            code, got = server.change_item(r["room"], WHO, {"kind": r["kind"], "id": r["id"], "action": r["action"]})
        except (OSError, server.StoreDown) as e:          # the door answers these 503; here the row is reported
            code, got = 503, str(e)
        if code == 200:
            done[r["room"]] = done.get(r["room"], 0) + 1
        else:
            failed.append(f"{r['room']} {r['kind']}:{r['id']} → {code} {got}")
    for room in sorted(done):
        flow = next((f for f in server.flows() if f["room"] == room), None)
        items = (server.folder_index(flow["folder"], text=True) or {}).get("items", []) if flow else []
        try:
            st = server.items_of(room, strict=True, fresh=True)
        except (OSError, server.StoreDown):
            print(f"{room}: {done[room]} closed; the store did not answer the recount")
            continue
        still = [f"{i['kind']}:{i['id']}" for i in items if i["kind"] in ("decision", "question")
                 and (st.get(f"{i['kind']}:{i['id']}") or {}).get("state", "proposed") in ("proposed", "edited")]
        print(f"{room}: {done[room]} closed; still open: {', '.join(still) or 'none'}")
    for f in failed:
        print("FAILED", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
