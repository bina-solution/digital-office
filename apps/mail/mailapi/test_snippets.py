"""snippets.py — the list's preview line (DGO-1507). Pure: no IMAP server, a fake connection."""
import base64
import quopri
import unittest

import snippets


def leaf(num, sub="plain", enc="7BIT", charset="utf-8", att=False):
    return {"num": num, "type": "text", "subtype": sub, "enc": enc, "charset": charset,
            "size": 100, "filename": "", "is_att": att}


class Decode(unittest.TestCase):
    def test_base64_cut_inside_a_quantum(self):
        raw = base64.encodebytes("שלום, החשבונית מצורפת. תודה רבה".encode())
        self.assertEqual(snippets.decode_peek(raw[:-7], "BASE64", "utf-8", False)[:5], "שלום,")

    def test_quoted_printable_cut_inside_an_escape(self):
        raw = quopri.encodestring("חשבונית מס 4120".encode())
        cut = raw[: raw.rindex(b"=") + 2]                  # «=D7=9» — half an escape at the end
        self.assertTrue(snippets.decode_peek(cut, "QUOTED-PRINTABLE", "utf-8", False).startswith("חשבונית"))

    def test_iana_hebrew_label(self):
        raw = "שלום".encode("iso-8859-8")
        self.assertEqual(snippets.decode_peek(raw, "8BIT", "iso-8859-8-i", False), "שלום")

    def test_unknown_charset_is_utf8_not_an_error(self):
        self.assertEqual(snippets.decode_peek(b"hello", "7BIT", "x-no-such", False), "hello")

    def test_html_reduced_to_text(self):
        raw = b"<html><head><style>p{color:red}</style></head><body><p>Hi&nbsp;there</p><p>second</p></body></html>"
        self.assertEqual(snippets.decode_peek(raw, "7BIT", "utf-8", True), "Hi there second")

    def test_html_cut_inside_a_tag(self):
        self.assertEqual(snippets.decode_peek(b"<p>text</p><a href=\"http://x", "7BIT", "utf-8", True), "text")

    def test_character_cut_in_half(self):
        raw = "שלום".encode()[:-1]
        self.assertEqual(snippets.decode_peek(raw, "8BIT", "utf-8", False), "שלו")

    def test_quote_and_signature_cut(self):
        text = "Thanks, see below\n\nOn Sat, Nov 7, 2026 at 5:37 AM Dani <d@x>\nwrote:\n> old text"
        self.assertEqual(snippets.clean(text), "Thanks, see below")
        self.assertEqual(snippets.clean("מצורף\n-- \nחתימה"), "מצורף")
        self.assertEqual(snippets.clean("תודה\nב-7 בנוב׳ 2026, דני כתב/ה:\n> ישן"), "תודה")

    def test_heading_underlines_dropped(self):
        # a real staging message (2026-10-12): a plain-text heading underlined with «=» and «-»
        self.assertEqual(snippets.clean("הלשכה הדיגיטלית — הסבר\n=======\nמה זה\n-----\nמערכת אחת"),
                         "הלשכה הדיגיטלית — הסבר מה זה מערכת אחת")

    def test_kept_length(self):
        out = snippets.clean("א" * 500)
        self.assertEqual(len(out), snippets.KEEP + 1)
        self.assertTrue(out.endswith("…"))


class Leaf(unittest.TestCase):
    def test_plain_before_html_and_never_an_attachment(self):
        leaves = [leaf("1", "plain", att=True), leaf("2.1", "html"), leaf("2.2", "plain")]
        self.assertEqual(snippets.text_leaf(leaves)["num"], "2.2")
        self.assertEqual(snippets.text_leaf([leaf("1", "html")])["num"], "1")
        self.assertIsNone(snippets.text_leaf([{"num": "1", "type": "application", "subtype": "pdf", "is_att": True}]))


class FakeConn:
    def __init__(self, bodies):
        self.bodies, self.calls = bodies, []

    def fetch(self, uids, items):
        self.calls.append((tuple(uids), items[0]))
        num = items[0].decode().split("[")[1].split("]")[0]
        return {u: {("BODY[%s]<0>" % num).encode(): self.bodies[u]} for u in uids if u in self.bodies}


class Fill(unittest.TestCase):
    def setUp(self):
        snippets.CACHE = snippets._LRU(100)

    def test_one_fetch_per_part_number_then_the_cache(self):
        page = [{"uid": 1}, {"uid": 2}, {"uid": 3}, {"uid": 4}]
        leaves = {1: [leaf("1")], 2: [leaf("1")], 3: [leaf("1.1")], 4: []}
        conn = FakeConn({1: b"one", 2: b"two", 3: b"three"})
        self.assertEqual(snippets.fill(conn, page, leaves, ("box", "INBOX", 7)), 2)
        self.assertEqual([p.get("snippet") for p in page], ["one", "two", "three", ""])
        again = [{"uid": 1}, {"uid": 3}, {"uid": 4}]
        self.assertEqual(snippets.fill(conn, again, leaves, ("box", "INBOX", 7)), 0)
        self.assertEqual([p["snippet"] for p in again], ["one", "three", ""])
        # …and the request is a PEEK: listing never marks a message read
        self.assertTrue(all(b"BODY.PEEK[" in item for _, item in conn.calls))

    def test_another_uidvalidity_is_not_the_same_message(self):
        conn = FakeConn({1: b"new"})
        snippets.CACHE.put(("box", "INBOX", 7, 1), "old")
        page = [{"uid": 1}]
        snippets.fill(conn, page, {1: [leaf("1")]}, ("box", "INBOX", 8))
        self.assertEqual(page[0]["snippet"], "new")

    def test_a_failed_fetch_leaves_the_page_without_previews(self):
        class Broken(FakeConn):
            def fetch(self, uids, items):
                raise OSError("connection reset")
        page = [{"uid": 1}]
        self.assertEqual(snippets.fill(Broken({}), page, {1: [leaf("1")]}, ("b", "INBOX", 1)), 0)
        self.assertNotIn("snippet", page[0])

    def test_an_html_only_message_is_read_further(self):
        page = [{"uid": 1}, {"uid": 2}]
        leaves = {1: [leaf("1")], 2: [leaf("1", "html")]}
        conn = FakeConn({1: b"plain", 2: b"<p>html</p>"})
        self.assertEqual(snippets.fill(conn, page, leaves, ("b", "INBOX", 1)), 2)
        self.assertEqual(sorted(item for _, item in conn.calls),
                         [b"BODY.PEEK[1]<0.4096>", b"BODY.PEEK[1]<0.640>"])
        self.assertEqual([p["snippet"] for p in page], ["plain", "html"])

    def test_online_is_not_a_quote_header(self):
        self.assertEqual(snippets.clean("Online meeting tomorrow\nsee you\nDani wrote:\n> x"),
                         "Online meeting tomorrow see you")

    def test_groups_capped(self):
        page = [{"uid": u} for u in range(1, 6)]
        leaves = {u: [leaf("%d" % u)] for u in range(1, 6)}             # five different part numbers
        conn = FakeConn({u: b"x" for u in range(1, 6)})
        self.assertEqual(snippets.fill(conn, page, leaves, ("b", "INBOX", 1)), snippets.MAX_GROUPS)


if __name__ == "__main__":
    unittest.main()
