#!/usr/bin/env python3
"""test_line — the client document line builds every shape from data and refuses data that cannot make one (DGO-1454).

    python3 apps/my-docs/line/test_line.py

Stdlib only, no renderer needed: what is asserted is the page `line.build()` writes, and `line.main()`'s exit codes.
"""
import copy
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import line  # noqa: E402

with open(os.path.join(HERE, "example.json"), encoding="utf-8") as _f:
    EXAMPLE = json.load(_f)


def doc(**changes):
    d = copy.deepcopy(EXAMPLE)
    for k, v in changes.items():
        if v is None:
            d.pop(k, None)
        else:
            d[k] = v
    return d


def style_of(page: str) -> str:
    return page.split("<style>", 1)[1].split("</style>", 1)[0]


class Shapes(unittest.TestCase):
    def test_quote_and_agreement(self):
        page = line.build(doc())
        for want in ('class="cover"', "מה אנחנו מציעים", "הסכם שירות", "6,000 ₪", '<bdi dir="ltr">−3,000</bdi> ₪',
                     "3,000 ₪", "8 בנובמבר 2026", "בתוקף 30 יום", '<span class="blank"></span>',
                     '<span class="blank w"></span>', "<b>«הלקוח»</b>", "Noto Sans Hebrew", "Noto Serif Hebrew"):
            self.assertIn(want, page)
        self.assertEqual(page.count('<section class="section'), 2)

    def test_quote_only(self):
        page = line.build(doc(agreement=None, cover=None))
        self.assertIn("מה אנחנו מציעים", page)
        self.assertNotIn('<table class="parties">', page)       # the title still says «הסכם שירות»: the PAGE is gone
        self.assertNotIn('<ol class="clauses">', page)
        self.assertNotIn('class="cover"', page)
        self.assertIn('<section class="section first">', page)   # no cover: the first page breaks nothing
        self.assertIn("ההצעה בתוקף 30 יום מיום 8 בנובמבר 2026.", page)   # no cover to say it

    def test_validity_said_once_with_a_cover(self):
        self.assertNotIn("ההצעה בתוקף 30 יום מיום", line.build(doc()))

    def test_agreement_only(self):
        page = line.build(doc(offer=None, cover=None))
        self.assertIn("הסכם שירות", page)
        self.assertNotIn('<table class="price">', page)

    def test_total_without_advance(self):
        d = doc()
        del d["offer"]["price"]["advance"]
        page = line.build(d)
        self.assertIn('<tr class="total"><td>סה״כ</td>', page)
        self.assertNotIn("−", page.split("<body>")[1])

    def test_several_items_say_the_total_before_the_advance(self):
        d = doc()
        d["offer"]["price"]["items"] = [{"text": "א", "qty": 1, "unit": 2000}, {"text": "ב", "qty": 1, "unit": 4000}]
        page = line.build(d)
        rows = re.findall(r'<tr class="(sum|paid|total)"><td>[^<]*</td><td class="n"></td><td class="n"></td>'
                          r'<td class="n">(.*?)</td></tr>', page)
        self.assertEqual([r[0] for r in rows], ["sum", "paid", "total"])
        self.assertIn("6,000 ₪", rows[0][1])

    def test_quantities_never_in_exponent_form(self):
        d = doc()
        d["offer"]["price"]["items"] = [{"text": "א", "qty": 1500000, "unit": 1}, {"text": "ב", "qty": 2.5, "unit": 10}]
        d["offer"]["price"]["advance"]["amount"] = 1
        page = line.build(d)
        self.assertIn('<td class="n">1,500,000</td>', page)
        self.assertIn('<td class="n">2.5</td>', page)
        self.assertNotIn("e+06", page)

    def test_text_is_text(self):
        d = doc()
        d["offer"]["lead"] = '<script>alert(1)</script> & "x"'
        page = line.build(d)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_header_cannot_leave_the_style_element(self):
        # the second reader of DGO-1454: «</style><script>» in a title or a name became a live script
        for field in ("title", "seller", "customer"):
            d = doc()
            evil = "x</STYLE ><script>alert(1)</script><style>"
            if field == "title":
                d["title"] = evil
            else:
                d[field]["name"] = evil
                d[field].pop("short", None)
            page = line.build(d)
            self.assertEqual(page.lower().count("</style"), 1, field)
            self.assertNotIn("<script", page.lower(), field)

    def test_header_stays_one_css_string(self):
        d = doc(title='a "q" \\ b\r\nc\fd')
        css = style_of(line.build(d))
        head = re.search(r'@top-right \{ content: "((?:[^"\\]|\\.)*)";', css)
        self.assertIsNotNone(head)
        self.assertNotRegex(head.group(1), r"[\r\n\f]")
        self.assertIn("\\22 q\\22 ", head.group(1))
        self.assertIn("\\5c ", head.group(1))

    def test_header_and_title_are_plain_text(self):
        d = doc()
        d["customer"]["short"] = "{__} **חברה**"
        page = line.build(d)
        self.assertIn('content: "הצעת מחיר והסכם שירות · ______ חברה"', page)
        title = page.split("<title>", 1)[1].split("</title>", 1)[0]
        self.assertNotIn("<", title)

    def test_only_palette_values(self):
        with open(os.path.join(HERE, "..", "..", "..", "platform-base", "bina-ui", "theme-tokens.css"), encoding="utf-8") as f:
            palette = set(x.lower() for x in re.findall(r"#[0-9a-fA-F]{3,8}\b", f.read()))
        used = set(x.lower() for x in re.findall(r"#[0-9a-fA-F]{3,8}\b", line.build(doc())))
        self.assertTrue(used, "the page names its colours")
        self.assertEqual(used - palette, set(), "a colour that is not Olive Grove's own value")


