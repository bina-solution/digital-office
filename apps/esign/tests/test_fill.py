"""«מילוי וחתימה» (DGO-2139): one link for every party, over HTTP, end to end.

The document under test is drawn here the way a quote is printed: two signing blocks, each with the party's name
printed above it, lines, and the words under the lines («שם ותפקיד», «חתימה וחותמת», «תאריך» | «חתימה», «תאריך»),
and a heading «1 · חתימה» over a line that is NOT a place. Two browsers are two test clients (two cookie jars).
"""
import base64
import io
import json
import os
import re
import sys
import zlib

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fill as fill_mod  # noqa: E402
import fillpdf  # noqa: E402
import pdfsign  # noqa: E402
import server as server_mod  # noqa: E402
from test_http import Stub  # noqa: E402

CLIENT, OFFICE = "לקוח לדוגמה", "בינה סולושנס"


def quote_pdf() -> bytes:
    """A4 with the signing page of a quote: the client's block on the right, the office's on the left, lines drawn as
    a browser prints a border (a thin filled box), Hebrew stored in visual order (as a browser's PDF stores it)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    f = pdfsign._font()
    c.setFont(f, 18)
    c.drawRightString(540, 760, pdfsign.he("אישור ההצעה"))
    c.setFont(f, 9)
    # the step heading over a line: not a place
    c.rect(56, 200, 160, 1.4, stroke=0, fill=1)
    c.drawRightString(214, 186, pdfsign.he("1 · חתימה"))
    # the client's block (right)
    c.setFont(f, 12)
    c.drawRightString(520, 470, pdfsign.he(CLIENT))
    c.setFont(f, 9)
    c.drawRightString(520, 455, pdfsign.he("בשם הלקוח"))
    c.rect(330, 380, 190, 1.0, stroke=0, fill=1)
    c.drawRightString(520, 368, pdfsign.he("שם ותפקיד"))
    c.rect(330, 320, 190, 1.0, stroke=0, fill=1)
    c.drawRightString(520, 308, pdfsign.he("חתימה וחותמת"))
    c.drawString(332, 308, pdfsign.he("תאריך"))
    # the office's block (left)
    c.setFont(f, 12)
    c.drawRightString(255, 470, pdfsign.he(OFFICE))
    c.setFont(f, 9)
    c.drawRightString(255, 455, pdfsign.he("ישראל ישראלי"))
    c.rect(70, 380, 185, 1.0, stroke=0, fill=1)
    c.drawRightString(255, 368, pdfsign.he("חתימה"))
    c.drawString(72, 368, pdfsign.he("תאריך"))
    c.showPage()
    c.save()
    return buf.getvalue()


def png_ink() -> str:
    """A small hand-drawn mark as the pad sends it: a PNG with alpha, as a data URL."""
    w, h = 60, 20
    raw = b""
    for y in range(h):
        raw += b"\x00" + b"".join(b"\x10\x10\x10\xff" if abs(y - 10 - (x % 7 - 3)) < 2 else b"\x00\x00\x00\x00"
                                  for x in range(w))

    def chunk(t, d):
        return len(d).to_bytes(4, "big") + t + d + zlib.crc32(t + d).to_bytes(4, "big")
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", w.to_bytes(4, "big") + h.to_bytes(4, "big") + b"\x08\x06\x00\x00\x00")
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode()


@pytest.fixture()
def stub(monkeypatch):
    s = Stub()
    monkeypatch.setenv("DRIVE_URL", s.url)
    monkeypatch.setenv("NOTIFICATIONS_URL", s.url)
    monkeypatch.setenv("ESIGN_BASE_URL", "http://esign.test")
    monkeypatch.setenv("ESIGN_PUBLIC_URL", "https://sign.example.test")
    monkeypatch.delenv("ESIGN_DRIVE_FOLDER", raising=False)
    monkeypatch.setenv("ESIGN_RENDER_URL", "")
    monkeypatch.setenv("ESIGN_OFFICE_NAME", OFFICE)
    yield s
    s.stop()


@pytest.fixture()
def app(tmp_path, stub):
    a = server_mod.routes(server_mod.create_app(data_dir=str(tmp_path)))
    a.config["FILL_SYNC"] = True                 # the final copy is made inside the last signature's request
    return fill_mod.routes(a)


def prepare(cl) -> dict:
    r = cl.post("/api/events", data={"file": (io.BytesIO(quote_pdf()), "10001 — לקוח לדוגמה.pdf"), "title": "הצעת מחיר 10001",
                                     "ref": "doc_1", "days": "30", "hints": json.dumps([CLIENT, OFFICE])},
                content_type="multipart/form-data")
    assert r.status_code == 200, r.data
    return r.get_json()


def send(cl, ev, *, order="any", code=None, extra=()) -> str:
    parties = [dict(p) for p in ev["parties"]]
    if code:
        parties[0]["code"] = code
    fields = ev["fields"] + list(extra)
    r = cl.post("/api/events/%s/send" % ev["event"]["id"], json={"parties": parties, "fields": fields,
                                                                 "settings": {"order": order}})
    assert r.status_code == 200, r.data
    link = r.get_json()["link"]
    assert link.startswith("https://sign.example.test/s/")
    return link.rsplit("/", 1)[-1]


def boot(cl, token) -> dict:
    r = cl.get("/s/" + token)
    assert r.status_code == 200
    m = re.search(rb'<script type="application/json" id="fill-boot">(.*?)</script>', r.data, re.S)
    return json.loads(m.group(1))


def side(ev, label):
    return next(p for p in ev["parties"] if p["label"] == label)


def fields_of(ev, pid):
    return [f for f in ev["fields"] if f["party"] == pid]


# ── the document says where it is filled and signed ──────────────────────────────────────────────
def test_detect_reads_the_two_blocks_and_their_owners(tmp_path):
    p = tmp_path / "q.pdf"
    p.write_bytes(quote_pdf())
    found = fillpdf.detect(str(p), [CLIENT, OFFICE])
    labels = [x["label"] for x in found["parties"]]
    assert labels == [CLIENT, OFFICE]                          # each block's owner is the name printed over it
    assert [x["note"] for x in found["parties"]] == ["בשם הלקוח", "ישראל ישראלי"]   # …and the line under that name
    c, o = found["parties"]
    kinds = lambda pid: sorted(f["type"] for f in found["fields"] if f["party"] == pid)
    assert kinds(c["id"]) == ["date_signed", "name", "signature", "text"]
    assert kinds(o["id"]) == ["date_signed", "signature"]
    for f in found["fields"]:
        x, y, w, h = f["box"]
        assert 0 <= x and 0 <= y and x + w <= 1 and y + h <= 1 and w > 0 and h > 0
    sig = next(f for f in found["fields"] if f["party"] == c["id"] and f["type"] == "signature")
    assert sig["label"] == "חתימה וחותמת"                        # the document's own word
    # the place stands on its line: its bottom just above the line (y=321pt from the bottom of an 842pt page)
    assert abs((sig["box"][1] + sig["box"][3]) - (842 - 321) / 842) < 0.01
    assert sig["box"][0] > 0.5                                  # on the client's (right) block
    # «1 · חתימה» over a line is a heading, not a place
    assert not [f for f in found["fields"] if f["box"][1] > 0.7]


def house_pdf(kind: str) -> bytes:
    """The office's own documents as the house renderer prints them, every line the way a browser prints a
    border-bottom: the whole element as a box with the box above the line cut out of it, filled even-odd — the path's
    bounds are the element, its ink only the line.
      "accept": a quote's «אישור הלקוח», one row of four cells 17pt apart, a word under each (one side);
      "sigs":   an agreement's two signing areas side by side, the party printed above each and «חתימה וחותמת» and
                «תאריך» under it — here only 17pt apart, as close as one side's cells: a row that asks for a signature
                twice is still two sides.
    And a filled bar and a framed box, each with a word under it: neither is a line."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.pdfgen.canvas import FILL_EVEN_ODD
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    f = pdfsign._font()

    def underlined(x0, y0, w, h):                             # the element, minus all of it above its .7pt border
        p = c.beginPath()
        p.rect(x0, y0, w, h)
        p.rect(x0, y0 + 0.7, w, h - 0.7)
        c.drawPath(p, stroke=0, fill=1, fillMode=FILL_EVEN_ODD)
    c.setFont(f, 7.2)
    if kind == "accept":
        c.setFont(f, 10.6)
        c.drawRightString(535, 240, pdfsign.he("אישור הלקוח"))
        c.setFont(f, 7.2)
        for x0, word in ((429, "שם מלא"), (306, "תפקיד"), (183, "תאריך"), (60, "חתימה וחותמת")):
            underlined(x0, 173.4, 106, 18.7)
            c.drawRightString(x0 + 106, 161.5, pdfsign.he(word))
        # not places: a cover's «תאריך» under a rule with its date printed under it, and a certificate's row under a
        # rule whose sentence holds the word «החתימה»
        c.rect(62, 707, 470, 1, stroke=0, fill=1)
        c.drawRightString(385, 694, pdfsign.he("תאריך"))
        c.setFont(f, 9.6)
        c.drawRightString(385.5, 677, pdfsign.he("19 בנובמבר 2026"))
        c.setFont(f, 7.2)
        c.rect(45, 500, 505, 1, stroke=0, fill=1)
        c.drawRightString(443, 488, pdfsign.he("נשלח קישור החתימה"))
    elif kind == "sigs":
        for x0, party in ((306, OFFICE), (60, CLIENT)):
            c.setFont(f, 9.6)
            c.drawRightString(x0 + 229, 290, pdfsign.he(party))
            c.setFont(f, 7.4)
            underlined(x0, 200, 229, 48.2)
            c.drawRightString(x0 + 229, 188, pdfsign.he("חתימה וחותמת"))
            c.drawString(x0, 188, pdfsign.he("תאריך"))
    elif kind == "rows":
        # two parties' rows of cells stacked in the same columns, each party's name over its own row
        for top, party in ((430, OFFICE), (330, CLIENT)):
            c.setFont(f, 9.6)
            c.drawRightString(535, top + 30, pdfsign.he(party))
            c.setFont(f, 7.2)
            for x0, word in ((429, "שם מלא"), (306, "תפקיד"), (183, "תאריך"), (60, "חתימה וחותמת")):
                underlined(x0, top, 106, 18.7)
                c.drawRightString(x0 + 106, top - 12, pdfsign.he(word))
    elif kind == "table":
        # a ruled details table, each row's border-bottom printed as a browser prints it, a key and its value in it
        for i, (key, value) in enumerate((("שם מלא", "דנה לוי"), ("טלפון", "052-1234567"), ("כתובת", "רוטשילד 45"))):
            top = 400 - 20 * i
            underlined(60, top, 475, 20)
            c.drawRightString(535, top + 6, pdfsign.he(key))
            c.drawRightString(400, top + 6, pdfsign.he(value))
    elif kind == "stack":
        # an ordinary form: one party's lines 20pt apart, each word 10pt under its line in 9pt type; the role and the
        # address are both plain answers of that one party
        c.setFont(f, 9)
        for i, word in enumerate(("שם מלא", "ת.ז.", "תפקיד", "כתובת", "טלפון", "תאריך", "חתימה")):
            c.rect(300, 500 - 20 * i, 220, 0.8, stroke=0, fill=1)
            c.drawRightString(520, 490 - 20 * i, pdfsign.he(word))
    elif kind == "printed":
        # a name already printed on a «שם וחתימה» line; a company's name printed between a line and «חתימה וחותמת»;
        # an ID number printed under «תאריך»
        c.setFont(f, 9)
        c.rect(330, 700, 190, 0.8, stroke=0, fill=1)
        c.drawRightString(500, 704, pdfsign.he("דנה לוי"))
        c.drawRightString(520, 690, pdfsign.he("שם וחתימה"))
        c.rect(70, 700, 185, 0.8, stroke=0, fill=1)
        c.drawRightString(255, 690, pdfsign.he("לקוח לדוגמה בע״מ"))
        c.drawRightString(255, 678, pdfsign.he("חתימה וחותמת"))
        c.rect(330, 400, 190, 0.8, stroke=0, fill=1)
        c.drawRightString(520, 390, pdfsign.he("תאריך"))
        c.drawRightString(520, 378, pdfsign.he("ת.ז. 320134567"))
        c.rect(70, 500, 185, 0.8, stroke=0, fill=1)                # a plain «חתימה» line, its signer's name printed on it
        c.drawRightString(255, 504, pdfsign.he("ישראל ישראלי"))
        c.drawRightString(255, 490, pdfsign.he("חתימה"))
        c.rect(70, 300, 185, 0.8, stroke=0, fill=1)                # a name at one end of the line, a date at the other
        c.drawRightString(255, 304, pdfsign.he("ישראל ישראלי"))
        c.drawString(70, 304, "20.11.2026")
        c.drawRightString(255, 290, pdfsign.he("חתימת הלקוח"))
    elif kind == "column":
        # two parties stacked in one column, each «שם מלא / טלפון / חתימה» on lines 20pt apart, its name above it
        c.setFont(f, 9)
        for top, party in ((560, OFFICE), (460, CLIENT)):
            c.drawRightString(520, top + 18, pdfsign.he(party))
            for i, word in enumerate(("שם מלא", "טלפון", "חתימה")):
                c.rect(300, top - 20 * i, 220, 0.8, stroke=0, fill=1)
                c.drawRightString(520, top - 10 - 20 * i, pdfsign.he(word))
    elif kind == "above":
        # words printed just ABOVE their own lines, 24pt apart: each is also under the line above it — not that line's
        c.setFont(f, 9)
        for i, word in enumerate(("שם מלא", "תפקיד", "חתימה")):
            c.rect(300, 500 - 24 * i, 220, 0.8, stroke=0, fill=1)
            c.drawRightString(520, 504 - 24 * i, pdfsign.he(word))
    elif kind in ("columns", "columns2"):
        # two parties' columns side by side 17pt apart, each «שם מלא / טלפון / חתימה» on lines 20pt apart under its name
        # ("columns2": the phone first — a row of two phones is two sides, round 9)
        c.setFont(f, 9)
        words = ("שם מלא", "טלפון", "חתימה") if kind == "columns" else ("טלפון", "שם מלא", "חתימה")
        for x0, x1, party in ((300, 520, OFFICE), (60, 283, CLIENT)):
            c.drawRightString(x1, 578, pdfsign.he(party))
            for i, word in enumerate(words):
                c.rect(x0, 560 - 20 * i, x1 - x0, 0.8, stroke=0, fill=1)
                c.drawRightString(x1, 550 - 20 * i, pdfsign.he(word))
    elif kind == "inputs":
        # a printed web form: each word 9pt over its own tall input (28pt, a bottom border only — a label's margin in
        # print, round 9); the next word close under the input above it, so it is within reach of that border too
        c.setFont(f, 9)
        for i, word in enumerate(("שם מלא", "תפקיד", "חתימה")):
            top = 640 - 47 * i
            c.drawRightString(520, top + 9, pdfsign.he(word))
            underlined(300, top - 28, 220, 28)
    elif kind == "blanktable":
        # an empty ruled table: 20pt rows under a top rule, each key centred in its row, its value cell blank
        c.setFont(f, 9)
        c.rect(60, 420, 475, 0.8, stroke=0, fill=1)
        for i, key in enumerate(("שם מלא", "כתובת", "טלפון")):
            c.rect(60, 400 - 20 * i, 475, 0.8, stroke=0, fill=1)
            c.drawRightString(535, 407 - 20 * i, pdfsign.he(key))
    elif kind == "receiver":
        # a delivery note's receiver: «שם וחתימה» and «תאריך» under one signing area
        underlined(60, 300, 229, 48.2)
        c.drawRightString(289, 288, pdfsign.he("שם וחתימה"))
        c.drawString(60, 288, pdfsign.he("תאריך"))
    elif kind == "contract":
        # a contract's last lines: «חתימת הלקוח» and the business's «חתימה», each with its number printed under it
        for x0, x1, word, number in ((330, 520, "חתימת הלקוח", "ח.פ. 515550001"), (70, 255, "חתימה", "ע.מ. 300000015")):
            c.rect(x0, 300, x1 - x0, 1.0, stroke=0, fill=1)
            c.drawRightString(x1, 288, pdfsign.he(word))
            c.drawRightString(x1, 277, pdfsign.he(number))
    c.rect(60, 600, 200, 18, stroke=0, fill=1)                # a filled bar
    c.drawRightString(260, 588, pdfsign.he("חתימה"))
    p = c.beginPath()                                         # a frame: a box with a box cut out at every side
    p.rect(330, 600, 200, 18)
    p.rect(331, 601, 198, 16)
    c.drawPath(p, stroke=0, fill=1, fillMode=FILL_EVEN_ODD)
    c.drawRightString(530, 588, pdfsign.he("שם מלא"))
    c.showPage()
    c.save()
    return buf.getvalue()


