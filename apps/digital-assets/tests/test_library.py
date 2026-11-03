"""the content library (DGO-819): a blueprint's `library:` is its editorial plan — a richtext slot per
item and language — and a WRITTEN body becomes a draft version, once per content of its file, never the
active one. Runs on a scratch state and a scratch blueprints directory; the real library is validated
as it is committed.

    python3 apps/digital-assets/tests/test_library.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="da-library-"))
(TMP / "state").mkdir()
(TMP / "bp" / "content" / "article").mkdir(parents=True)
shutil.copy(HERE / "blueprints" / "_channels.yaml", TMP / "bp" / "_channels.yaml")
os.environ["APP_STATE_DIR"] = str(TMP / "state")
os.environ["DIGITAL_ASSETS_BLUEPRINTS"] = str(TMP / "bp")
sys.path.insert(0, str(HERE))
import yaml  # noqa: E402

import blueprints  # noqa: E402
import store  # noqa: E402

BP = {"id": "lib-test", "version": 1, "name": {"he": "בדיקה", "en": "test"},
      "library": [{"type": "article", "slug": "n8n", "lang": "he", "title": "n8n בלשכה",
                   "category": "open-source", "refs": ["DGO-692"], "words": 2000},
                  {"type": "tutorial", "slug": "install-dgo-with-claude", "lang": "he",
                   "title": "להתקין DGO עם Claude", "refs": ["DGO-749"]}]}
BODY = "---\ntitle: n8n עולה 0 ₪ בלשכה\nexcerpt: קצר\ntags: [n8n]\nauthor: בינה סולושנס\n---\n\nגוף המאמר, מילה ועוד מילה.\n"
FILE = TMP / "bp" / "content" / "article" / "n8n.he.md"


def _write(bp=BP, body=BODY):
    (TMP / "bp" / "lib-test.yaml").write_text(yaml.safe_dump(bp, allow_unicode=True), encoding="utf-8")
    FILE.write_text(body, encoding="utf-8")


def test_plan_and_draft():
    store.init()
    _write()
    got = blueprints.apply("lib-test", by="test")
    assert (got["created"], got["drafts"]) == (2, 1), got
    slot = store.get_slot("content.article.n8n.he")
    assert (slot["kind"], slot["lang"], slot["section"], slot["grp"]) == ("richtext", "he", "content", "article"), slot
    assert slot["plan"]["refs"] == ["DGO-692"] and slot["plan"]["file"] == "content/article/n8n.he.md", slot["plan"]
    assert {t["channel"] for t in slot["targets"]} == {"website", "blog"}, slot["targets"]
    assert store.get_slot("content.tutorial.install-dgo-with-claude.he"), "an item not yet written is a slot of the plan"
    (a,) = store.list_assets("content.article.n8n.he")
    assert (a["status"], a["source"], a["title"], a["author"]) == ("draft", "import", "n8n עולה 0 ₪ בלשכה", "בינה סולושנס"), a
    assert a["text"].startswith("גוף המאמר") and a["meta"]["format"] == "markdown" and a["meta"]["tags"] == ["n8n"], a
    assert store.active_of("content.article.n8n.he") is None, "a written body is never made active by applying"
    assert not store.list_assets("content.tutorial.install-dgo-with-claude.he")


def test_reapply_is_additive():
    again = blueprints.apply("lib-test", by="test")
    assert (again["created"], again["drafts"]) == (0, 0), again
    (a,) = store.list_assets("content.article.n8n.he")
    store.set_active("content.article.n8n.he", a["id"], by="owner")
    _write(body=BODY.replace("מילה ועוד מילה", "מילה, ועוד מילה, ועוד אחת"))
    edited = blueprints.apply("lib-test", by="test")
    assert edited["drafts"] == 1, edited
    assert len(store.list_assets("content.article.n8n.he")) == 2, "an edited body is a NEW draft beside the old"
    assert store.active_of("content.article.n8n.he")["asset_id"] == a["id"], "the owner's active choice is untouched"


def test_invalid_entries():
    known = {c["id"] for c in blueprints.channel_catalog()}
    bad = {"id": "x", "library": [{"type": "essay", "slug": "a", "title": "t"},
                                  {"type": "article", "slug": "Not Latin", "title": "t"},
                                  {"type": "article", "slug": "ok", "lang": "fr", "title": "t"},
                                  {"type": "article", "slug": "same", "title": "t"},
                                  {"type": "article", "slug": "same", "title": "t"},
                                  {"type": "news", "slug": "untitled"}]}
    problems = blueprints.validate(bad, known)
    for needle in ("type not in", "slug must be", "lang not in", "duplicate slot content.article.same.he", "no title"):
        assert any(needle in p for p in problems), (needle, problems)


def test_summary_counts():
    s = blueprints.summary(blueprints.all_blueprints()["lib-test"])
    assert (s["counts"]["library"], s["counts"]["written"]) == (2, 1), s["counts"]


def test_the_real_library_validates():
    real = yaml.safe_load((HERE / "blueprints" / "content-library.yaml").read_text(encoding="utf-8"))
    known = {c["id"] for c in yaml.safe_load((HERE / "blueprints" / "_channels.yaml").read_text(encoding="utf-8"))["channels"]}
    assert not blueprints.validate(real, known), blueprints.validate(real, known)[:5]
    for e in real["library"]:
        f = HERE / "blueprints" / "content" / e["type"] / f"{e['slug']}.{e.get('lang') or 'he'}.md"
        if f.is_file():
            front, body = blueprints._front(f.read_text(encoding="utf-8"))
            assert front.get("title") and body.strip(), f"{f.name}: a written body has front matter and text"


if __name__ == "__main__":
    try:
        test_plan_and_draft()
        test_reapply_is_additive()
        test_invalid_entries()
        test_summary_counts()
        test_the_real_library_validates()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print("library: 5/5 ok")