class Refusals(unittest.TestCase):
    def refused(self, d, part):
        with self.assertRaises(line.Refused) as e:
            line.build(d)
        self.assertIn(part, str(e.exception))

    def test_unknown_field(self):
        self.refused(doc(costumer={"name": "x"}), "unknown fields ['costumer']")

    def test_unknown_inner_field(self):
        d = doc()
        d["offer"]["prices"] = d["offer"]["price"]
        self.refused(d, "document.offer: unknown fields ['prices']")

    def test_missing_customer_name(self):
        self.refused(doc(customer={"short": "x"}), "customer.name: missing")

    def test_neither_offer_nor_agreement(self):
        self.refused(doc(offer=None, agreement=None), "an offer (a quote), an agreement, or both")

    def test_bad_date(self):
        self.refused(doc(date="8.11.2026"), "date: YYYY-MM-DD")

    def test_advance_above_total(self):
        d = doc()
        d["offer"]["price"]["advance"]["amount"] = 7000
        self.refused(d, "at most the total (6,000)")

    def test_quantity_not_a_number(self):
        d = doc()
        d["offer"]["price"]["items"][0]["qty"] = "20"
        self.refused(d, "offer.price.items[0].qty: a number")

    def test_infinite_quantity(self):
        d = doc()
        d["offer"]["price"]["items"][0]["qty"] = float("inf")
        self.refused(d, "offer.price.items[0].qty: a number")

    def test_zero_quantity(self):
        d = doc()
        d["offer"]["price"]["items"][0]["qty"] = 0
        self.refused(d, "a quantity above 0")

    def test_clause_without_text(self):
        d = doc()
        d["agreement"]["clauses"][0]["text"] = " "
        self.refused(d, "agreement.clauses[0].text: a text")

    def test_wrong_kinds(self):
        # the second reader's list: each crashed with a traceback (exit 1, «no renderer») instead of a refusal
        def at(path, value):
            d = doc()
            node = d
            for k in path[:-1]:
                node = node[k]
            node[path[-1]] = value
            return d
        for path, value, part in [
            (("offer", "price", "advance"), 3000, "offer.price.advance: an object"),
            (("cover",), True, "document.cover: an object"),
            (("offer", "sign_off"), "שלמה", "offer.sign_off: an object"),
            (("offer", "steps"), ["a", "b"], "offer.steps: an object"),
            (("offer", "steps", "items"), "מאשרים", "offer.steps.items: a list"),
            (("agreement", "parties"), ["x"], "agreement.parties[0]: an object"),
            (("agreement", "signatures", 0, "fields"), "תאריך", "signatures[0].fields: a list"),
            (("valid_days",), [30], "valid_days: a whole number"),
        ]:
            with self.subTest(path=path):
                self.refused(at(path, value), part)


class Command(unittest.TestCase):
    def run_main(self, args):
        return line.main(args)

    def test_html_only_writes_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "x.pdf")
            self.assertEqual(self.run_main([os.path.join(HERE, "example.json"), out, "--html"]), 0)
            self.assertTrue(os.path.getsize(os.path.join(tmp, "x.html")) > 1000)
            self.assertFalse(os.path.exists(out))

    def test_a_folder_as_the_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_main([os.path.join(HERE, "example.json"), tmp + os.sep, "--html"]), 0)
            self.assertTrue(os.path.exists(os.path.join(tmp, "example.html")))

    def test_refused_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.json")
            with open(bad, "w", encoding="utf-8") as f:
                json.dump(doc(offer=None, agreement=None), f)
            self.assertEqual(self.run_main([bad, os.path.join(tmp, "x.pdf")]), 2)
            self.assertEqual(os.listdir(tmp), ["bad.json"])

    def test_wrong_kind_is_a_refusal_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.json")
            d = doc()
            d["offer"]["price"]["advance"] = 3000
            with open(bad, "w", encoding="utf-8") as f:
                json.dump(d, f)
            self.assertEqual(self.run_main([bad, os.path.join(tmp, "x.pdf")]), 2)

    def test_unknown_option_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                self.assertEqual(self.run_main([os.path.join(HERE, "example.json"), "--drvie=/x/"]), 2)
                self.assertEqual(self.run_main([os.path.join(HERE, "example.json"), "--drive"]), 2)
            finally:
                os.chdir(cwd)
            self.assertEqual(os.listdir(tmp), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
