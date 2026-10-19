#!/usr/bin/env python3
"""Research → blueprints. Regenerates ../blueprints/{business-basic,basic-restaurant,startup-tail}.yaml
from the machine-readable appendices of the research files in this directory.

    python3 apps/digital-assets/research/build_blueprints.py

Why a generator and not hand-written YAML: the research is the evidence (every slot and unit there
cites its sources), and it will be refreshed. The blueprints must follow it, not drift from it. What
the research cannot know — which slot feeds which social PROFILE FIELD, the Hebrew names of the
startup units, the startup's own identity/content slots — is written HERE, in three small tables,
and is the only hand-made part.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "blueprints"
TODAY = "2026-09-29"

SOCIAL = ["facebook", "instagram", "x", "youtube", "github", "discord", "whatsapp", "linkedin",
          "tiktok", "telegram", "threads"]


def appendix(name: str, marker: str) -> dict:
    text = (HERE / name).read_text(encoding="utf-8")
    m = re.search(r"```yaml\n(" + re.escape(marker) + r".*?)```", text, re.S)
    if not m:
        raise SystemExit(f"{name}: no {marker!r} appendix")
    return yaml.safe_load(m.group(1))


# ── table 1: which slot feeds which profile field, on which channels ─────────────────────────────
# (key → {field: [channels]}). Everything else a slot targets is tracked, not pushed.
FIELD_MAP: dict[str, dict[str, list[str]]] = {
    "identity.logo.square":             {"avatar": SOCIAL},
    "identity.name.brand-he":           {"name": SOCIAL},
    "identity.name.brand-en":           {"name": SOCIAL},
    "identity.description.short":       {"bio": SOCIAL},
    "identity.contact.website-url":     {"links": ["facebook", "instagram", "x", "youtube", "github", "whatsapp"]},
    "identity.profile.facebook.cover":  {"banner": ["facebook"]},
    "identity.profile.facebook.intro":  {"bio": ["facebook"]},
    "identity.profile.instagram.bio":   {"bio": ["instagram"]},
    "identity.profile.whatsapp.about":  {"bio": ["whatsapp"]},
    "identity.profile.whatsapp.photo":  {"avatar": ["whatsapp"]},
    "identity.profile.youtube.banner":  {"banner": ["youtube"]},
    "identity.profile.x.header":        {"banner": ["x"]},
    "identity.profile.x.bio":           {"bio": ["x"]},
    "identity.profile.tiktok.bio":      {"bio": ["tiktok"]},
    "identity.profile.discord.banner":  {"banner": ["discord"]},
    "identity.profile.linkedin.cover":  {"banner": ["linkedin"]},
}
# slots the office's own products read live (the `brand` capability)
BRAND = {"identity.name.brand-he": "name", "identity.name.brand-en": "name_en",
         "identity.logo.primary": "logo", "identity.logo.square": "logo_square",
         "identity.logo.favicon": "favicon", "identity.logo.monochrome": "logo_mono",
         "identity.description.short": "description", "identity.tagline": "tagline",
         "identity.color.primary": "color", "identity.slug": "slug"}
LANG = {"identity.name.brand-he": "he", "identity.name.brand-en": "en"}


def convert_slot(s: dict) -> dict:
    key = s["key"]
    section = {"identification": "identity"}.get(s["section"], s["section"])
    targets = []
    fmap = FIELD_MAP.get(key, {})

    for f, chans in fmap.items():
        for c in chans:
            targets.append({"channel": c, "field": f})
    for c in s.get("targets") or []:
        if not any(t["channel"] == c for t in targets):
            targets.append({"channel": c})
    if key in BRAND:
        targets.append({"channel": "brand", "field": None, "brand": BRAND[key]})
    cons = dict(s.get("constraints") or {})
    out = {"key": key, "section": section, "group": key.split(".")[1] if key.count(".") >= 2 else "",
           "label": {"he": s.get("label_he"), "en": s.get("label_en")},
           "kind": {"rich-text": "richtext"}.get(s["kind"], s["kind"]),
           "required": bool(s.get("required")), "constraints": cons,
           "expires": None if s.get("expires") in (None, "none") else s.get("expires"),
           "targets": [{k: v for k, v in t.items() if v is not None} for t in targets]}
    if key in LANG:
        out["lang"] = LANG[key]
    elif isinstance(cons.get("langs"), list) and len(cons["langs"]) == 1:
        out["lang"] = cons["langs"][0]
    return out


def convert_calendar(c: dict) -> dict:
    return {"id": c["id"], "name": {"he": c.get("name_he") or c["id"], "en": c.get("name_en") or c["id"]},
            "trigger": c.get("trigger"), "channels": c.get("channels") or [],
            "assets": c.get("assets") or []}


# ── table 2: the startup-tail in Hebrew ──────────────────────────────────────────────────────────
PHASE_HE = {
    "stealth": "לפני ההשקה — מתחת לרדאר", "teaser": "טיזר", "waitlist": "רשימת המתנה / בטא סגורה",
    "launch-day": "יום ההשקה", "post-launch": "אחרי ההשקה", "release-train": "רכבת העדכונים (קבוע)",
    "launch-week": "שבוע השקות (קבוע)", "proof": "אבני דרך ובנייה בציבור", "funding": "גיוס",
    "community": "קהילה והדרכה (קבוע)", "expansion": "תמחור, פלטפורמות, חומרה ומוצר שני",
    "conference": "כנס / קינוט שנתי", "annual": "יום הולדת וסיכום שנה",
    "transition": "מעברים: שינוי כיוון, רישיון, תקלה, רכישה"}
UNIT_HE = {
    "holding-page": "עמוד המתנה עם הרשמה", "founder-thesis-post": "מניפסט המייסדים",
    "teaser-video": "סרטון טיזר / הצצה", "save-the-date": "שמרו את התאריך / ספירה לאחור",
    "waitlist-survey": "רשימת המתנה עם שאלון", "cohort-invite-email": "הזמנה למחזור בטא + עדכון גרסה",
    "launch-post": "פוסט ההשקה (העמוד המרכזי)", "launch-film": "סרט ההשקה", "hn-launch": "השקה ב-Hacker News",
    "product-hunt-launch": "השקה ב-Product Hunt", "social-launch-thread": "שרשור / קרוסלת השקה",
    "launch-postmortem": "סיכום ההשקה במספרים", "first-big-update": "העדכון הגדול הראשון",
    "changelog-entry": "רשומת יומן שינויים", "changelog-digest-email": "תקציר שינויים בדוא״ל",
    "monthly-update-post": "פוסט עדכונים חודשי", "release-livestream": "שידור חי לגרסה",
    "whats-new-video": "סרטון „מה חדש” / „הכירו את…”", "launch-week-hub": "עמוד שבוע ההשקות",
    "personal-ticket": "כרטיס אישי / תג", "daily-drop": "השקה יומית (יום N מתוך 5)",
    "community-hackathon": "האקתון ומפגשים", "launch-week-recap": "סיכום שבוע ההשקות",
    "milestone-post": "פוסט אבן דרך", "open-metrics-page": "עמוד מדדים פתוח",
    "research-or-opinion-post": "מחקר / דעה / תגובה לחדשות", "funding-announcement": "הודעת גיוס",
    "why-we-raised-post": "למה ואיך גייסנו", "newsletter-issue": "גיליון ניוזלטר",
    "method-handbook": "המתודה / המדריך הפתוח", "tutorial-video": "סדרת סרטוני הדרכה",
    "community-spotlight": "זרקור על הקהילה", "pricing-launch": "השקת תמחור / מסלול בתשלום",
    "platform-launch": "השקה בפלטפורמה חדשה", "hardware-launch": "השקת חומרה / מוצר פיזי",
    "second-product-reveal": "חשיפת מוצר שני", "conference-announce-cfp": "הכרזת כנס וקול קורא",
    "keynote-livestream": "קינוט בשידור חי", "talk-recordings": "הקלטות הרצאות וסדנאות",
    "anniversary-moment": "יום הולדת", "state-of-address": "נאום „מצב המוצר” השנתי",
    "year-in-review": "סיכום השנה", "open-letter": "מכתב פתוח", "incident-report": "דוח תקלה / אבטחה",
    "acquisition-announcement": "הודעת רכישה / פרק חדש",
    # company-derived units (below)
    "star-milestone": "כרטיס אבן דרך בכוכבי GitHub", "beta-call": "קריאה לבודקי בטא",
    "new-app-listing": "אפליקציה חדשה בחנות", "major-version": "גרסה ראשית (X.0)",
    "customer-story": "סיפור לקוח", "localization-launch": "השקת שפה חדשה",
    "meetup-report": "דיווח ממפגש קהילה", "contest-challenge": "תחרות / אתגר שבועי",
    "teaser-drip": "טפטוף טיזרים ב-X", "feature-cards": "כרטיסי פיצ'רים (בנטו)",
    "founder-forum-post": "פוסט מייסד בפורום", "beta-to-ga": "מבטא לזמינות כללית",
    "github-release": "הערות גרסה ב-GitHub", "hardware-series": "סדרת סרטוני חומרה",
}
# units the three company scans add to the cross-company skeleton (phase → units)
EXTRA_UNITS = {
    "teaser": [
        {"id": "teaser-drip", "name": "Teaser drip on X",
         "purpose": "Build curiosity for a week without naming the product.",
         "trigger": "A reveal date is fixed.", "timing": "D-7..D-1",
         "channels": ["x", "instagram", "discord"],
         "assets": [{"kind": "image", "spec": "2160x2160 crop of the product, one per day", "count": 5},
                    {"kind": "text", "spec": "1-3 word lowercase post per day ('uh oh', 'we cooked')", "count": 5}],
         "copy": "cryptic line → cropped glimpse → (no name, no link) → the reveal lands on D0",
         "from": "umbrel U1 (research/umbrel.md)"}],
    "launch-day": [
        {"id": "feature-cards", "name": "Feature-card thread (bento)",
         "purpose": "Explain the release one feature per card, as replies to the reveal.",
         "trigger": "The reveal post is up.", "timing": "D0, as replies to the reveal",
         "channels": ["x", "linkedin", "instagram"],
         "assets": [{"kind": "image", "spec": "3200x2400 (4:3) card per feature", "count": 6},
                    {"kind": "image", "spec": "4:3 'bento' hero summarising all features", "count": 1}],
         "copy": "'Introducing X.' → one card per feature (headline + one line) → thanks to the community",
         "from": "umbrel U2/U3"},
        {"id": "founder-forum-post", "name": "Founder post in the community forum",
         "purpose": "Talk to the existing community directly, before the press does.",
         "trigger": "The reveal is public.", "timing": "D0",
         "channels": ["discord", "github", "website"],
         "assets": [{"kind": "text", "spec": "'Hey everyone' post: what, how to try the beta, what feedback we need, the date", "count": 1}],
         "copy": "Hey everyone → the reveal link → how to try the beta → ask for feedback → date promise",
         "from": "umbrel U7"}],
    "post-launch": [
        {"id": "beta-to-ga", "name": "Beta → general availability",
         "purpose": "Close the loop: the public beta becomes the release everyone gets.",
         "trigger": "The beta is stable.", "timing": "D+6..D+43 (umbrel: 6-43 days after the reveal)",
         "channels": ["x", "youtube", "github", "website"],
         "assets": [{"kind": "video", "spec": "25-47 s cut of the reveal film", "count": 1},
                    {"kind": "text", "spec": "quote of the reveal post: 'X. Rolling out today.'", "count": 1}],
         "copy": "quote the reveal → 'rolling out today' → what changed since the beta → update now",
         "from": "umbrel U4"}],
    "proof": [
        {"id": "star-milestone", "name": "GitHub star milestone card",
         "purpose": "Celebrate a round number of GitHub stars — the open-source proof metric.",
         "trigger": "GitHub stars cross a round number (5k, 10k, 50k…).", "timing": "on trigger",
         "channels": ["x", "linkedin", "github", "discord", "instagram"],
         "assets": [{"kind": "image", "spec": "card 1920x1080 (16:9) with the number and a pun", "count": 1},
                    {"kind": "image", "spec": "1080x1080 square cut", "count": 1}],
         "copy": "the number → thank-you to contributors → one line on what is next → link to repo",
         "from": "n8n U06 (research/n8n.md)"},
        {"id": "customer-story", "name": "Customer story",
         "purpose": "Show a real business getting a real result with the product.",
         "trigger": "A customer outcome worth telling.", "timing": "recurring:monthly",
         "channels": ["website", "youtube", "linkedin", "x"],
         "assets": [{"kind": "video", "spec": "16:9 1920x1080, 60-180 s", "count": 1},
                    {"kind": "text", "spec": "case study 600-1200 words", "count": 1},
                    {"kind": "image", "spec": "hero 1600x900", "count": 1}],
         "copy": "who they are → the problem before → what they built → the number after → quote",
         "from": "Notion U9, n8n U16"}],
    "release-train": [
        {"id": "github-release", "name": "GitHub release notes",
         "purpose": "The canonical, versioned record of a release, read by the people who install it.",
         "trigger": "A version is tagged.", "timing": "recurring:every release",
         "channels": ["github", "rss", "discord"],
         "assets": [{"kind": "text", "spec": "'X.Y brings A, B, C…' + 'New features' bullets + Discord CTA + downloads with checksums", "count": 1},
                    {"kind": "image", "spec": "bento hero 4:3", "count": 1}],
         "copy": "one sentence of what it brings → bento → bullets → where to talk about it → downloads",
         "from": "umbrel U6, n8n U01"},
        {"id": "new-app-listing", "name": "New app in the store",
         "purpose": "Every new app in the store is a small launch of its own.",
         "trigger": "An app is published to the app store.", "timing": "recurring:every release",
         "channels": ["app-store", "x", "discord", "github"],
         "assets": [{"kind": "image", "spec": "app icon 256x256 + 3-5 gallery screenshots 1440x900", "count": 1},
                    {"kind": "text", "spec": "listing: name, tagline ≤60, description, release notes", "count": 1}],
         "copy": "app name + one-line promise → what it does in the office → screenshot → install link",
         "from": "umbrel App Store listing, n8n integration pages, Notion template gallery"},
        {"id": "beta-call", "name": "Call for beta testers",
         "purpose": "Recruit the community to test a feature before it ships.",
         "trigger": "A feature is ready for community testing.", "timing": "recurring:monthly",
         "channels": ["discord", "github", "x", "email"],
         "assets": [{"kind": "text", "spec": "forum/Discord post: what to test, how, until when", "count": 1},
                    {"kind": "image", "spec": "screenshot 1600x900", "count": 1}],
         "copy": "what is new → how to turn it on → what feedback we need → where to report",
         "from": "n8n U03"}],
    "community": [
        {"id": "meetup-report", "name": "Community meetup report",
         "purpose": "Turn a local meetup into content and proof of a living community.",
         "trigger": "A meetup happened.", "timing": "per event",
         "channels": ["x", "linkedin", "instagram", "discord"],
         "assets": [{"kind": "image", "spec": "photo set 1080x1350, 3-6 photos", "count": 1},
                    {"kind": "text", "spec": "short report + next date", "count": 1}],
         "copy": "where + who came → best moment → what we learned → next meetup",
         "from": "n8n U08"},
        {"id": "contest-challenge", "name": "Contest / weekly challenge",
         "purpose": "Seed a new capability or keep the community building.",
         "trigger": "A capability to seed, or an engagement series.", "timing": "recurring:weekly",
         "channels": ["discord", "x", "youtube"],
         "assets": [{"kind": "image", "spec": "challenge card 1080x1080", "count": 1},
                    {"kind": "text", "spec": "rules, prize, deadline", "count": 1}],
         "copy": "the challenge → the prize → the deadline → how to submit",
         "from": "n8n U10"}],
    "expansion": [
        {"id": "hardware-series", "name": "Hardware video series",
         "purpose": "A physical product needs a sequence, not a post: the reveal, then its life.",
         "trigger": "A device is revealed.", "timing": "reveal D0 → making-of D+1 → ships D+5 → unboxing D+13 → setup D+15 → use-case film D+21",
         "channels": ["youtube", "x", "instagram", "website"],
         "assets": [{"kind": "video", "spec": "making-of 16:9", "count": 1},
                    {"kind": "video", "spec": "unboxing 16:9 + 9:16 cut", "count": 1},
                    {"kind": "video", "spec": "setup walkthrough 16:9", "count": 1},
                    {"kind": "video", "spec": "use-case film 60-120 s", "count": 1}],
         "copy": "reveal → how it is made → it ships → open the box → set it up → what you do with it",
         "from": "umbrel U8 (Umbrel Home / Pro)"},
        {"id": "major-version", "name": "Major version (X.0)",
         "purpose": "A semver-major release is a launch: announce, test, migrate, celebrate.",
         "trigger": "A major version is ready.", "timing": "announce D-13..D-5, release D0",
         "channels": ["website", "github", "x", "youtube", "producthunt", "email"],
         "assets": [{"kind": "page", "spec": "breaking-changes / migration page", "count": 1},
                    {"kind": "text", "spec": "blog 'X.0 is here'", "count": 1},
                    {"kind": "video", "spec": "16:9 90-180 s walkthrough", "count": 1},
                    {"kind": "image", "spec": "1200x675 card", "count": 1}],
         "copy": "'coming soon' → 'ready to be tested' → what changes for you → the release → thanks",
         "from": "n8n U04, umbrelOS 1.0, Notion 2.0"},
        {"id": "localization-launch", "name": "New language launch",
         "purpose": "Opening the product in a new language is a launch in that market.",
         "trigger": "A new interface language ships.", "timing": "on trigger",
         "channels": ["website", "x", "linkedin", "facebook", "instagram"],
         "assets": [{"kind": "image", "spec": "1200x675 card in the new language", "count": 1},
                    {"kind": "text", "spec": "announcement in the new language", "count": 1}],
         "copy": "'<product> now speaks <language>' → what is translated → who helped → try it",
         "from": "Notion U13"}],
}

# ── table 3: the startup's own identity and content slots ────────────────────────────────────────
STARTUP_SLOTS = [
    {"key": "identity.product.name", "section": "identity", "group": "product", "kind": "text",
     "label": {"he": "שם המוצר", "en": "Product name"}, "required": True,
     "constraints": {"note": "when the product and the company differ (Digital Office vs the company behind it)"},
     "targets": [{"channel": "website"}, {"channel": "github"}, {"channel": "app-store"},
                 {"channel": "brand", "brand": "product"}]},
    {"key": "identity.product.one-liner", "section": "identity", "group": "product", "kind": "text",
     "label": {"he": "משפט אחד על המוצר", "en": "Product one-liner"}, "required": True,
     "constraints": {"max_len": 90, "note": "the line under the name everywhere; the X/HN/PH title"},
     "targets": [{"channel": "website"}, {"channel": "github", "field": "bio"}, {"channel": "producthunt"},
                 {"channel": "hackernews"}]},
    {"key": "identity.logo.wordmark", "section": "identity", "group": "logo", "kind": "image",
     "label": {"he": "לוגו מילולי (wordmark)", "en": "Wordmark"},
     "constraints": {"formats": ["SVG", "PNG"]}, "targets": [{"channel": "website"}, {"channel": "print"}]},
    {"key": "identity.handles", "section": "identity", "group": "names", "kind": "list",
     "label": {"he": "שמות המשתמש בכל הרשתות", "en": "Handles on every network"}, "required": True,
     "constraints": {"note": "one line per network: 'x: digitaloffice'. Consistency is the point (umbrel, n8n and Notion all keep one handle)."},
     "targets": []},
    {"key": "identity.voice", "section": "identity", "group": "voice", "kind": "richtext",
     "label": {"he": "קול וטון", "en": "Voice & tone"},
     "constraints": {"note": "3-5 principles with a do/don't example each"}, "targets": []},
    {"key": "identity.illustration.renders", "section": "identity", "group": "illustration", "kind": "image",
     "label": {"he": "סגנון הדמיות מוצר", "en": "Product render style"},
     "constraints": {"note": "umbrel: glassy 3D device renders; Notion: hand-drawn black-and-white; n8n: dark UI captures"},
     "targets": [{"channel": "website"}, {"channel": "x"}, {"channel": "youtube"}]},
    {"key": "identity.illustration.motion", "section": "identity", "group": "illustration", "kind": "animation",
     "label": {"he": "שפת תנועה", "en": "Motion style"},
     "constraints": {"note": "the 2-3 s intro/outro sting and UI-transition style used in every video"},
     "targets": [{"channel": "youtube"}, {"channel": "x"}, {"channel": "website"}]},
    {"key": "identity.press-kit", "section": "identity", "group": "press", "kind": "file",
     "label": {"he": "ערכת עיתונות", "en": "Press kit"},
     "constraints": {"formats": ["ZIP"], "note": "logos (SVG/PNG, light/dark), product shots, founder photos, boilerplate"},
     "targets": [{"channel": "website"}, {"channel": "press"}]},
    {"key": "identity.founders", "section": "identity", "group": "people", "kind": "list",
     "label": {"he": "המייסדים", "en": "Founders"},
     "constraints": {"note": "name, role, one-line bio, photo, handles — the voices of every launch post"},
     "targets": [{"channel": "website"}, {"channel": "press"}]},
    {"key": "content.vision.manifesto", "section": "content", "group": "vision", "kind": "richtext",
     "label": {"he": "חזון / מניפסט", "en": "Vision / manifesto"}, "required": True,
     "constraints": {"note": "800-1500 words: the broken status quo, why now, our principles"},
     "targets": [{"channel": "website"}, {"channel": "blog"}]},
    {"key": "content.about.who-we-are", "section": "content", "group": "about", "kind": "richtext",
     "label": {"he": "מי אנחנו", "en": "Who we are"}, "required": True,
     "targets": [{"channel": "website"}, {"channel": "github"}, {"channel": "press"}]},
    {"key": "content.docs.home", "section": "content", "group": "docs", "kind": "link",
     "label": {"he": "תיעוד", "en": "Docs"}, "required": True,
     "targets": [{"channel": "website"}, {"channel": "github"}, {"channel": "discord"}]},
    {"key": "content.docs.tutorials", "section": "content", "group": "docs", "kind": "list",
     "label": {"he": "מדריכים", "en": "Tutorials"},
     "constraints": {"note": "one line per tutorial: title | link | video"},
     "targets": [{"channel": "website"}, {"channel": "youtube"}]},
    {"key": "content.app-store.listing", "section": "content", "group": "app-store", "kind": "list",
     "label": {"he": "טקסט לכל אפליקציה בחנות", "en": "Text for each app in the store"}, "required": True,
     "constraints": {"note": "per app: name, tagline (≤60), description, icon (256x256 SVG), 3-5 gallery images (1440x900), category, version, developer, website, support link, release notes — umbrel-app.yml's ~30 fields (research/umbrel.md), which n8n's integration pages and Notion's template listings also cover"},
     "targets": [{"channel": "app-store"}, {"channel": "website"}]},
    {"key": "content.releases.changelog", "section": "content", "group": "releases", "kind": "list",
     "label": {"he": "יומן גרסאות", "en": "Releases / changelog"}, "required": True,
     "constraints": {"note": "one entry per release: 'X.Y — <headline benefit>' + 3-7 bullets (n8n, Notion U1)"},
     "targets": [{"channel": "website"}, {"channel": "github"}, {"channel": "rss"}, {"channel": "email"}]},
    {"key": "content.newsletter.weekly", "section": "content", "group": "newsletter", "kind": "richtext",
     "label": {"he": "הניוזלטר השבועי", "en": "Weekly newsletter"},
     "targets": [{"channel": "email"}, {"channel": "website"}]},
    {"key": "content.news.press-release", "section": "content", "group": "news", "kind": "richtext",
     "label": {"he": "הודעה לעיתונות", "en": "Press release"},
     "targets": [{"channel": "press"}, {"channel": "website"}]},
    {"key": "content.website.home-hero", "section": "content", "group": "website", "kind": "text",
     "label": {"he": "כותרת דף הבית", "en": "Home page headline"}, "required": True,
     "constraints": {"max_len": 70}, "targets": [{"channel": "website"}]},
    {"key": "content.website.home-subtitle", "section": "content", "group": "website", "kind": "text",
     "label": {"he": "תת־כותרת דף הבית", "en": "Home page subtitle"},
     "constraints": {"max_len": 160}, "targets": [{"channel": "website"}]},
    {"key": "content.website.cta", "section": "content", "group": "website", "kind": "text",
     "label": {"he": "כפתור הפעולה הראשי", "en": "Primary call to action"},
     "constraints": {"max_len": 24}, "targets": [{"channel": "website"}]},
    {"key": "content.website.pricing", "section": "content", "group": "website", "kind": "richtext",
     "label": {"he": "עמוד תמחור", "en": "Pricing page"}, "targets": [{"channel": "website"}]},
    {"key": "content.community.guidelines", "section": "content", "group": "community", "kind": "richtext",
     "label": {"he": "כללי הקהילה", "en": "Community guidelines"},
     "targets": [{"channel": "discord"}, {"channel": "github"}]},
]


def unit_examples(u: dict) -> list:
    return [e for e in (u.get("examples") or []) if isinstance(e, str)][:3]


def build_startup_tail(skeleton: dict) -> dict:
    phases = []
    for ph in skeleton["phases"]:
        units = []
        for u in ph["units"] + EXTRA_UNITS.get(ph["id"], []):
            units.append({"id": u["id"], "name": {"he": UNIT_HE.get(u["id"], u["name"]), "en": u["name"]},
                          "purpose": u.get("purpose"), "trigger": u.get("trigger"),
                          "timing": u.get("timing"), "channels": u.get("channels") or [],
                          "assets": u.get("assets") or [], "copy": u.get("copy"),
                          "examples": unit_examples(u), **({"from": u["from"]} if u.get("from") else {})})
        phases.append({"id": ph["id"], "name": {"he": PHASE_HE.get(ph["id"], ph["name"]), "en": ph["name"]},
                       "order": ph["order"], "window": ph["window"], "units": units})
    return {
        "id": "startup-tail", "version": 1, "order": 2,
        "name": {"he": "זנב סטארט־אפ", "en": "Startup tail"},
        "summary": {"he": "סדרת המדיה שמוצר צעיר מפרסם כדי לחשוף את עצמו ואז את העדכונים שלו — "
                          "14 שלבים ו-" + str(sum(len(p['units']) for p in phases)) + " יחידות מדיה, "
                          "מחקר על umbrelOS, n8n, Notion ועוד עשר חברות",
                    "en": "The media series a young product publishes to reveal itself and then its "
                          "updates — derived from umbrelOS, n8n, Notion and ten more companies"},
        "extends": ["business-basic"],
        "sources": ["research/startup-patterns.md", "research/umbrel.md", "research/n8n.md",
                    "research/notion.md"],
        "params": [{"id": "launch_date", "kind": "date",
                    "label": {"he": "יום ההשקה (D0)", "en": "Launch day (D0)"}}],
        "slots": STARTUP_SLOTS, "phases": phases}


def header(title: str, src: str) -> str:
    return (f"# {title}\n# GENERATED by research/build_blueprints.py on {TODAY} from {src}.\n"
            "# Do not hand-edit: change the research (or the tables in the generator) and regenerate.\n")


def dump(path: Path, doc: dict, head: str) -> None:
    body = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110)
    path.write_text(head + body, encoding="utf-8")
    print(f"wrote {path.relative_to(HERE.parent.parent.parent)}  ({len(body) // 1024} KB)")


def main() -> int:
    biz = appendix("business-types.md", "# business-blueprints-input")
    by_id = {b["id"]: b for b in biz["blueprints"]}
    for bid, extra in (("business-basic", {}), ("basic-restaurant", {})):
        b = by_id[bid]
        doc = {"id": bid, "version": 1, "order": {"business-basic": 1, "basic-restaurant": 3}[bid],
               "name": {"he": b["name_he"], "en": b["name_en"]},
               "summary": {"he": {"business-basic": "כל הנכסים הדיגיטליים שעסק צריך כדי להתקיים כראוי ברשת ועל הנייר — זהות, תוכן, מדיה, ולוח שנה של חגי ישראל",
                                  "basic-restaurant": "מעל עסק בסיסי: תפריטים, תעודת כשרות, רישוי ושילוט, פלטפורמות משלוחים והזמנות, וצילומי מנות"}[bid],
                           "en": b["name_en"]},
               "extends": [b["extends"]] if b.get("extends") else [],
               "sources": ["research/business-types.md"],
               "slots": [convert_slot(s) for s in b["slots"]],
               "calendar": [convert_calendar(c) for c in b.get("calendar") or []]}
        dump(OUT / f"{bid}.yaml", doc, header(doc["name"]["he"], "research/business-types.md"))
    tail = build_startup_tail(appendix("startup-patterns.md", "# startup-tail-skeleton"))
    dump(OUT / "startup-tail.yaml", tail, header("זנב סטארט־אפ",
                                                  "research/startup-patterns.md + the company scans"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