def test_detect_reads_the_offices_own_documents(tmp_path):
    p = tmp_path / "accept.pdf"
    p.write_bytes(house_pdf("accept"))
    found = fillpdf.detect(str(p), [CLIENT, OFFICE])
    assert [x["label"] for x in found["parties"]] == [CLIENT]          # one row of cells is one side: the customer
    assert sorted(f["type"] for f in found["fields"]) == ["date_signed", "name", "signature", "text"]
    for f in found["fields"]:                                          # each on its cell's line, none on the bar/frame
        assert abs((f["box"][1] + f["box"][3]) - (842 - 173.75) / 842) < 0.01
    sig = next(f for f in found["fields"] if f["type"] == "signature")
    assert sig["label"] == "חתימה וחותמת" and sig["box"][0] < 0.2

    p = tmp_path / "sigs.pdf"
    p.write_bytes(house_pdf("sigs"))
    found = fillpdf.detect(str(p), [CLIENT, OFFICE])
    by = {x["label"]: x["id"] for x in found["parties"]}
    assert sorted(by) == sorted([CLIENT, OFFICE])                     # two signatures in a row are two sides
    for label, right in ((OFFICE, True), (CLIENT, False)):
        mine = [f for f in found["fields"] if f["party"] == by[label]]
        assert sorted(f["type"] for f in mine) == ["date_signed", "signature"]
        assert all((f["box"][0] > 0.36) == right for f in mine)        # each side's places in its own box
        assert all(abs((f["box"][1] + f["box"][3]) - (842 - 200.35) / 842) < 0.01 for f in mine)


