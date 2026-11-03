"""The panel scripts of the InterNIC write (DGO-1032) run in a REAL browser, on pages shaped as the live
panel was measured — the fake panel of test_portal_write.py answers by matching a script's text, so the
scripts' own rules never ran in a test (the third reader). Needs Playwright with its Chromium; skipped
without it.

    python3 apps/domains/test_portal_js.py
"""
import json
import os
import sys
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import portal  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ImportError:                                    # pragma: no cover
    sync_playwright = None

DASHBOARD = """<table><thead><tr><th></th><th>דומיין</th><th>חידוש אוטומטי</th></tr></thead><tbody>
<tr><td><input type=checkbox class=sel {sel_a}></td><td>office.co.il</td><td><input type=checkbox class=renew checked></td></tr>
<tr><td><input type=checkbox class=sel></td><td>digital-office.co.il</td><td><input type=checkbox class=renew></td></tr>
<tr><td><input type=checkbox class=sel></td><td>bina-solutions.co.il</td><td><input type=checkbox class=renew checked></td></tr>
</tbody></table><button class="zone-edit visually-hidden" onclick="window.opened=1">zone</button>"""

#: two records and a TXT whose value is a <textarea>; the type select carries `selected` as served
ZONE = """<table>
<tr><td><input name="name_0" value="digital-office.co.il."></td><td><input name="ttl_0" value="86400"></td>
    <td><select name="rectype_0"><option>A</option><option selected>CNAME</option></select></td>
    <td><input name="specs_0" value="93.184.216.5"></td></tr>
<tr><td><input name="name_3" value="digital-office.co.il."></td><td><input name="ttl_3" value="3600"></td>
    <td><select name="rectype_3"><option>A</option><option selected>TXT</option></select></td>
    <td><textarea name="specs_3">"v=spf1 a -all"</textarea></td></tr>
<tr><td><input></td><td><input></td><td><select><option>A</option></select></td><td><input></td></tr>
</table>"""

SWAL = """<div class="swal2-container"><button class="swal2-close" style="display:none"
  onclick="window.answer='close'">x</button><h2 class="swal2-title">האם לשמור את השינויים?</h2>
  <div class="swal2-html-container">3 רשומות</div>
  <button class="swal2-confirm" onclick="window.answer='confirm'">כן</button>
  <button class="swal2-cancel" onclick="window.answer='cancel'">לא</button></div>"""


def page_with(body):
    return f"<!doctype html><html><head><meta charset=utf-8></head><body>{body}</body></html>"


def dtr_child(column, title, data, drawn=2):
    """A DataTables Responsive child row as its default renderer draws it: one cell across the columns still
    drawn, each hidden column in an <li> marked with its column index."""
    return (f"<tr class=child><td class=child colspan={drawn}><ul data-dtr-index=0 class=dtr-details>"
            f"<li data-dtr-index={column} data-dt-row=0 data-dt-column={column}><span class=dtr-title>{title}</span> "
            f"<span class=dtr-data>{data}</span></li></ul></td></tr>")


class Served(SimpleHTTPRequestHandler):
    """The editor's own address, as `_JS_SERVER_ZONE` fetches it again."""
    def do_GET(self):
        body = page_with(ZONE).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
class PanelScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Served)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)

    def run_js(self, fn, spec=None):
        src = f"({fn})({json.dumps(spec, ensure_ascii=False)})" if spec is not None else f"({fn})()"
        return json.loads(self.page.evaluate(src))

    def test_the_opener_ticks_only_its_own_row_and_touches_no_switch(self):
        self.page.set_content(page_with(DASHBOARD.format(sel_a="")))
        got = self.run_js(portal._JS_OPEN_ZONE, {"domain": "digital-office.co.il"})
        self.assertEqual(got, {"found": True, "zone": True})
        state = self.page.evaluate("Array.from(document.querySelectorAll('input')).map(i => i.checked)")
        # [office sel, office renew, digital sel, digital renew, bina sel, bina renew]
        self.assertEqual(state, [False, True, True, False, False, True],
                         "only digital-office.co.il's selection box changes; every renew switch is as it was")

    def test_the_opener_opens_nothing_when_another_domain_is_selected(self):
        self.page.set_content(page_with(DASHBOARD.format(sel_a="checked")))
        got = self.run_js(portal._JS_OPEN_ZONE, {"domain": "digital-office.co.il"})
        self.assertEqual(got.get("others_selected"), 1)
        self.assertFalse(self.page.evaluate("!!window.opened"))
        self.assertEqual(self.page.evaluate("Array.from(document.querySelectorAll('input')).map(i => i.checked)"),
                         [True, True, False, False, False, True], "nothing was clicked")

    def test_the_opener_never_takes_a_name_that_only_contains_the_domain(self):
        self.page.set_content(page_with(DASHBOARD.format(sel_a="")))
        got = self.run_js(portal._JS_OPEN_ZONE, {"domain": "office.co.il"})
        self.assertEqual(got, {"found": True, "zone": True})
        self.assertTrue(self.page.evaluate("document.querySelectorAll('input.sel')[0].checked"))
        self.assertFalse(self.page.evaluate("document.querySelectorAll('input.sel')[1].checked"))

    def test_the_opener_counts_only_its_own_tables_selection_column(self):
        """The fourth reader: a hidden copy of our own row, a hidden bulk dialog with ticked rows, and a
        renew switch that is ON in another row each made every read and write refuse."""
        extra = ("<table style='display:none'><tbody><tr><td><input type=checkbox checked></td>"
                 "<td>digital-office.co.il</td></tr><tr><td><input type=checkbox checked></td>"
                 "<td>bina-solutions.co.il</td></tr></tbody></table>")
        self.page.set_content(page_with(extra + DASHBOARD.format(sel_a="")))
        got = self.run_js(portal._JS_OPEN_ZONE, {"domain": "digital-office.co.il"})
        self.assertEqual(got, {"found": True, "zone": True})
        self.assertTrue(self.page.evaluate("document.querySelectorAll('input.sel')[1].checked"),
                        "the VISIBLE row's own box was ticked")

    def test_a_table_kept_hidden_while_it_renders_still_counts_another_domains_tick(self):
        """The fifth reader: hidden rows were left out of the count, so with the whole table hidden two
        domains ended up ticked and the zone button was pressed."""
        hidden = DASHBOARD.format(sel_a="checked").replace("<table>", "<table style='display:none'>", 1)
        self.page.set_content(page_with(hidden))
        got = self.run_js(portal._JS_OPEN_ZONE, {"domain": "digital-office.co.il"})
        self.assertEqual(got.get("others_selected"), 1, got)
        self.assertFalse(self.page.evaluate("!!window.opened"))

    def test_a_column_is_counted_across_colspans(self):
        """…a cell index is not a column: with a spanning cell the renew switch stood where the selection
        box was looked for, and another domain's auto-renew read as "selected"."""
        # the reader's S6: select-all in the header's 3rd column, each name cell spanning icon + name
        page = ("<table><thead><tr><th></th><th>דומיין</th><th><input type=checkbox class=all></th><th>חידוש</th>"
                "</tr></thead><tbody><tr><td colspan=2>office.co.il</td><td><input type=checkbox class=sel></td>"
                "<td><input type=checkbox class=renew checked></td></tr><tr><td colspan=2>digital-office.co.il</td>"
                "<td><input type=checkbox class=sel></td><td><input type=checkbox class=renew></td></tr></tbody>"
                "</table><button class='zone-edit' onclick='window.opened=1'>zone</button>")
        self.page.set_content(page_with(page))
        got = self.run_js(portal._JS_OPEN_ZONE, {"domain": "digital-office.co.il"})
        self.assertEqual(got, {"found": True, "zone": True}, "another domain's auto-renew read as selected")
        state = self.page.evaluate("Array.from(document.querySelectorAll('tbody input')).map(i => i.checked)")
        self.assertEqual(state, [False, True, True, False], "our selection box ticked; every renew as it was")

    def test_a_row_with_no_selection_box_is_never_clicked(self):
        """…its auto-renew switch, the only box in the row, was clicked: a money setting."""
        page = ("<table><thead><tr><th><input type=checkbox class=all></th><th>דומיין</th><th>חידוש</th></tr>"
                "</thead><tbody><tr><td></td><td>digital-office.co.il</td><td><input type=checkbox class=renew>"
                "</td></tr></tbody></table><button class='zone-edit' onclick='window.opened=1'>zone</button>")
        self.page.set_content(page_with(page))
        got = self.run_js(portal._JS_OPEN_ZONE, {"domain": "digital-office.co.il"})
        self.assertTrue(got.get("no_selection"), got)
        self.assertFalse(self.page.evaluate("document.querySelector('input.renew').checked"))
        self.assertFalse(self.page.evaluate("!!window.opened"))

    def test_a_first_box_under_a_settings_header_is_never_clicked(self):
        page = ("<table><thead><tr><th>חידוש אוטומטי</th><th>דומיין</th></tr></thead><tbody>"
                "<tr><td><input type=checkbox class=renew></td><td>digital-office.co.il</td></tr></tbody></table>"
                "<button class='zone-edit' onclick='window.opened=1'>zone</button>")
        self.page.set_content(page_with(page))
        got = self.run_js(portal._JS_OPEN_ZONE, {"domain": "digital-office.co.il"})
        self.assertTrue(got.get("no_selection"), got)
        self.assertFalse(self.page.evaluate("document.querySelector('input.renew').checked"))

    # ── the sixth reader (round six's code): a column is a GRID, and a setting says so anywhere ─────────
    def open_on(self, table, domain="digital-office.co.il"):
        """The opener on `table` + the zone button: (its answer, whether the zone was pressed, the classes
        of the boxes it ticked)."""
        self.page.set_content(page_with(table + "<button class='zone-edit' onclick='window.opened=1'>zone</button>"))
        self.page.evaluate("window.opened = 0")                  # the window outlives set_content
        before = self.page.evaluate("Array.from(document.querySelectorAll('input')).map(i => i.checked)")
        got = self.run_js(portal._JS_OPEN_ZONE, {"domain": domain})
        after = self.page.evaluate("Array.from(document.querySelectorAll('input')).map(i => i.checked)")
        classes = self.page.evaluate("Array.from(document.querySelectorAll('input')).map(i => i.className)")
        ticked = [c for c, b, a in zip(classes, before, after) if b != a]
        return got, bool(self.page.evaluate("!!window.opened")), ticked

    def assertRefused(self, table, why):
        got, opened, ticked = self.open_on(table)
        # refused by name, or (round ten) the row is not in a domain list at all: either way nothing is clicked
        self.assertTrue(got.get("no_selection") or got.get("others_selected") or got.get("found") is False,
                        (why, got))
        self.assertEqual((opened, ticked), (False, []), why)

    def test_a_settings_header_in_any_header_row_refuses(self):
        """R1: the names in the FIRST header row, a filter row LAST: the last row's empty cell was read,
        and the auto-renew switch ticked."""
        self.assertRefused(
            "<table><thead><tr><th>דומיין</th><th>חידוש אוטומטי</th><th>בחירה</th></tr>"
            "<tr><td><input type=search></td><td></td><td></td></tr></thead><tbody>"
            "<tr><td>digital-office.co.il</td><td><input type=checkbox class=x1></td>"
            "<td><input type=checkbox class=x2></td></tr></tbody></table>", "a filter row last")

    def test_a_header_that_spans_down_holds_its_column(self):
        """R2 and R2b: a grouped header (rowspan) shifted the last row's cells — the renew switch was
        clicked under a header looked up at the wrong column, and a true selection column was refused."""
        self.assertRefused(
            "<table><thead><tr><th rowspan=2>דומיין</th><th colspan=2>הגדרות</th></tr>"
            "<tr><th>חידוש אוטומטי</th><th>בחירה</th></tr></thead><tbody>"
            "<tr><td>digital-office.co.il</td><td><input type=checkbox class=x1></td>"
            "<td><input type=checkbox class=x2></td></tr></tbody></table>", "renew under a grouped header")
        got, opened, ticked = self.open_on(
            "<table><thead><tr><th rowspan=2>בחר</th><th rowspan=2>דומיין</th><th colspan=2>הגדרות</th></tr>"
            "<tr><th>חידוש אוטומטי</th><th>נעול</th></tr></thead><tbody>"
            "<tr><td><input type=checkbox class=sel></td><td>office.co.il</td><td><input type=checkbox class=x1>"
            "</td><td><input type=checkbox class=x2></td></tr>"
            "<tr><td><input type=checkbox class=sel></td><td>digital-office.co.il</td><td><input type=checkbox "
            "class=x1></td><td><input type=checkbox class=x2></td></tr></tbody></table>")
        self.assertEqual((got, opened, ticked), ({"found": True, "zone": True}, True, ["sel"]))

    def test_a_cell_that_spans_down_the_body_holds_its_column(self):
        """R3, R3b, R3c: a group cell spanning two domains' rows hid the other's tick, and read a renew
        switch's header at the wrong column."""
        for ours_first in (False, True):
            other = "<td><input type=checkbox class=sel checked></td><td>office.co.il</td>"
            ours = "<td><input type=checkbox class=sel></td><td>digital-office.co.il</td>"
            first, second = (ours, other) if ours_first else (other, ours)
            self.assertRefused(
                "<table><thead><tr><th>בעלים</th><th>בחר</th><th>דומיין</th></tr></thead><tbody>"
                f"<tr><td rowspan=2>BINA</td>{first}</tr><tr>{second}</tr></tbody></table>",
                f"another domain ticked in a group (ours first: {ours_first})")
        self.assertRefused(
            "<table><thead><tr><th>בעלים</th><th>חידוש אוטומטי</th><th>דומיין</th></tr></thead><tbody>"
            "<tr><td rowspan=2>BINA</td><td><input type=checkbox class=x1></td><td>office.co.il</td></tr>"
            "<tr><td><input type=checkbox class=x1></td><td>digital-office.co.il</td></tr></tbody></table>",
            "renew in a group's second row")

    def test_a_setting_says_so_by_its_header_row_its_title_or_its_own_name(self):
        """R5, R6, R4: a header row of <th> in the body, an icon header named only by its title, and a
        one-domain account whose only box is the renew switch with no header at all."""
        self.assertRefused("<table><tbody><tr><th>חידוש אוטומטי</th><th>דומיין</th></tr>"
                           "<tr><td><input type=checkbox class=x1></td><td>digital-office.co.il</td></tr>"
                           "</tbody></table>", "a header row in the body")
        self.assertRefused("<table><thead><tr><th title='חידוש אוטומטי'>&#x21bb;</th><th>דומיין</th></tr></thead>"
                           "<tbody><tr><td><input type=checkbox class=x1></td><td>digital-office.co.il</td></tr>"
                           "</tbody></table>", "an icon header")
        # round eight: under the measured empty header, so that the box's OWN name is what refuses (a table
        # with no header at all refuses since round eight whatever the box says)
        for box in ("class=autoRenewToggle", "name=auto_renew", "id=domain-lock", "aria-label='Auto renew'",
                    "id=r1><label for=r1>חידוש אוטומטי</label"):
            self.assertRefused(f"<table><thead><tr><th></th><th>דומיין</th></tr></thead><tbody><tr><td><input "
                               f"type=checkbox {box}></td><td>digital-office.co.il</td></tr></tbody></table>", box)

    def test_a_selection_box_with_an_ordinary_name_still_opens(self):
        """…and no word that only CONTAINS a setting refuses: Bootstrap's `d-block` holds "lock"."""
        got, opened, ticked = self.open_on(
            "<table><thead><tr><th></th><th>דומיין</th></tr></thead><tbody><tr><td><input type=checkbox "
            "class='form-check-input d-block' name='domains[]' id=select-1></td><td>digital-office.co.il</td>"
            "</tr></tbody></table>")
        self.assertEqual((got, opened, ticked), ({"found": True, "zone": True}, True, ["form-check-input d-block"]))

    # ── the seventh reader (round seven's code) ────────────────────────────────────────────────────────
    @staticmethod
    def dash(sel="form-check-input", ours="digital-office.co.il", other="office.co.il", sel_extra="",
             head="<thead><tr><th></th><th>דומיין</th><th>חידוש אוטומטי</th></tr></thead>", foot=""):
        """The panel's dashboard as the readers drew it: our row second, another domain's renew ON."""
        def box(cls, on=False, extra=""):
            return f"<input type=checkbox class='{cls}' {'checked' if on else ''} {extra}>"
        return (f"<table>{head}<tbody>"
                f"<tr><td>{box('sel ' + sel, extra=sel_extra.replace('@', other))}</td><td>{other}</td>"
                f"<td>{box('form-check-input renew', True)}</td></tr>"
                f"<tr><td>{box('sel ' + sel, extra=sel_extra.replace('@', ours))}</td><td>{ours}</td>"
                f"<td>{box('form-check-input renew')}</td></tr></tbody>{foot}</table>")

    def test_an_ordinary_selection_box_is_never_refused(self):
        """F1–F7, F10, H1, H2: each of these refused every read — a centred box (`mx-auto` is no auto-renew),
        its own domain in its label, a toolbar or a bulk menu in the header, a summary in the foot, hidden
        text in the select-all cell, a header that says "Block"."""
        menu = ("<thead><tr><th><input type=checkbox class=all><ul style='display:none'><li>חידוש המסומנים</li>"
                "</ul></th><th>דומיין</th><th>חידוש אוטומטי</th></tr></thead>")
        pages = {
            "mx-auto d-block": self.dash("form-check-input mx-auto d-block"),
            "m-auto": self.dash("form-check-input m-auto"),
            "pe-auto": self.dash("form-check-input pe-auto"),
            "Tailwind mx-auto": self.dash("mx-auto block"),
            "its own domain in its label": self.dash(ours="autoparts.co.il", sel_extra="aria-label='בחר את @'"),
            "a toolbar row": self.dash(head="<thead><tr><th colspan=3><button type=button>חידוש</button>"
                                            "<button type=button>עריכת DNS</button></th></tr><tr><th></th>"
                                            "<th>דומיין</th><th>חידוש אוטומטי</th></tr></thead>"),
            "a bulk select": self.dash(head="<thead><tr><th><input type=checkbox class=all><select><option>פעולות"
                                            "</option><option>חידוש</option></select></th><th>דומיין</th>"
                                            "<th>חידוש אוטומטי</th></tr></thead>"),
            "a summary in the foot": self.dash(foot="<tfoot><tr><th colspan=3>2 דומיינים · 1 בחידוש אוטומטי</th>"
                                                    "</tr></tfoot>"),
            "a hidden menu": self.dash(head=menu),
            "a hidden menu, the table hidden": self.dash(head=menu).replace("<table>", "<table style='display:none'>", 1),
            # round ten: "Select all / Auto" beside the box refuses (the ninth reader: any word passed there);
            # a select-all box's own hidden "Select all" is what a selection column says
            "hidden select-all text": ("<table><thead><tr><th><input type=checkbox class=all><span class=visually-hidden"
                                       " style='display:none'>Select all</span></th><th>דומיין</th></tr></thead><tbody>"
                                       "<tr><td><input type=checkbox class=sel></td><td>digital-office.co.il</td></tr>"
                                       "</tbody></table>"),
            "a closed bulk menu in the select-all cell": self.dash(
                head="<thead><tr><th><input type=checkbox class=all><details><summary>פעולות</summary><a href=#>"
                     "חידוש</a></details></th><th>דומיין</th><th>חידוש אוטומטי</th></tr></thead>"),
            "a toolbar of links, a wider row in the body": self.dash(
                head="<thead><tr><th colspan=3><a class=btn href=#>חידוש</a></th></tr><tr><th></th><th>דומיין</th>"
                     "<th>חידוש אוטומטי</th></tr></thead>").replace(
                "</tbody>", "<tr style='display:none'><td colspan=100>details</td></tr></tbody>"),
        }
        for why, table in pages.items():
            got, opened, ticked = self.open_on(table, "autoparts.co.il" if "autoparts" in table
                                               else "digital-office.co.il")
            self.assertEqual((got, opened), ({"found": True, "zone": True}, True), why)
            self.assertEqual(len(ticked), 1, why)
            self.assertIn("sel", ticked[0], why)

    def test_a_span_ends_with_its_row_group(self):
        """E1, E2, E2c, E3: a header's rowspan (or rowspan=0, "to the end of the GROUP") carried into the
        body put a renew switch under "בחירה", or another domain's tick out of the count — clicked, or two
        domains ticked."""
        switch = "<input type=checkbox class=x{on}>"          # no name of its own: the column alone decides
        pages = {
            "a thead rowspan over our renew switch": (
                "<table><thead><tr><th rowspan=2>דומיין</th><th>חידוש אוטומטי</th><th>בחירה</th></tr></thead><tbody>"
                f"<tr><td>digital-office.co.il</td><td>{switch.format(on='')}</td><td><input type=checkbox class=sel>"
                f"</td></tr><tr><td>office.co.il</td><td>{switch.format(on=' checked')}</td><td><input "
                "type=checkbox class=sel></td></tr></tbody></table>"),
            "rowspan=0 in the thead": (
                "<table><thead><tr><th rowspan=0>דומיין</th><th>חידוש אוטומטי</th><th>בחירה</th></tr></thead>"
                "<tbody><tr><td>office.co.il</td><td><input type=checkbox class=x></td><td><input type=checkbox "
                "class=sel></td></tr><tr><td>digital-office.co.il</td><td><input type=checkbox class=x></td><td>"
                "<input type=checkbox class=sel></td></tr></tbody></table>"),
            "a select-all rowspan=2, another domain ticked": (
                "<table><thead><tr><th rowspan=2><input type=checkbox class=all></th><th>דומיין</th><th>חידוש "
                "אוטומטי</th></tr></thead><tbody><tr><td><input type=checkbox class=sel checked></td><td>"
                "office.co.il</td><td><input type=checkbox class=x></td></tr><tr><td><input type=checkbox "
                "class=sel></td><td>digital-office.co.il</td><td><input type=checkbox class=x></td></tr></tbody>"
                "</table>"),
            "a group cell longer than its tbody, another domain ticked in the next": (
                "<table><thead><tr><th>בעלים</th><th>בחר</th><th>דומיין</th></tr></thead><tbody><tr><td "
                "rowspan=3>BINA</td><td><input type=checkbox class=sel></td><td>digital-office.co.il</td></tr><tr>"
                "<td><input type=checkbox class=sel></td><td>bina-solutions.co.il</td></tr></tbody><tbody><tr><td>"
                "OTHER</td><td><input type=checkbox class=sel checked></td><td>office.co.il</td></tr></tbody></table>"),
        }
        for why, table in pages.items():
            self.assertRefused(table, why)

    def test_a_header_names_its_column_through_its_icon_and_a_switch_is_a_setting(self):
        """E4–E6, E8: an icon's title, an image's alt, a span's aria-label inside the th — and a Bootstrap
        switch with no header at all — each had the renew switch clicked."""
        body = "</thead><tbody><tr><td><input type=checkbox class=x></td><td>digital-office.co.il</td></tr></tbody></table>"
        for why, th in (("an icon's title", "<i class='bi bi-arrow-repeat' title='חידוש אוטומטי'></i>"),
                        ("an image's alt", "<img alt='חידוש אוטומטי' src='data:,'>"),
                        ("a span's aria-label", "<span aria-label='Auto-renew'>&#x21bb;</span>")):
            self.assertRefused(f"<table><thead><tr><th>{th}</th><th>דומיין</th></tr>{body}", why)
        # under the measured empty header, so that the switch itself is what refuses (round eight)
        for why, box in (("a Bootstrap switch", "<div class='form-check form-switch'><input type=checkbox "
                                                "class=form-check-input></div>"),
                         ("role=switch", "<input type=checkbox role=switch>"),
                         ("an older kit's switch", "<div class='custom-control custom-switch'><input "
                                                   "type=checkbox class=custom-control-input></div>"),
                         ("a label.switch", "<label class=switch><input type=checkbox><span></span></label>")):
            self.assertRefused(f"<table><thead><tr><th></th><th>דומיין</th></tr></thead><tbody><tr><td>{box}</td>"
                               "<td>digital-office.co.il</td></tr></tbody></table>", why)

    # ── the eighth reader (round eight's code): a selection column is known, never guessed ─────────────
    def test_only_a_column_known_to_be_a_selection_column_is_ticked(self):
        """Every one of these clicked the renew box past a list of setting words: a sortable header whose
        name is a button, text hidden at the office browser's width, a `hidden` header cell, a header of
        just "Auto", a title as wide as the header over the renew column, Hebrew words outside the list, a
        header row of <td> — and an i18n key in the box's label."""
        def page(th, box="<input type=checkbox class=x>", head_row=None):
            head = head_row or f"<tr><th>{th}</th><th>דומיין</th></tr>"
            return (f"<table><thead>{head}</thead><tbody><tr><td>{box}</td><td>digital-office.co.il</td>"
                    "</tr></tbody></table>")
        pages = {
            "a sortable header": page("<button type=button>חידוש אוטומטי</button>"),
            "text hidden at this width": page("<span class=d-none style='display:none'>חידוש אוטומטי</span><i></i>"),
            "Auto": page("Auto"),
            "Block": page("Block"),
            "מתחדש אוטומטית": page("מתחדש אוטומטית"),
            "הארכה אוטומטית": page("הארכה אוטומטית"),
            "a hidden header cell": page("", head_row="<tr><th hidden>חידוש אוטומטי</th><th hidden>דומיין</th></tr>"),
            # round ten: the ninth reader's own page — the title over every column, an empty <th> under it
            "a title over every column": ("<table><thead><tr><th colspan=3>חידוש אוטומטי</th></tr><tr><th></th>"
                                          "<th>דומיין</th><th>תוקף</th></tr></thead><tbody><tr><td><input "
                                          "type=checkbox class=x></td><td>digital-office.co.il</td><td>2027</td>"
                                          "</tr></tbody></table>"),
            "a header row of <td>": ("<table><tr><td><b>חידוש אוטומטי</b></td><td><b>דומיין</b></td></tr><tr><td>"
                                     "<input type=checkbox class=x></td><td>digital-office.co.il</td></tr></table>"),
            "an i18n key in the box's label": page("", box="<input type=checkbox aria-label='domain.autoRenew'>"),
            "no header at all": ("<table><tbody><tr><td><input type=checkbox class=sel></td><td>digital-office.co.il"
                                 "</td></tr></tbody></table>"),
        }
        for why, table in pages.items():
            self.assertRefused(table, why)
        # …and a domain whose own name holds a setting word is no setting
        got, opened, ticked = self.open_on(
            "<table><thead><tr><th></th><th>דומיין</th></tr></thead><tbody><tr><td><input type=checkbox "
            "id=select-lock-shop.co.il></td><td>lock-shop.co.il</td></tr></tbody></table>", "lock-shop.co.il")
        self.assertEqual((got, opened), ({"found": True, "zone": True}, True))

    def test_a_rowspan_to_the_end_of_a_body_group_holds_its_column(self):
        """B1/B2: rowspan=0 in a body group — and in the first of two, with another domain ticked in the
        next: read as one row, the group cell shifted the columns of the rows below it."""
        head = "<thead><tr><th>בעלים</th><th></th><th>דומיין</th></tr></thead>"
        # ours second in the group: its box stands under the empty header only if the group cell holds col 0
        got, opened, ticked = self.open_on(
            f"<table>{head}<tbody><tr><td rowspan=0>BINA</td><td><input type=checkbox class=sel></td>"
            "<td>office.co.il</td></tr><tr><td><input type=checkbox class=sel></td><td>digital-office.co.il</td>"
            "</tr></tbody></table>")
        self.assertEqual((got, opened, ticked), ({"found": True, "zone": True}, True, ["sel"]))
        # …and the span ends with its group: another domain ticked in the next one is counted
        self.assertRefused(
            f"<table>{head}<tbody><tr><td rowspan=0>BINA</td><td><input type=checkbox class=sel></td>"
            "<td>digital-office.co.il</td></tr></tbody><tbody><tr><td>OTHER</td><td><input type=checkbox class=sel "
            "checked></td><td>office.co.il</td></tr></tbody></table>", "a tick in the next group")

    # ── the ninth reader (round nine's code) ───────────────────────────────────────────────────────────
    def test_the_row_is_taken_from_the_domain_list_never_a_card_before_it(self):
        """D1: an auto-renew card placed before the list, its table [empty | שם] — its toggle was ticked by
        document order."""
        card = ("<div class=card><h5>חידוש אוטומטי</h5><table><thead><tr><th></th><th>שם</th></tr></thead><tbody>"
                "<tr><td><input type=checkbox class=toggle></td><td>digital-office.co.il</td></tr></tbody></table></div>")
        got, opened, ticked = self.open_on(card + self.dash())
        self.assertEqual((got, opened, ticked), ({"found": True, "zone": True}, True, ["sel form-check-input"]))

    def test_a_header_is_read_whole_and_a_select_all_cell_says_only_select(self):
        """A header named by its own list or <details>, a glyph, a kit's title attribute, a button input, a
        filter — each read as empty and clicked the renew box; beside a select-all box any word passed."""
        def page(th):
            return (f"<table><thead><tr><th>{th}</th><th>דומיין</th></tr></thead><tbody><tr><td><input "
                    "type=checkbox class=x></td><td>digital-office.co.il</td></tr></tbody></table>")
        for why, th in (("a <details>", "<details><summary>חידוש אוטומטי</summary>…</details>"),
                        ("a list", "<ul><li>חידוש אוטומטי</li></ul>"),
                        ("a glyph", "&#x27F3;"),
                        ("Bootstrap 4's tooltip title", "<span data-original-title='חידוש אוטומטי' title=''>i</span>"),
                        ("tippy", "<span data-tippy-content='Auto renew'></span>"),
                        ("a button input", "<input type=button value='חידוש אוטומטי'>"),
                        ("a filter", "<select><option>חידוש אוטומטי</option></select>"),
                        ("a placeholder", "<input placeholder='חידוש'>"),
                        ("Auto beside a select-all box", "<input type=checkbox class=all> Auto"),
                        ("«אוטומטי» beside a select-all box", "<input type=checkbox class=all> אוטומטי"),
                        ("a renew-all box named by its title", "<input type=checkbox title='Renew all'>")):
            self.assertRefused(page(th), why)

    def test_a_sortable_empty_header_still_opens_and_a_refusal_says_what_it_read(self):
        """C1: DataTables writes ": activate to sort column ascending" on every sortable header — the measured
        empty one too, which refused every read. And a refusal answers with the header it read."""
        got, opened, ticked = self.open_on(self.dash(
            head="<thead><tr><th aria-label=': activate to sort column ascending'></th><th>דומיין</th>"
                 "<th>חידוש אוטומטי</th></tr></thead>"))
        self.assertEqual((got, opened), ({"found": True, "zone": True}, True))
        got, _, _ = self.open_on(self.dash(head="<thead><tr><th>Auto</th><th>דומיין</th><th>חידוש אוטומטי</th>"
                                                "</tr></thead>"))
        self.assertEqual(got.get("header"), ["Auto"])

    # ── the tenth reader (round ten's code) ───────────────────────────────────────────────────────────
    def test_a_visible_card_naming_domains_while_the_list_is_hidden_is_refused(self):
        """P1: the list hidden while it renders, a visible auto-renew card whose table also names «דומיין» —
        the card's row was the only visible one, and its toggle was ticked."""
        card = ("<div class=card><table><thead><tr><th></th><th>דומיין</th></tr></thead><tbody><tr><td><input "
                "type=checkbox class=toggle></td><td>digital-office.co.il</td></tr></tbody></table></div>")
        hidden = self.dash().replace("<table>", "<table style='display:none'>", 1)
        self.assertRefused(card + hidden, "two domain lists")

    def test_each_name_is_judged_on_its_own(self):
        """R1: DataTables copies a header's title into its aria-label — «בחר הכל בחר הכל» read whole was no
        "select", and a labelled select-all refused every read. And the select-all words a panel uses."""
        for why, th in (("DataTables' copy of the title", "<th aria-label=' בחר הכל'><input type=checkbox class=all> בחר הכל</th>"),
                        ("orderable", "<th aria-label='Select all: activate to sort column ascending'><input "
                                      "type=checkbox class=all> Select all</th>"),
                        ("DataTables Select's box", "<th><input type=checkbox class=all aria-label='Select all rows'></th>"),
                        ("«הכל»", "<th><input type=checkbox class=all> הכל</th>"),
                        ("«בחירת הכל»", "<th><input type=checkbox class=all> בחירת הכל</th>"),
                        ("a script inside", "<th><input type=checkbox class=all><script>var renewAll = 1;</script></th>")):
            got, opened, _ = self.open_on(self.dash(head=f"<thead><tr>{th}<th>דומיין</th><th>חידוש אוטומטי</th>"
                                                         "</tr></thead>"))
            self.assertEqual((got, opened), ({"found": True, "zone": True}, True), why)

    def test_every_name_of_the_box_and_the_header_is_read(self):
        """P2, P3, P5, A5: a box titled by Bootstrap 4 (`data-original-title`) or tippy; a title on a wide
        cell's child; a second, renew-all box in the select-all cell; a header named only by Bootstrap 4."""
        def page(th, box="<input type=checkbox class=x>"):
            return (f"<table><thead><tr><th>{th}</th><th>דומיין</th></tr></thead><tbody><tr><td>{box}</td>"
                    "<td>digital-office.co.il</td></tr></tbody></table>")
        self.assertRefused(page("", "<input type=checkbox title='' data-original-title='חידוש אוטומטי'>"), "BS4 box")
        self.assertRefused(page("", "<input type=checkbox data-tippy-content='Auto renew'>"), "tippy box")
        self.assertRefused(page("", "<input type=checkbox aria-labelledby=l1><span id=l1>חידוש אוטומטי</span>"),
                           "aria-labelledby")
        self.assertRefused(page("<span title='' data-original-title='חידוש אוטומטי'></span>"), "a BS4 header")
        self.assertRefused(page("<input type=checkbox class=all><input type=checkbox title='Renew all'>"),
                           "a renew-all box beside the select-all")
        self.assertRefused("<table><thead><tr><th colspan=3><span title='חידוש אוטומטי'>&#x27F3;</span></th></tr>"
                           "<tr><th></th><th>דומיין</th><th>תוקף</th></tr></thead><tbody><tr><td><input "
                           "type=checkbox class=x></td><td>digital-office.co.il</td><td>2027</td></tr></tbody></table>",
                           "a title on a wide cell's child")

    def test_any_other_ticked_row_is_counted_whatever_its_name_cell_holds(self):
        """B1: another domain's name cell with a badge in it was not a name — its tick was not counted."""
        page = ("<table><thead><tr><th></th><th>דומיין</th></tr></thead><tbody>"
                "<tr><td><input type=checkbox class=sel checked></td><td>office.co.il <b>VIP</b></td></tr>"
                "<tr><td><input type=checkbox class=sel></td><td>digital-office.co.il</td></tr></tbody></table>")
        got, opened, ticked = self.open_on(page)
        self.assertTrue(got.get("others_selected"), got)
        self.assertEqual((opened, ticked), (False, []))

    def test_a_list_with_no_header_over_the_box_is_refused(self):
        """The rule a column with no header cell is not known to be a selection one (round nine), held again:
        the pages that held it now leave the list (round ten), so this one is a list with no header row."""
        self.assertRefused("<table><tbody><tr><th>דומיין</th><td></td></tr><tr><td><input type=checkbox "
                           "class=sel></td><td>digital-office.co.il</td></tr></tbody></table>", "no header row")

    # ── the eleventh reader (round eleven's code) ─────────────────────────────────────────────────────
    def test_a_glyph_in_a_name_is_no_empty_header(self):
        """A header named only by a glyph in a NAME — a title '↻', an icon's aria-label '🔁', an image's alt
        '⟳' — was dropped as empty, and the renew box under it ticked."""
        for why, th in (("a title", "<th title='&#x21BB;'></th>"), ("an aria-label", "<th><i aria-label='&#x1F501;'></i></th>"),
                        ("an alt", "<th><img alt='&#x27F3;' src='data:,'></th>")):
            self.assertRefused(f"<table><thead><tr>{th}<th>דומיין</th></tr></thead><tbody><tr><td><input "
                               "type=checkbox class=x></td><td>digital-office.co.il</td></tr></tbody></table>", why)

    def test_wide_rows_and_boxless_copies_never_refuse_the_measured_layout(self):
        """O2, O1b: a hidden details row across every column holding a ticked switch, and a phone copy of the
        list with no boxes — each refused every first read, so the memory never formed."""
        details = "<tr class=collapse style='display:none'><td colspan=3><input type=checkbox checked> פרטיות</td></tr>"
        phone = ("<table style='display:none'><thead><tr><th>דומיין</th></tr></thead><tbody><tr><td>"
                 "digital-office.co.il</td></tr></tbody></table>")
        for why, page in (("a details row", self.dash().replace("</tbody>", details + "</tbody>")),
                          ("a phone copy with no boxes", phone + self.dash())):
            got, opened, ticked = self.open_on(page)
            self.assertEqual((got, opened), ({"found": True, "zone": True}, True), why)

    def test_the_box_cell_and_every_name_reference_are_read(self):
        """S1, S5: the box's own cell saying «חידוש אוטומטי», a header named through aria-labelledby; and the
        names no test held: a box's value, its aria-label whole, the new words, a select-all box named only
        by a kit's title, a wide cell's aria-label; and a bare «הכל» with no box."""
        def page(th, box="<input type=checkbox class=x>"):
            return (f"<table><thead><tr>{th}<th>דומיין</th></tr></thead><tbody><tr><td>{box}</td>"
                    "<td>digital-office.co.il</td></tr></tbody></table>")
        for why, table in (
                ("the box's cell", page("<th></th>", "<input type=checkbox class=x> חידוש אוטומטי")),
                ("a lock beside the box", page("<th></th>", "<input type=checkbox class=x><i title='נעילת דומיין'></i>")),
                ("aria-labelledby", page("<th aria-labelledby=h1></th>") + "<span id=h1 hidden>חידוש אוטומטי</span>"),
                ("the box's value", page("<th></th>", "<input type=checkbox value=autorenew>")),
                ("the box's aria-label whole", page("<th></th>", "<input type=checkbox aria-label='Select: auto renew'>")),
                ("«יחודש»", page("<th></th>", "<input type=checkbox title='יחודש אוטומטית'>")),
                ("auto-extend", page("<th></th>", "<input type=checkbox aria-label='Auto-extend'>")),
                ("a select-all box named by a kit's title", page("<th><input type=checkbox class=all "
                                                                 "data-original-title='Renew all'></th>")),
                ("a bare «הכל»", page("<th>הכל</th>"))):
            self.assertRefused(table, why)
        self.assertRefused("<table><thead><tr><th colspan=2 aria-label='Auto renew'></th></tr><tr><th></th>"
                           "<th>דומיין</th></tr></thead><tbody><tr><td><input type=checkbox class=x></td>"
                           "<td>digital-office.co.il</td></tr></tbody></table>", "a wide cell's aria-label")

    # ── the twelfth reader (round twelve's code) ──────────────────────────────────────────────────────
    def test_another_domains_tick_counts_whatever_its_colspan(self):
        """E1b, E1c: a ticked box in a cell whose colspan differs from ours was skipped — two domains ticked
        and the zone pressed. Only a cell across the WHOLE table, where ours is not, is no row's box."""
        head = "<thead><tr><th colspan=2></th><th>דומיין</th><th>תוקף</th></tr></thead>"
        for why, theirs, ours in (
                ("theirs spans two", "<td colspan=2><input type=checkbox class=sel checked></td>",
                 "<td><input type=checkbox class=sel></td><td></td>"),
                ("ours spans two", "<td><input type=checkbox class=sel checked></td><td></td>",
                 "<td colspan=2><input type=checkbox class=sel></td>")):
            self.assertRefused(f"<table>{head}<tbody><tr>{theirs}<td>office.co.il</td><td>2027</td></tr>"
                               f"<tr>{ours}<td>digital-office.co.il</td><td>2027</td></tr></tbody></table>", why)

    def test_a_drawn_card_with_a_box_beside_a_list_without_boxes_is_refused(self):
        """B1: ignoring rows without a box made a favourites card the one list when the list's own rows had
        none — its box was ticked. A copy that is DRAWN still counts as a second list."""
        card = ("<table><thead><tr><th></th><th>דומיין</th></tr></thead><tbody><tr><td><input type=checkbox "
                "class=fav></td><td>digital-office.co.il</td></tr></tbody></table>")
        boxless = ("<table><thead><tr><th>דומיין</th><th>תוקף</th></tr></thead><tbody><tr><td>digital-office.co.il"
                   "</td><td>2027</td></tr></tbody></table>")
        self.assertRefused(card + boxless, "two drawn lists")

    def test_a_responsive_child_row_is_no_rows_box(self):
        """The reader of 42f2fa71: DataTables Responsive hides columns with CSS (their cells stay), so a child
        row spans only the columns drawn, never the whole table — its moved switch read as another domain
        ticked, and the measured layout refused at the office browser's narrow width."""
        page = ("<table><thead><tr><th></th><th>דומיין</th><th style='display:none'>חידוש אוטומטי</th></tr></thead>"
                "<tbody><tr><td><input type=checkbox class=sel></td><td>office.co.il</td><td style='display:none'>"
                "</td></tr>" + dtr_child(2, "חידוש אוטומטי", "<input type=checkbox class=renew checked>")
                + "<tr><td><input type=checkbox class=sel></td>"
                "<td>digital-office.co.il</td><td style='display:none'><input type=checkbox class=renew></td></tr>"
                "</tbody></table>")
        got, opened, ticked = self.open_on(page)
        self.assertEqual((got, opened, ticked), ({"found": True, "zone": True}, True, ["sel"]))

    # ── the reader of 8c03fbcd ─────────────────────────────────────────────────────────────────────────
    def test_another_domains_tick_in_its_child_row_counts(self):
        """With the SELECTION column hidden, another domain's box lives only in its open child row (Responsive
        moves the hidden cells' nodes there): skipping that row ticked ours beside it."""
        page = ("<table><thead><tr><th style='display:none'></th><th>דומיין</th><th>חידוש אוטומטי</th></tr></thead>"
                "<tbody><tr><td style='display:none'></td><td>office.co.il</td><td>"
                "<input type=checkbox class=renew></td></tr>" + dtr_child(0, "", "<input type=checkbox class=sel checked>")
                + "<tr><td style='display:none'><input type=checkbox class=sel></td><td>digital-office.co.il</td>"
                "<td><input type=checkbox class=renew></td></tr></tbody></table>")
        got, opened, ticked = self.open_on(page)
        self.assertEqual((got.get("others_selected"), opened, ticked), (1, False, []), got)

    # ── the reader of 31d13e30 ─────────────────────────────────────────────────────────────────────────
    def test_a_child_row_is_read_whatever_column_ours_is(self):
        """The selection column LAST and hidden (Responsive hides from the right): the child row's one cell
        spans only the two columns drawn, so the grid's third column of it was empty and the row never asked."""
        page = ("<table><thead><tr><th>דומיין</th><th>תוקף</th><th style='display:none'></th></tr></thead>"
                "<tbody><tr><td>office.co.il</td><td>2027</td><td style='display:none'></td></tr>"
                + dtr_child(2, "", "<input type=checkbox class=sel checked>")
                + "<tr><td>digital-office.co.il</td><td>2027</td><td style='display:none'><input type=checkbox "
                "class=sel></td></tr></tbody></table>")
        got, opened, ticked = self.open_on(page)
        self.assertEqual((got.get("others_selected"), opened, ticked), (1, False, []), got)

    def test_a_child_rows_mark_is_not_the_pages_column(self):
        """A `visible:false` column (its cells never drawn) numbers DataTables' columns one past the page's:
        the other domain's moved tick is marked 1 while ours is the page's column 0."""
        page = ("<table><thead><tr><th style='display:none'></th><th>דומיין</th><th>חידוש אוטומטי</th></tr></thead>"
                "<tbody><tr><td style='display:none'></td><td>office.co.il</td><td><input type=checkbox class=renew>"
                "</td></tr>" + dtr_child(1, "", "<input type=checkbox class=sel checked>")
                + "<tr><td style='display:none'><input type=checkbox class=sel></td><td>digital-office.co.il</td>"
                "<td><input type=checkbox class=renew></td></tr></tbody></table>")
        got, opened, ticked = self.open_on(page)
        self.assertEqual((got.get("others_selected"), opened, ticked), (1, False, []), got)

    # ── the reader of 537f0bef ─────────────────────────────────────────────────────────────────────────
    def test_a_select_all_titles_bulk_menu_names_no_setting_of_its_part(self):
        """DataTables copies the header's HTML into the child row's title: a select-all header whose bulk menu
        offers «חידוש אוטומטי» read as a setting column, and another domain's moved tick went uncounted."""
        head = "<input type=checkbox class=all><select><option>פעולות</option><option>חידוש אוטומטי</option></select>"
        page = (f"<table><thead><tr><th style='display:none'>{head}</th><th>דומיין</th><th>תוקף</th></tr></thead>"
                "<tbody><tr><td style='display:none'></td><td>office.co.il</td><td>2027</td></tr>"
                + dtr_child(0, head.replace("class=all", "class=all2"), "<input type=checkbox class=sel checked>")
                + "<tr><td style='display:none'><input type=checkbox class=sel></td><td>digital-office.co.il</td>"
                "<td>2027</td></tr></tbody></table>")
        got, opened, ticked = self.open_on(page)
        self.assertEqual((got.get("others_selected"), opened, ticked), (1, False, []), got)

    def test_a_child_row_at_one_drawn_column_is_read(self):
        """At one drawn column the child row is no wider than our cell: its part for the hidden selection
        column (past column 0) was never read."""
        page = ("<table><thead><tr><th>דומיין</th><th style='display:none'></th><th style='display:none'>חידוש "
                "אוטומטי</th></tr></thead><tbody><tr><td>office.co.il</td><td style='display:none'></td><td "
                "style='display:none'></td></tr>" + dtr_child(1, "", "<input type=checkbox class=sel checked>", drawn=1)
                + "<tr><td>digital-office.co.il</td><td style='display:none'><input type=checkbox class=sel></td>"
                "<td style='display:none'><input type=checkbox class=renew></td></tr></tbody></table>")
        got, opened, ticked = self.open_on(page)
        self.assertEqual((got.get("others_selected"), opened, ticked), (1, False, []), got)

    # ── the reader of 3a819f41 ─────────────────────────────────────────────────────────────────────────
    def test_a_part_titled_as_our_header_is_ours_whatever_it_names(self):
        """The select-all header's title copied without its box (a box put in after DataTables read it), or as
        its text: «חידוש אוטומטי» in the bulk menu read as a setting column, and another domain's tick hid."""
        menu = "<select><option>פעולות</option><option>חידוש אוטומטי</option></select>"
        for title in (menu, "פעולותחידוש אוטומטי"):
            page = (f"<table><thead><tr><th style='display:none'><input type=checkbox class=all>{menu}</th>"
                    "<th>דומיין</th><th>תוקף</th></tr></thead><tbody><tr><td style='display:none'></td>"
                    "<td>office.co.il</td><td>2027</td></tr>"
                    + dtr_child(0, title, "<input type=checkbox class=sel checked>")
                    + "<tr><td style='display:none'><input type=checkbox class=sel></td><td>digital-office.co.il</td>"
                    "<td>2027</td></tr></tbody></table>")
            got, opened, ticked = self.open_on(page)
            self.assertEqual((got.get("others_selected"), opened, ticked), (1, False, []), (title, got))

    def test_a_ticked_box_outside_every_part_counts(self):
        """A narrow one-cell row at our column whose ticked box sits outside its column-marked parts: round
        sixteen read the cell's first box; round seventeen read only the parts."""
        page = ("<table><thead><tr><th></th><th style='display:none'>דומיין</th><th style='display:none'>חידוש "
                "אוטומטי</th></tr></thead><tbody><tr><td style='display:none'></td><td style='display:none'>"
                "office.co.il</td><td style='display:none'></td></tr><tr class=child><td class=child colspan=1>"
                "<input type=checkbox class=sel checked><ul class=dtr-details><li data-dt-column=2><span "
                "class=dtr-title>חידוש אוטומטי</span> <span class=dtr-data><input type=checkbox class=renew></span>"
                "</li></ul></td></tr><tr><td><input type=checkbox class=sel></td><td style='display:none'>"
                "digital-office.co.il</td><td style='display:none'><input type=checkbox class=renew></td></tr>"
                "</tbody></table>")
        got, opened, ticked = self.open_on(page)
        self.assertEqual((got.get("others_selected"), opened, ticked), (1, False, []), got)

    def test_a_wide_row_without_column_marks_counts_whole(self):
        """A one-cell row wider than ours that is no Responsive child (no column marks) is not known to hold
        only settings: its tick counts, and nothing is opened."""
        page = ("<table><thead><tr><th></th><th>דומיין</th><th style='display:none'>x</th></tr></thead>"
                "<tbody><tr><td><input type=checkbox class=sel></td><td>office.co.il</td><td style='display:none'>"
                "</td></tr><tr><td colspan=2><input type=checkbox class=sel checked></td></tr>"
                "<tr><td><input type=checkbox class=sel></td><td>digital-office.co.il</td><td style='display:none'>"
                "</td></tr></tbody></table>")
        got, opened, ticked = self.open_on(page)
        self.assertEqual((got.get("others_selected"), opened, ticked), (1, False, []), got)

    def test_a_txt_value_in_a_textarea_is_a_record(self):
        self.page.set_content(page_with(ZONE))
        rows = self.run_js(portal._JS_ZONE)["rows"]
        self.assertEqual([(r["type"], r["content"]) for r in rows],
                         [("CNAME", "93.184.216.5"), ("TXT", '"v=spf1 a -all"')])

    def test_the_guard_reads_the_served_page_as_the_editor_reads_itself(self):
        url = f"http://127.0.0.1:{self.server.server_address[1]}/zone/112859"
        self.page.goto(url)
        live = self.run_js(portal._JS_ZONE)["rows"]
        served = json.loads(self.page.evaluate(f"({portal._JS_SERVER_ZONE})()"))
        self.assertEqual(portal._zone_key(served["rows"], "digital-office.co.il"),
                         portal._zone_key(live, "digital-office.co.il"))

    def test_cancel_clicks_the_visible_button_never_the_hidden_close(self):
        self.page.set_content(page_with(SWAL))
        self.assertTrue(self.run_js(portal._JS_ANSWER, {"confirm": False})["found"])
        self.assertEqual(self.page.evaluate("window.answer"), "cancel")


if __name__ == "__main__":
    unittest.main()
