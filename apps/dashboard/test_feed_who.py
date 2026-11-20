"""test_feed_who.py — who opened or closed a work item, said in its line (feed.py members/by_of, DGO-1329).

    python3 apps/dashboard/test_feed_who.py

What is asked: the workspace's members become {id: name} (a display name, else the first and last name, else the
mailbox); a close is said with who last moved the item, an open with who made it; an id nobody knows, or a members
list that cannot be read, leaves the line as it was. And the group's line ends with the name (group.py items).
"""
import importlib.util
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp()
os.environ.update(DASHBOARD_STATE=os.path.join(TMP, "state.json"), DASHBOARD_HERD=os.path.join(TMP, "none.yaml"))
SPEC = importlib.util.spec_from_file_location("dashboard_feed_who", os.path.join(HERE, "feed.py"))
f = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(f)
sys.path.insert(0, HERE)
import group  # noqa: E402


def issue(state="s", **kw):
    return dict({"id": "i1", "sequence_id": 7, "name": "item", "state": state, "created_at": "2026-11-05T10:00:00+00:00",
                 "updated_at": "2026-11-05T12:00:00+00:00", "completed_at": "2026-11-05T12:00:00+00:00"}, **kw)


class Who(unittest.TestCase):
    def setUp(self):
        f.WHO.clear()

    def test_members_become_names(self):
        f.pages = lambda base, path: [{"member": {"id": "u1", "display_name": "עזריה"}},
                                      {"id": "u2", "first_name": "Owner", "last_name": "B"},
                                      {"id": "u3", "email": "office@bina.local"}, {"member": {}}]
        self.assertEqual(f.members("http://plane"), {"u1": "עזריה", "u2": "Owner B", "u3": "office"})

    def test_a_members_list_not_read_is_no_names(self):
        def boom(base, path):
            raise RuntimeError("HTTP 502")
        f.pages = boom
        self.assertEqual(f.members("http://plane"), {})

    def test_a_close_names_who_moved_it_an_open_who_made_it(self):
        f.WHO.update({"u1": "עזריה", "u2": "שלמה"})
        line = f.moved("started", "completed", issue(updated_by="u1", created_by="u2"))
        self.assertEqual((line["kind"], line["by"]), ("done", "עזריה"))
        line = f.moved(None, "backlog", issue(updated_by="u1", created_by="u2"))
        self.assertEqual((line["kind"], line["by"]), ("open", "שלמה"))
        line = f.moved("started", "completed", issue(updated_by="nobody"))
        self.assertNotIn("by", line)

    def test_the_groups_line_ends_with_the_name(self):
        out, t = [], [1_800_000_000.0]
        relay = group.Relay(group.load_rules(), lambda text: out.append(text) or 1, now=lambda: t[0])
        relay.items([])
        t[0] += 30
        relay.items([{"ts": t[0] - 5, "kind": "done", "text": "נסגר: הקישור בכרטיס", "ref": "DGO-1400", "by": "עזריה"}])
        self.assertIn("• הקישור בכרטיס DGO-1400 — עזריה", out[0])     # the name first, then who did it (DGO-2102)


if __name__ == "__main__":
    unittest.main()