def test_detect_tells_stacked_rows_ruled_tables_and_contract_lines_apart(tmp_path):
    """The second reader, round 5: two parties' rows stacked in the same columns gave the second's signature to the
    first; a ruled table's rows became places over printed text; «חתימת הלקוח», and a «חתימה» with the party's number
    printed under it, were not found."""
    def found(kind):
        p = tmp_path / (kind + ".pdf")
        p.write_bytes(house_pdf(kind))
        return fillpdf.detect(str(p), [CLIENT, OFFICE])
    got = found("rows")
    by = {x["label"]: x["id"] for x in got["parties"]}
    assert sorted(by) == sorted([CLIENT, OFFICE])                       # each row is its own party's, signature too
    for label, line in ((OFFICE, 430.35), (CLIENT, 330.35)):
        mine = [f for f in got["fields"] if f["party"] == by[label]]
        assert sorted(f["type"] for f in mine) == ["date_signed", "name", "signature", "text"]
        assert all(abs((f["box"][1] + f["box"][3]) - (842 - line) / 842) < 0.01 for f in mine)
    assert found("table")["fields"] == []                               # a key under a written row is no place
    got = found("contract")
    assert sorted((f["type"], f["label"], f["box"][0] > 0.5) for f in got["fields"]) == [
        ("signature", "חתימה", False), ("signature", "חתימת הלקוח", True)]
    got = {f["type"]: f["box"] for f in found("receiver")["fields"]}   # «שם וחתימה»: who, and the hand — the wider
    assert sorted(got) == ["date_signed", "name", "signature"] and got["signature"][2] > got["name"][2]


