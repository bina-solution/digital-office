"""The digital-assets recipe's printer (DGO-948): what each slot holds, one line each, a word to narrow a
section of 174, and never "nothing there" for an API that did not answer.

    python3 apps/digital-assets/operatives/test_slots.py
"""
import importlib.util
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location("slots", os.path.join(HERE, "slots.py"))
slots = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(slots)

DOC = json.dumps({"slots": [
    {"key": "content.website.home.hero", "kind": "text", "label": {"he": "כותרת הגיבור", "en": "Hero title"},
     "active": {"id": "a-1", "kind": "text", "text": "מערכת ההפעלה\nשל העסק הישראלי"}},
    {"key": "content.website.home.pricing", "kind": "text", "label": {"he": "תמחור (בדף הבית)"},
     "active": {"id": "a-2", "text": "חינם להתקנה עצמית | משלמים רק על מה שאנחנו מפעילים"}},
    {"key": "content.website.home.subtitle", "kind": "richtext", "label": {"he": "תת־כותרת"}, "active": {}},
    {"key": "identity.logo.primary", "kind": "image", "label": {"he": "לוגו ראשי"},
     "active": {"id": "a-3", "kind": "image", "ext": "svg"}},
]}, ensure_ascii=False)
MEDIA = json.dumps({"slots": [
    {"key": "media.launch.reel", "section": "media", "kind": "video", "label": {"he": "סרטון השקה"}, "count": 3,
     "active": None},
    {"key": "media.launch.post", "section": "media", "kind": "image", "label": {"he": "פוסט השקה"}, "count": 0,
     "active": None},
]}, ensure_ascii=False)


class Slots(unittest.TestCase):
    def test_what_each_slot_holds_one_line_each(self):
        out, code = slots.lines(DOC)
        self.assertEqual(code, 0)
        self.assertEqual(out, [
            "כותרת הגיבור | content.website.home.hero | מערכת ההפעלה של העסק הישראלי",
            "תמחור (בדף הבית) | content.website.home.pricing | חינם להתקנה עצמית ¦ משלמים רק על מה שאנחנו מפעילים",
            "לוגו ראשי | identity.logo.primary | (image svg)",
            "3 slot(s) hold something, 1 are empty",
        ])

    def test_a_word_narrows_by_key_or_label(self):
        out, _ = slots.lines(DOC, "תמחור")
        self.assertEqual(out[0].split(" | ")[1], "content.website.home.pricing")
        self.assertEqual(out[-1], "1 slot(s) hold something (of those with «תמחור»)")
        self.assertEqual(slots.lines(DOC, "hero")[0][0].split(" | ")[1], "content.website.home.hero")

    def test_a_word_with_its_hebrew_prefix_still_finds_the_slot(self):
        out, code = slots.lines(DOC, "התמחור")          # «מה כתוב באתר על התמחור?» — the model's word
        self.assertEqual((out[0].split(" | ")[1], code), ("content.website.home.pricing", 0))
        self.assertEqual(slots.lines(DOC, "תמחור בית")[0][0].split(" | ")[1], "content.website.home.pricing")
        self.assertEqual(slots.lines(DOC, "תמחור לוגו")[0], ["0 slot(s) hold something (of those with «תמחור לוגו»)"])
        self.assertEqual(slots.lines(DOC, "he")[0][-1], "1 slot(s) hold something (of those with «he»)")  # hero only

    def test_a_media_unit_with_items_holds_something(self):
        out, _ = slots.lines(MEDIA)
        self.assertEqual(out, ["סרטון השקה | media.launch.reel | (3 item(s))", "1 slot(s) hold something, 1 are empty"])

    def test_bbox_remote_status_line_is_skipped(self):
        self.assertEqual(slots.lines("HTTP 200  GET http://digital-assets.macbook:9005/api/slots\n" + DOC), slots.lines(DOC))

    def test_an_error_is_shown_and_fails(self):
        self.assertEqual(slots.lines('HTTP 502  GET x\n{"error": "down"}'), (["HTTP 502  GET x", '{"error": "down"}'], 1))
        self.assertEqual(slots.lines(""), (["(the digital-assets API answered nothing)"], 1))

    def test_an_empty_section(self):
        self.assertEqual(slots.lines('{"slots": []}'), (["0 slot(s) hold something"], 0))

    def test_the_line_it_is_given(self):
        self.assertEqual(slots.asked(["content", "תמחור", "--via", "macbook", "digital-assets"]),
                         ("content", "תמחור", ("macbook", "digital-assets")))
        self.assertEqual(slots.asked(["identity", "<word>"]), ("identity", "", None))
        self.assertEqual(slots.asked(["<section>", "<word>", "--via", "macbook", "digital-assets"]),
                         ("content", "", ("macbook", "digital-assets")))
        self.assertEqual(slots.asked(["תמחור"]), ("content", "תמחור", None))
        self.assertEqual(slots.asked([]), ("content", "", None))

    def test_a_via_without_an_office_and_an_alias_is_refused(self):
        # read here instead, it would print this office's texts as the other office's
        for line in (["content", "--via", "vps1"], ["--via"], ["x", "--via", "<office>", "<alias>"],
                     ["--via", "macbook", "--x"]):
            with self.assertRaises(ValueError, msg=line):
                slots.asked(line)

    def test_many_are_counted_and_a_long_text_is_cut(self):
        many = json.dumps({"slots": [{"key": f"k{i}", "label": {"he": f"ל{i}"}, "active": {"text": "x" * 300}}
                                     for i in range(30)]})
        out, _ = slots.lines(many)
        self.assertEqual(out[-2:], ["… and 5 more that hold something", "30 slot(s) hold something"])
        self.assertTrue(out[0].endswith("x" * 200 + "…"))


if __name__ == "__main__":
    unittest.main()
