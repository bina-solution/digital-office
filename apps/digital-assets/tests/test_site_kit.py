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


if __name__ == "__main__":
    test_scan()
    test_apply()
    print("site_kit: 2/2 ok")