def test_detect_keeps_ordinary_forms_whole(tmp_path):
    """The second reader, round 6: a form's lines 20pt apart lost every answer after the first (the label above sat
    in the next line's written-on band); one party asking a role and an address split in two; «שם וחתימה» on a line
    with the name already printed lost its signature too; a company's name between a line and «חתימה וחותמת» hid the
    signature; an ID number under «תאריך» read as a date."""
    def found(kind):
        p = tmp_path / (kind + ".pdf")
        p.write_bytes(house_pdf(kind))
        return fillpdf.detect(str(p), [CLIENT, OFFICE])
    got = found("stack")
    assert [x["label"] for x in got["parties"]] == [CLIENT]
    assert sorted(f["type"] for f in got["fields"]) == ["date_signed", "id_number", "name", "phone", "signature", "text",
                                                        "text"]
    got = found("printed")
    assert sorted((f["type"], f["label"]) for f in got["fields"]) == [
        ("date_signed", "תאריך"), ("signature", "חתימה"), ("signature", "חתימה וחותמת"), ("signature", "חתימת הלקוח"),
        ("signature", "שם וחתימה")]
    hand = next(f for f in got["fields"] if f["label"] == "שם וחתימה")
    assert hand["box"][0] + hand["box"][2] < 460 / 595                 # the hand keeps its own side, off the name
    from reportlab.pdfbase import pdfmetrics
    printed = 255 - pdfmetrics.stringWidth(pdfsign.he("ישראל ישראלי"), pdfsign._font(), 9)   # the name's left edge
    hand = next(f for f in got["fields"] if f["label"] == "חתימה")
    assert (hand["box"][0] + hand["box"][2]) * 595.28 < printed         # …and beside a name printed on a plain line
    assert hand["box"][2] * 595.28 > 100                               # with the rest of the line to sign on
    dated = 70 + pdfmetrics.stringWidth("20.11.2026", pdfsign._font(), 9)    # the date's right edge
    hand = next(f for f in got["fields"] if f["label"] == "חתימת הלקוח")
    assert hand["box"][0] * 595.28 > dated and (hand["box"][0] + hand["box"][2]) * 595.28 < printed   # between them


def test_detect_misses_rather_than_misplaces(tmp_path):
    """The second reader, round 7: two parties stacked in one column — the lower one's phone went to the upper party;
    words printed just above their own lines put each answer on the field above. A place on the wrong line is worse
    than none: the office adds a missing place in the editor, a wrong one may go out."""
    def found(kind):
        p = tmp_path / (kind + ".pdf")
        p.write_bytes(house_pdf(kind))
        return fillpdf.detect(str(p), [CLIENT, OFFICE])
    got = found("column")
    by = {x["label"]: x["id"] for x in got["parties"]}
    assert sorted(by) == sorted([CLIENT, OFFICE])
    for label, lines in ((OFFICE, (560.4, 540.4, 520.4)), (CLIENT, (460.4, 440.4, 420.4))):
        mine = sorted((f for f in got["fields"] if f["party"] == by[label]), key=lambda f: f["box"][1])
        assert [f["type"] for f in mine] == ["name", "phone", "signature"]
        assert all(abs((f["box"][1] + f["box"][3]) - (842 - y) / 842) < 0.01 for f, y in zip(mine, lines))
    assert found("above")["fields"] == []
    # round 8: two parties' columns 17pt apart stay two sides, each in its own column
    got = found("columns")
    by = {x["label"]: x["id"] for x in got["parties"]}
    assert sorted(by) == sorted([CLIENT, OFFICE])
    for label, right in ((OFFICE, True), (CLIENT, False)):
        mine = [f for f in got["fields"] if f["party"] == by[label]]
        assert sorted(f["type"] for f in mine) == ["name", "phone", "signature"]
        assert all((f["box"][0] > 290 / 595) == right for f in mine)
    # …and so do two columns whose first row is two phones (round 9)
    got = found("columns2")
    by = {x["label"]: x["id"] for x in got["parties"]}
    assert sorted(by) == sorted([CLIENT, OFFICE])
    for label, right in ((OFFICE, True), (CLIENT, False)):
        mine = [f for f in got["fields"] if f["party"] == by[label]]
        assert sorted(f["type"] for f in mine) == ["name", "phone", "signature"]
        assert all((f["box"][0] > 290 / 595) == right for f in mine)
    # …a printed web form's tall inputs, and an empty ruled table, give no place rather than the field above
    assert found("inputs")["fields"] == []
    assert found("blanktable")["fields"] == []


