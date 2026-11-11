"""site_kit: scan finds what a page maps and what it does not; apply rewrites exactly the mapped
values, keeps everything else byte-for-byte, and reports missing/unused keys.

    python3 apps/digital-assets/tests/test_site_kit.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import site_kit  # noqa: E402

PAGE = (HERE / "fixtures" / "home.html").read_text(encoding="utf-8")
BUNDLE = {"slots": {
    "identity.name.brand-he": {"kind": "text", "text": "הלשכה הדיגיטלית"},
    "identity.description.short": {"kind": "text", "text": "מערכת ההפעלה של העסק שלך"},
    "identity.logo.primary": {"kind": "image", "url": "http://digital-assets:8985/files/abc.png", "sha": "abc"},
    "content.docs.home": {"kind": "link", "text": "https://docs.digital-office.co.il"},
    "content.website.home-hero": {"kind": "text", "text": "העסק שלך, על מחשב אחד"},
    "content.website.home-subtitle": {"kind": "richtext", "text": "שורה אחת\nשורה שתיים"},
    "content.website.cta": {"kind": "text", "text": "התקינו עכשיו"},
    "content.vision.manifesto": {"kind": "richtext", "text": "לא מופיע בעמוד"},
}}


def test_scan():
    s = site_kit.scan(PAGE)
    keys = s["keys"]
    assert "content.website.home-hero" in keys and "identity.logo.primary" in keys, keys
    whats = {(m["key"], m["what"]) for m in s["mapped"]}
    assert ("identity.name.brand-he", "alt") in whats and ("identity.name.brand-he", "text") in whats
    unmapped = [u["current"] for u in s["unmapped"]]
    assert "טקסט שעוד לא מופה לשום משבצת" in unmapped, unmapped
    assert "/team.jpg" in unmapped and "/old-og.png" in unmapped, unmapped


def test_apply():
    out, rep = site_kit.apply(PAGE, BUNDLE, lambda e: "/_da/abc.png")
    assert "<title data-da=\"identity.name.brand-he\">הלשכה הדיגיטלית</title>" in out
    assert 'content="מערכת ההפעלה של העסק שלך"' in out
    assert 'src="/_da/abc.png"' in out and 'alt="הלשכה הדיגיטלית"' in out
    assert 'href="https://docs.digital-office.co.il"' in out
    assert ">העסק שלך, על מחשב אחד</h1>" in out
    assert "שורה אחת<br>\nשורה שתיים" in out
    assert ">התקינו עכשיו</button>" in out
    assert "טקסט שעוד לא מופה לשום משבצת" in out and "נשאר כמו שהוא" in out
    assert rep["missing"] == ["content.not.in.bundle"], rep
    assert rep["unused"] == ["content.vision.manifesto"], rep
    # idempotent: applying twice changes nothing the second time
    out2, rep2 = site_kit.apply(out, BUNDLE, lambda e: "/_da/abc.png")
    assert out2 == out and rep2["changed"] == [], rep2["changed"]
    # everything outside the mapped values is untouched
    assert out.count("<p>טקסט שעוד לא מופה לשום משבצת</p>") == 1


def test_attribute_texts():
    """A text that lives in an attribute (a field's placeholder, a tooltip, a screen reader's label) is a
    slot like any other — and the attribute is matched by its whole name, never inside `data-da-…`."""
    page = ('<form><input type="text" data-da-placeholder="content.website.form-name" placeholder="Name">'
            '<a href="#" title="old" data-da-title="content.website.reset">x</a>'
            '<button aria-label="Menu" data-da-aria-label="content.website.menu"></button></form>')
    bundle = {"slots": {"content.website.form-name": {"kind": "text", "text": "שם"},
                        "content.website.reset": {"kind": "text", "text": "לאפס את כל האפשרויות"},
                        "content.website.menu": {"kind": "text", "text": "תפריט"}}}
    out, rep = site_kit.apply(page, bundle)
    assert 'placeholder="שם"' in out and 'title="לאפס את כל האפשרויות"' in out and 'aria-label="תפריט"' in out, out
    assert 'data-da-title="content.website.reset"' in out and 'data-da-aria-label="content.website.menu"' in out, out
    assert len(rep["changed"]) == 3 and rep["missing"] == [], rep
    whats = {m["what"] for m in site_kit.scan(page)["mapped"]}
    assert whats == {"placeholder", "title", "aria-label"}, whats
    out2, rep2 = site_kit.apply(out, bundle)
    assert out2 == out and rep2["changed"] == [], rep2


def test_any_attribute():
    """`data-da-attr-<name>` sets attribute <name> from a slot — a counter's number lives in
    `data-to-value`, and its text is only where the animation starts, so the text is not the slot."""
    page = ('<span class="elementor-counter-number" data-duration="2000" data-to-value="521" data-from-value="0" '
            'data-da-attr-data-to-value="content.website.units">0</span>'
            '<span data-da-attr-data-to-value="content.website.absent" data-to-value="9">0</span>')
    bundle = {"slots": {"content.website.units": {"kind": "text", "text": "530"}}}
    out, rep = site_kit.apply(page, bundle)
    assert 'data-to-value="530"' in out and 'data-from-value="0"' in out and ">0</span>" in out, out
    assert rep["changed"] == [{"key": "content.website.units", "what": "data-to-value"}], rep
    assert rep["missing"] == ["content.website.absent"] and 'data-to-value="9"' in out, rep
    mapped = site_kit.scan(page)["mapped"]
    assert {(m["key"], m["what"], m["current"]) for m in mapped} == {
        ("content.website.units", "data-to-value", "521"), ("content.website.absent", "data-to-value", "9")}, mapped
    assert site_kit.apply(out, bundle)[0] == out


def test_files_and_kinds_in_any_attribute():
    """A FILE slot goes through `file_url` whatever attribute names it (a lazy loader's `data-src`), so
    the asset service's internal address never reaches a page; a TEXT slot named by `src` leaves `src`
    alone (it used to raise, and the whole page went out unrewritten); and an attribute's name inside
    ANOTHER attribute's value is not that attribute."""
    bundle = {"slots": {"img": {"kind": "image", "url": "http://digital-assets:8985/files/a.png", "sha": "a"},
                        "txt": {"kind": "text", "text": "כותרת"}}}
    to_site = lambda e: ".assets/a.png"  # noqa: E731
    out, _ = site_kit.apply('<img data-da-attr-data-src="img" data-src="x.png" src="x.png">', bundle, to_site)
    assert 'data-src=".assets/a.png"' in out and "digital-assets:8985" not in out, out
    out, _ = site_kit.apply('<a data-da-href="img" href="old.pdf">x</a>', bundle, to_site)
    assert 'href=".assets/a.png"' in out, out
    out, rep = site_kit.apply('<img data-da-attr-src="txt" src="keep.png"><h1 data-da="txt">x</h1>', bundle, to_site)
    assert 'src="keep.png"' in out and ">כותרת</h1>" in out, out
    page = '<a onclick="tip(this, \'a\', title=\'old\')" title="real" data-da-title="txt">x</a>'
    out, _ = site_kit.apply(page, bundle)
    assert "title='old'" in out and 'title="כותרת"' in out and 'title="real"' not in out, out
    out, _ = site_kit.apply('<input data-da-placeholder="txt" disabled placeholder=old/>', bundle)
    assert 'placeholder="כותרת"' in out and "disabled" in out, out
    # every tag shape the parser reads an attribute from, the attribute is REPLACED — never a second
    # copy appended (the browser shows the first, the parser keeps the last: the slot would never show)
    for tag in ('<a href=?p=2 title=old data-da-title="txt">', '<img src="a" / title="old" data-da-title="txt">',
                '<a href="x"title="old" data-da-title="txt">', '<img/title="old" data-da-title="txt">',
                '<a href=index.php?id=5 TITLE=\'old\' data-da-title="txt">'):
        out, rep = site_kit.apply(tag, bundle)
        assert out.lower().count("title=") == 2 and 'title="כותרת"' in out.replace("TITLE", "title"), (tag, out)
        assert site_kit.apply(out, bundle)[1]["changed"] == [], (tag, out)


if __name__ == "__main__":
    test_scan()
    test_apply()
    test_attribute_texts()
    test_any_attribute()
    test_files_and_kinds_in_any_attribute()
    print("site_kit: 5/5 ok")