# ── one link, two sides, end to end ──────────────────────────────────────────────────────────────
def test_two_sides_sign_on_one_link_and_the_copy_is_sealed(app, stub):
    office = app.test_client()
    ev = prepare(office)
    token = send(office, ev)
    client, bina = app.test_client(), app.test_client()
    b = boot(client, token)
    assert b["office"]["name"] == OFFICE and [p["state"] for p in b["parties"]] == ["waiting", "waiting"]
    c = side(b, CLIENT)
    # the client takes its side, answers wrong, then right, and signs
    r = client.post("/s/%s/f/claim" % token, json={"party": c["id"]})
    assert r.status_code == 200 and r.get_json()["ok"]
    name = next(f for f in fields_of(b, c["id"]) if f["type"] == "name")
    role = next(f for f in fields_of(b, c["id"]) if f["type"] == "text")
    r = client.post("/s/%s/f/answers" % token, json={"party": c["id"], "values": {name["id"]: "ד"}})
    assert r.get_json()["errors"][name["id"]] == "כתבו שם מלא"
    r = client.post("/s/%s/f/sign" % token, json={"party": c["id"], "consent": True,
                                                  "values": {name["id"]: "דנה כהן", role["id"]: "מנכ״לית"},
                                                  "signature": {"kind": "draw", "image": png_ink()}})
    assert r.status_code == 200, r.data
    st = r.get_json()
    assert side(st, CLIENT)["state"] == "signed" and side(st, CLIENT)["signer"] == "דנה כהן"
    assert st["event"]["status"] == "open"
    # the office hears of this signature at once, not only when the last side signs
    notes = [json.loads(c_[3]) for c_ in stub.calls if c_[0] == "POST" and c_[1].endswith("/api/notifications")]
    assert any("דנה כהן" in n["title"] and "1 מתוך 2" in n["body"] for n in notes)
    # the office's side, from another browser, on the SAME link: it sees the client's signature in place
    b2 = boot(bina, token)
    assert side(b2, CLIENT)["state"] == "signed"
    placed = {f["id"]: f for f in b2["fields"]}
    assert placed[name["id"]]["value"] == "דנה כהן"
    assert placed[next(f for f in fields_of(b, c["id"]) if f["type"] == "signature")["id"]]["image"].endswith("/f/sig/" + c["id"])
    o = side(b2, OFFICE)
    assert bina.post("/s/%s/f/claim" % token, json={"party": o["id"]}).status_code == 200
    r = bina.post("/s/%s/f/sign" % token, json={"party": o["id"], "consent": True,
                                                "signature": {"kind": "type", "image": png_ink(), "text": "ישראל ישראלי"}})
    assert r.status_code == 200, r.data
    assert r.get_json()["event"]["status"] == "complete" and r.get_json()["event"]["final_ready"]
    # the final copy: the values are in the page, the certificate is appended, the seal holds
    r = client.get("/s/%s/f/final" % token)
    assert r.status_code == 200 and r.data.startswith(b"%PDF")
    path = str(app.config["DATA_DIR"]) + "/final.pdf"
    with open(path, "wb") as fh:
        fh.write(r.data)
    checks = pdfsign.verify(path)
    assert checks["signed"] and checks["intact"]
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(path)
    try:
        assert len(doc) == 2                                    # the page and the certificate
        text = doc[0].get_textpage().get_text_range()
        assert "דנה כהן" in text or "ןהכ הנד" in text or pdfsign.he("דנה כהן") in text
    finally:
        doc.close()
    # the copy reached «קבצים» under the day's folder, and the trail is whole
    puts = [c_ for c_ in stub.calls if c_[0] == "PUT"]
    assert any("%D7%97%D7%AA%D7%95%D7%9D.pdf" in c_[1] or "חתום.pdf" in c_[1] for c_ in puts)
    got = office.get("/api/events/%s" % ev["event"]["id"]).get_json()
    assert got["chain"]["ok"] and got["event"]["status"] == "complete"
    types = [e["type"] for e in got["events"]]
    assert types[:2] == ["event.created", "event.sent"] and "event.sealed" in types and types.count("party.signed") == 2


def test_a_side_is_one_browsers_and_taking_it_is_asked(app):
    office = app.test_client()
    ev = prepare(office)
    token = send(office, ev)
    a, b = app.test_client(), app.test_client()
    c = side(boot(a, token), CLIENT)
    name = next(f for f in ev["fields"] if f["party"] == c["id"] and f["type"] == "name")
    assert a.post("/s/%s/f/claim" % token, json={"party": c["id"]}).status_code == 200
    a.post("/s/%s/f/answers" % token, json={"party": c["id"], "values": {name["id"]: "דנה כהן"}})
    r = b.post("/s/%s/f/claim" % token, json={"party": c["id"]})
    assert r.status_code == 409 and r.get_json()["busy"]
    r = b.post("/s/%s/f/claim" % token, json={"party": c["id"], "take": True})
    assert r.status_code == 200 and r.get_json()["took_over"]
    assert r.get_json()["values"] == []                        # what the other browser typed is not shown here
    r = a.post("/s/%s/f/answers" % token, json={"party": c["id"], "values": {name["id"]: "x"}})
    assert r.status_code == 409 and r.get_json()["lost"]
    r = a.post("/s/%s/f/sign" % token, json={"party": c["id"], "consent": True, "signature": {"image": png_ink()}})
    assert r.status_code == 409


def test_a_personal_code_guards_its_side(app):
    office = app.test_client()
    ev = prepare(office)
    four = dict(ev["parties"][0], code="4821")                 # four digits fall to the side's ceiling of guesses
    r = office.post("/api/events/%s/send" % ev["event"]["id"], json={"parties": [four] + ev["parties"][1:],
                                                                      "fields": ev["fields"]})
    assert r.status_code == 400 and "6 עד 8" in r.get_json()["message"]
    token = send(office, ev, code="482117")
    cl = app.test_client()
    b = boot(cl, token)
    c = side(b, CLIENT)
    assert c["code"] is True and side(b, OFFICE)["code"] is False
    r = cl.post("/s/%s/f/claim" % token, json={"party": c["id"]})
    assert r.status_code == 403 and r.get_json()["need_code"]
    for _ in range(4):
        assert cl.post("/s/%s/f/claim" % token, json={"party": c["id"], "code": "000000"}).get_json()["verdict"] == "bad"
    assert cl.post("/s/%s/f/claim" % token, json={"party": c["id"], "code": "000000"}).get_json()["verdict"] == "locked"
    assert cl.post("/s/%s/f/claim" % token, json={"party": c["id"], "code": "482117"}).get_json()["verdict"] == "locked"


def test_in_order_the_second_side_waits_for_the_first(app):
    office = app.test_client()
    ev = prepare(office)
    token = send(office, ev, order="seq")
    cl = app.test_client()
    b = boot(cl, token)
    assert side(b, OFFICE)["blocked"] == CLIENT
    r = cl.post("/s/%s/f/claim" % token, json={"party": side(b, OFFICE)["id"]})
    assert r.status_code == 409 and r.get_json()["blocked"] == CLIENT


def test_answers_stay_private_until_signed_and_a_question_off_the_page_never_shows(app):
    office = app.test_client()
    ev = prepare(office)
    c = side(ev, CLIENT)
    mail = {"id": "fmail", "party": c["id"], "type": "email", "label": "דוא״ל", "required": False, "page": None, "box": None}
    token = send(office, ev, extra=[mail])
    a, other = app.test_client(), app.test_client()
    assert a.post("/s/%s/f/claim" % token, json={"party": c["id"]}).status_code == 200
    name = next(f for f in ev["fields"] if f["party"] == c["id"] and f["type"] == "name")
    role = next(f for f in ev["fields"] if f["party"] == c["id"] and f["type"] == "text")
    a.post("/s/%s/f/answers" % token, json={"party": c["id"], "values": {name["id"]: "דנה כהן", "fmail": "dana@example.com"}})
    seen = json.dumps(boot(other, token), ensure_ascii=False)
    assert "דנה כהן" not in seen and "dana@example.com" not in seen   # nothing of an unsigned side to anyone else
    mine = boot(a, token)
    assert mine["me"] == c["id"] and {v["field"]: v["value"] for v in mine["mine"]}[name["id"]] == "דנה כהן"
    r = a.post("/s/%s/f/sign" % token, json={"party": c["id"], "consent": True,
                                             "values": {role["id"]: "מנכ״לית"}, "signature": {"image": png_ink()}})
    assert r.status_code == 200, r.data
    seen = json.dumps(boot(other, token), ensure_ascii=False)
    assert "דנה כהן" in seen and "dana@example.com" not in seen      # on the page now; the e-mail is not on the page


def test_the_map_must_give_every_side_a_place_to_sign(app):
    office = app.test_client()
    ev = prepare(office)
    fields = [f for f in ev["fields"] if not (f["party"] == side(ev, OFFICE)["id"] and f["type"] == "signature")]
    r = office.post("/api/events/%s/send" % ev["event"]["id"], json={"parties": ev["parties"], "fields": fields})
    assert r.status_code == 400 and OFFICE in r.get_json()["message"]


def test_an_envelope_link_is_still_the_envelopes_page(app):
    cl = app.test_client()
    from test_http import tiny_pdf
    r = cl.post("/api/envelopes", data={"file": (io.BytesIO(tiny_pdf()), "a.pdf"), "signer": "ישראל"},
                content_type="multipart/form-data")
    token = r.get_json()["data"]["link"].rsplit("/", 1)[-1]
    page = cl.get("/s/" + token)
    assert page.status_code == 200 and b"fill-boot" not in page.data and "לחתימה".encode() in page.data


def solid_png(w: int, h: int, rgb=(0, 0, 0)) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        return len(d).to_bytes(4, "big") + t + d + zlib.crc32(t + d).to_bytes(4, "big")
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", w.to_bytes(4, "big") + h.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00")
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def ink_at(path, page, box) -> tuple[float, float]:
    """(darkness inside the box, darkness of the same box mirrored across the page) on the page AS SHOWN."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(path)
    try:
        im = doc[page - 1].render(scale=1).to_pil().convert("L")
    finally:
        doc.close()
    W, H = im.size

    def dark(x, y, w, h):
        crop = im.crop((int(x * W), int(y * H), int((x + w) * W), int((y + h) * H)))
        px = list(crop.getdata())
        return sum(1 for v in px if v < 100) / max(1, len(px))
    x, y, w, h = box
    return dark(x, y, w, h), dark(1 - x - w, 1 - y - h, w, h)


@pytest.mark.parametrize("rotate,crop", [(0, None), (90, None), (180, None), (0, (40, 60, 500, 760))])
def test_a_place_is_drawn_where_the_page_shows_it(tmp_path, rotate, crop):
    """Fractions of the page AS SHOWN — turned (/Rotate) or cut (/CropBox) — land where a viewer shows them."""
    import pikepdf
    src = tmp_path / "turned.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(595, 842))
    if rotate:
        pdf.pages[0].obj.Rotate = rotate
    if crop:
        pdf.pages[0].obj.CropBox = pikepdf.Array(list(crop))
    pdf.save(src)
    box = [0.62, 0.12, 0.2, 0.08]                             # top right of the page as shown
    out = tmp_path / "filled.pdf"
    out.write_bytes(fillpdf.fill(str(src), [{"page": 1, "box": box, "image": solid_png(40, 16)}]))
    inside, mirrored = ink_at(str(out), 1, box)
    assert inside > 0.5 and mirrored < 0.01, (rotate, crop, inside, mirrored)


def test_a_hand_is_kept_in_the_papers_ink_whatever_the_screen_drew_it_in(app):
    office = app.test_client()
    ev = prepare(office)
    token = send(office, ev)
    cl = app.test_client()
    c = side(ev, CLIENT)
    cl.post("/s/%s/f/claim" % token, json={"party": c["id"]})
    name = next(f for f in ev["fields"] if f["party"] == c["id"] and f["type"] == "name")
    role = next(f for f in ev["fields"] if f["party"] == c["id"] and f["type"] == "text")
    white = "data:image/png;base64," + base64.b64encode(solid_png(30, 10, (250, 250, 250))).decode()
    r = cl.post("/s/%s/f/sign" % token, json={"party": c["id"], "consent": True, "values": {name["id"]: "דנה כהן",
                                                                                            role["id"]: "מנכ״לית"},
                                              "signature": {"kind": "draw", "image": white}})
    assert r.status_code == 200, r.data
    from PIL import Image
    im = Image.open(io.BytesIO(cl.get("/s/%s/f/sig/%s" % (token, c["id"])).data)).convert("RGBA")
    assert im.getpixel((5, 5))[:3] == fillpdf.PRINT_INK      # a dark-mode phone's near-white hand, kept in ink


def test_a_side_left_for_another_is_empty_for_the_next(app):
    office = app.test_client()
    ev = prepare(office)
    token = send(office, ev)
    a, b = app.test_client(), app.test_client()
    c, o = side(ev, CLIENT), side(ev, OFFICE)
    name = next(f for f in ev["fields"] if f["party"] == c["id"] and f["type"] == "name")
    assert a.post("/s/%s/f/claim" % token, json={"party": c["id"]}).status_code == 200
    a.post("/s/%s/f/answers" % token, json={"party": c["id"], "values": {name["id"]: "דנה כהן"}})
    assert a.post("/s/%s/f/claim" % token, json={"party": o["id"]}).status_code == 200   # A moves to the other side
    r = b.post("/s/%s/f/claim" % token, json={"party": c["id"]})
    assert r.status_code == 200 and r.get_json()["values"] == []        # nothing of A's answers reaches B


def test_a_new_link_keeps_the_side_its_browser_was_filling(app):
    office = app.test_client()
    ev = prepare(office)
    token = send(office, ev)
    cl = app.test_client()
    c = side(ev, CLIENT)
    r = cl.post("/s/%s/f/claim" % token, json={"party": c["id"]})
    assert "Path=/s/;" in r.headers["Set-Cookie"] or r.headers["Set-Cookie"].rstrip().endswith("Path=/s/")
    new = office.post("/api/events/%s/link" % ev["event"]["id"]).get_json()["link"].rsplit("/", 1)[-1]
    name = next(f for f in ev["fields"] if f["party"] == c["id"] and f["type"] == "name")
    r = cl.post("/s/%s/f/answers" % new, json={"party": c["id"], "values": {name["id"]: "דנה כהן"}})
    assert r.status_code == 200 and boot(cl, new)["me"] == c["id"]


def test_wrong_codes_lock_a_side_longer_each_time(tmp_path, stub):
    from datetime import datetime, timedelta, timezone
    t = {"now": datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)}
    a = server_mod.routes(server_mod.create_app(data_dir=str(tmp_path), clock=lambda: t["now"]))
    a.config["FILL_SYNC"] = True
    app = fill_mod.routes(a)
    office = app.test_client()
    ev = prepare(office)
    token = send(office, ev, code="482193")
    cl, c = app.test_client(), side(ev, CLIENT)
    claim = lambda code: cl.post("/s/%s/f/claim" % token, json={"party": c["id"], "code": code}).get_json()["verdict"]
    assert [claim("000000") for _ in range(5)] == ["bad"] * 4 + ["locked"]
    t["now"] += timedelta(minutes=16)                        # the first lock was 15 minutes
    assert [claim("000000") for _ in range(5)] == ["bad"] * 4 + ["locked"]
    t["now"] += timedelta(minutes=16)                        # the second is 30: still locked, even for the right code
    assert claim("482193") == "locked"
    t["now"] += timedelta(minutes=15)
    assert cl.post("/s/%s/f/claim" % token, json={"party": c["id"], "code": "482193"}).status_code == 200


def test_opened_is_kept_once_and_a_form_post_is_refused(app):
    office = app.test_client()
    ev = prepare(office)
    token = send(office, ev)
    cl = app.test_client()
    for _ in range(3):
        assert cl.post("/s/%s/f/seen" % token, json={}).status_code == 200
    types = [e["type"] for e in office.get("/api/events/%s" % ev["event"]["id"]).get_json()["events"]]
    assert types.count("event.opened") == 1
    r = cl.post("/s/%s/f/claim" % token, data="party=p1", content_type="application/x-www-form-urlencoded")
    assert r.status_code == 415


def test_a_choice_with_no_options_and_a_second_seal_are_refused(app):
    office = app.test_client()
    ev = prepare(office)
    bad = {"id": "fq", "party": side(ev, CLIENT)["id"], "type": "choice", "label": "בחירה", "required": True,
           "options": [], "page": None, "box": None}
    r = office.post("/api/events/%s/send" % ev["event"]["id"], json={"parties": ev["parties"], "fields": ev["fields"] + [bad]})
    assert r.status_code == 400 and "אפשרות" in r.get_json()["message"]
    token = send(office, ev)
    for label, kind in ((CLIENT, "draw"), (OFFICE, "type")):
        cl = app.test_client()
        s = side(ev, label)
        cl.post("/s/%s/f/claim" % token, json={"party": s["id"]})
        vals = {f["id"]: ("דנה כהן" if f["type"] == "name" else "מנכ״לית") for f in ev["fields"]
                if f["party"] == s["id"] and f["type"] in ("name", "text")}
        assert cl.post("/s/%s/f/sign" % token, json={"party": s["id"], "consent": True, "values": vals,
                                                     "signature": {"kind": kind, "image": png_ink()}}).status_code == 200
    assert office.post("/api/events/%s/complete" % ev["event"]["id"]).status_code == 409   # made once, never again


def test_wrong_codes_lock_out_their_own_browser_not_the_signer(app):
    """Behind the office's door every visitor reaches esign from ONE address (the door's): wrong codes are counted per
    browser — the cookie the page gives on its first open — so a stranger's five lock out the stranger only."""
    office = app.test_client()
    ev = prepare(office)
    token = send(office, ev, code="482193")
    c = side(ev, CLIENT)
    stranger, signer = app.test_client(), app.test_client()
    door = {"REMOTE_ADDR": "172.18.0.28"}
    boot(stranger, token), boot(signer, token)                 # each browser opens the page: its own visitor cookie
    for _ in range(5):
        r = stranger.post("/s/%s/f/claim" % token, json={"party": c["id"], "code": "000000"}, environ_base=door)
    assert r.get_json()["verdict"] == "locked"
    r = signer.post("/s/%s/f/claim" % token, json={"party": c["id"], "code": "482193"}, environ_base=door)
    assert r.status_code == 200                                # the stranger's five did not lock the signer out


def test_wrong_codes_at_the_same_moment_are_counted_one_by_one(app):
    """Eight wrong codes from one browser at once: the side checks them one at a time — four are «wrong», the fifth
    locks, the rest find the lock. A guess in flight never erases the lock another has just set (round 5)."""
    import threading
    office = app.test_client()
    ev = prepare(office)
    send(office, ev, code="482193")
    eid, pid = ev["event"]["id"], side(ev, CLIENT)["id"]
    with app.app_context():
        st = fill_mod.fs()
    out, go = [], threading.Barrier(8)

    def guess():
        go.wait()
        out.append(st.code_ok(eid, pid, "000000", "v:one-browser"))
    threads = [threading.Thread(target=guess) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(out) == ["bad"] * 4 + ["locked"] * 4


def test_the_sides_ceiling_of_wrong_codes_tells_the_office(app, stub, monkeypatch):
    monkeypatch.setattr(fill_mod, "CODE_CEILING", 6)
    office = app.test_client()
    ev = prepare(office)
    token = send(office, ev, code="482193")
    c = side(ev, CLIENT)
    a, b = app.test_client(), app.test_client()
    boot(a, token), boot(b, token)
    for _ in range(5):
        a.post("/s/%s/f/claim" % token, json={"party": c["id"], "code": "000000"})
    r = b.post("/s/%s/f/claim" % token, json={"party": c["id"], "code": "000000"})
    assert r.get_json()["verdict"] == "closed"                 # the sixth from anywhere: the side is closed
    notes = [json.loads(x[3]) for x in stub.calls if x[0] == "POST" and x[1].endswith("/api/notifications")]
    assert any(n["level"] == "warn" and CLIENT in n["body"] and "קישור חדש" in n["body"] for n in notes)
    # a fresh browser every five tries meets the same ceiling: closed even for the right code — until a new link
    fresh = app.test_client()
    boot(fresh, token)
    r = fresh.post("/s/%s/f/claim" % token, json={"party": c["id"], "code": "482193"})
    assert r.status_code == 403 and r.get_json()["verdict"] == "closed"
    new = office.post("/api/events/%s/link" % ev["event"]["id"]).get_json()["link"].rsplit("/", 1)[-1]
    boot(fresh, new)
    assert fresh.post("/s/%s/f/claim" % new, json={"party": c["id"], "code": "482193"}).status_code == 200


def test_a_copy_made_but_not_delivered_is_delivered_again_and_a_gap_is_said(app, stub):
    office = app.test_client()
    ev = prepare(office)
    token = send(office, ev)
    pages = os.listdir(os.path.join(app.config["DATA_DIR"], "pages"))
    assert len(pages) == 1                                     # the page pictures were drawn when the link was made
    stub.status = 500                                          # «קבצים» refuses every copy
    for label, kind in ((CLIENT, "draw"), (OFFICE, "type")):
        cl = app.test_client()
        s = side(ev, label)
        cl.post("/s/%s/f/claim" % token, json={"party": s["id"]})
        vals = {f["id"]: ("דנה כהן" if f["type"] == "name" else "מנכ״לית") for f in ev["fields"]
                if f["party"] == s["id"] and f["type"] in ("name", "text")}
        assert cl.post("/s/%s/f/sign" % token, json={"party": s["id"], "consent": True, "values": vals,
                                                     "signature": {"kind": kind, "image": png_ink()}}).status_code == 200
    got = office.get("/api/events/%s" % ev["event"]["id"]).get_json()["event"]
    assert got["final_state"] == "ok" and got["drive_state"].startswith("pending")
    # «קבצים» said no without raising: the office is warned and pointed at the button, not told it was saved
    notes = [json.loads(x[3]) for x in stub.calls if x[0] == "POST" and x[1].endswith("/api/notifications")]
    assert notes[-1]["level"] == "warn" and "מסירה מחדש" in notes[-1]["body"]
    stub.status = 200
    r = office.post("/api/events/%s/complete" % ev["event"]["id"])
    assert r.status_code == 200 and r.get_json()["drive"]["ok"]
    assert office.post("/api/events/%s/complete" % ev["event"]["id"]).status_code == 409   # delivered: nothing to do
    with app.app_context():
        e = fill_mod.fs().get(ev["event"]["id"])
        e["trail_gaps"] = 2
        assert "2 פעולות לא נרשמו" in fill_mod.certificate(e, True)["certificate"]["verdict"]
        # the door's address is not shown as the signer's; a signer's own address on the internet is
        e["parties"][0]["signer_ip"], e["parties"][1]["signer_ip"] = "172.18.0.28", "93.184.216.9"
        cert = fill_mod.certificate(e, True)["certificate"]
        assert [s["ip"] for s in cert["signers"]] == ["", "93.184.216.9"] and "כתובת פנימית" in cert["verdict"]


def test_a_copy_that_failed_is_said_and_made_again_from_the_office(app, monkeypatch):
    office = app.test_client()
    ev = prepare(office)
    token = send(office, ev)
    real = pdfsign.sign
    monkeypatch.setattr(pdfsign, "sign", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("the key is not there")))
    for label, kind in ((CLIENT, "draw"), (OFFICE, "type")):
        cl = app.test_client()
        s = side(ev, label)
        cl.post("/s/%s/f/claim" % token, json={"party": s["id"]})
        vals = {f["id"]: ("דנה כהן" if f["type"] == "name" else "מנכ״לית") for f in ev["fields"]
                if f["party"] == s["id"] and f["type"] in ("name", "text")}
        r = cl.post("/s/%s/f/sign" % token, json={"party": s["id"], "consent": True, "values": vals,
                                                  "signature": {"kind": kind, "image": png_ink()}})
        assert r.status_code == 200, r.data                    # the signer's act is saved whatever the copy does
    e = r.get_json()["event"]
    assert e["status"] == "complete" and not e["final_ready"] and e["final_failed"]
    monkeypatch.setattr(pdfsign, "sign", real)
    eid = ev["event"]["id"]
    with app.app_context():
        assert fill_mod.fs().begin_seal(eid)                   # a press of «הפקה מחדש» is making the copy…
        trail = lambda: [x["type"] for x in app.config["STORE"].events(eid)].count("event.seal_failed")
        failed = trail()
        fill_mod.seal_later(app, eid)                          # …and another seal arrives meanwhile
        assert trail() == failed                               # it ends quietly: no «not made» of a copy in the making
    assert office.post("/api/events/%s/complete" % eid).status_code == 409   # a second press is refused
    with app.app_context():
        fill_mod.fs().set(eid, final_state="failed:the first press stopped")
    r = office.post("/api/events/%s/complete" % eid)
    assert r.status_code == 200, r.data
    assert boot(app.test_client(), token)["event"]["final_ready"]


def test_a_link_cannot_be_sent_already_expired_and_a_claim_survives_its_trail(app, monkeypatch):
    office = app.test_client()
    ev = prepare(office)
    r = office.post("/api/events/%s/send" % ev["event"]["id"], json={"parties": ev["parties"], "fields": ev["fields"],
                                                                     "settings": {"expires": "2020-01-01"}})
    assert r.status_code == 400 and "תאריך" in r.get_json()["message"]
    token = send(office, ev)
    store = app.config["STORE"]
    real = store.append

    def broken(eid, type_, data=None):
        if type_ == "party.claimed":
            raise RuntimeError("database is locked")
        return real(eid, type_, data)
    monkeypatch.setattr(store, "append", broken)
    cl = app.test_client()
    r = cl.post("/s/%s/f/claim" % token, json={"party": side(ev, CLIENT)["id"]})
    assert r.status_code == 200 and "fill_" in r.headers.get("Set-Cookie", "")   # the side reached its browser


def test_the_public_page_carries_its_own_style_and_script(app):
    cl = app.test_client()
    assert cl.get("/s/fill.css").status_code == 200 and cl.get("/s/fill.js").status_code == 200
    ev = prepare(cl)
    token = send(cl, ev)
    page = cl.get("/s/" + token).data.decode()
    assert "/s/fill.css" in page and "/s/fill.js" in page and "@bina-brand:start" in page
    assert cl.get("/s/%s/f/page/1?w=400" % token).headers["Content-Type"] == "image/webp"
