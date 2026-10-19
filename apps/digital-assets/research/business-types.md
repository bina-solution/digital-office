# Business blueprints for `digital-assets`: slot inventories (research)

> Research date: **2026-09-29**. Scope: two blueprints to ship now, **`business-basic`** and
> **`basic-restaurant`** (which extends `business-basic`), plus short notes on future blueprints.
> Every platform spec and legal requirement links to a source. **Unknown** means the value was not found or
> could not be verified. **(2nd)** means the number comes from a secondary source, either because the
> official page could not be fetched or because it does not state the number. The main open items are
> listed in §5.

## 0. Conventions

- **Key**: dotted kebab-case, `<section-root>.<group>.<item>[.<variant>]`. The roots map to the three
  sections: `identity.*` is **identification**, `content.*` is **content**, and `media.*` is **media**. A
  `basic-restaurant` slot with the same key as a `business-basic` slot **overrides** it.
- **Kinds**: text · rich-text · image · video · animation · color · file · document · link · list ·
  price-list · hours · address · phone. An email address is a `text` slot, an enum is a `text` slot with
  `enum`, and printable designs are `document` slots.
- **req.**: `yes` means the slot is needed for the business to exist properly online and on paper, or the law
  requires it. `no*` means the slot is conditionally required, and the condition appears in its constraints
  as **required if**. In the YAML appendix this is `required: false` plus `constraints.required_if`.
- **Targets** (channel ids): `website, google-search, gbp` (Google Business Profile), `apple-maps, bing, waze,
  b144, dapei-zahav, easy, facebook, instagram, whatsapp, youtube, x, tiktok, discord, linkedin, email,
  print, invoice, signage, premises-file`. The restaurant blueprint adds `wolt, tenbis` (10bis),
  `cibus, mishloha, tabit, ontopo, tripadvisor, rest` (rest.co.il).
- **Renewal / expiry**: `none` · `on-change` · ISO-8601 durations (`P1Y` from issue) · `per-holiday` ·
  `seasonal: …` · named rules (e.g. "TLV permit lapses 31 Dec").
- **Hebrew-calendar triggers** use the Hebrew date. Gregorian dates for 5787 (2026-27) are given as a check.
  Memorial days and Yom HaAtzmaut can move to avoid Shabbat, so take their dates from a calendar
  library and never hard-code them [S62].
- Sizes: `W x H` is in pixels unless the value says mm or cm. `rec` means recommended and `min` means
  minimum.
- Hebrew acronyms are written with the gershayim character (״), as in `בע״מ` and `ח״פ`, so they are safe in
  YAML and JSON.

## 1. Key facts at a glance

| Fact | Value | Source |
|---|---|---|
| GBP description | ≤750 chars; no URLs/HTML; no promotions or prices | [S02] |
| GBP categories | 1 primary + up to 9 additional | [S02] |
| GBP photos / video | JPG/PNG 10 KB-5 MB, rec 720x720, min 250x250 · video ≤30 s, ≤75 MB, ≥720p | [S01] |
| GBP posts | update / offer / event; archived after 6 months unless dated; ≤1,500 chars (2nd) | [S04] [S08] |
| WhatsApp profile | About 1-139 · description ≤512 (API; app reportedly 256) · address ≤256 · email ≤128 · ≤2 websites | [S15] [S80] |
| Instagram | bio 150 · feed kept at 1080 wide, 1.91:1-3:4 · stories 1080x1920 (2nd) | [S23] [S22] [S75] |
| YouTube | banner min 2048x1152, safe 1235x338, ≤6 MB · avatar renders 98x98 | [S20] |
| Open Graph image | ≥1200x630, min 600x315, ≤8 MB, ~1.91:1 | [S31] |
| Accessibility statement | reg. 35ה: prominent place; adjustments made + accessibility coordinator contact; IS 5568 = WCAG 2.0 AA | [S32] [S33] |
| Web-accessibility exemption | עוסק פטור or avg turnover ≤100,000 ₪ (35ו(ז)); conditional ≤1,000,000 ₪ (35ו(ט)) | [S32] |
| Tax invoice | serial no., 'חשבונית מס', 'מקור', name + address, עוסק מורשה no., date, details, price ± VAT, signature | [S34] |
| Allocation number | 9 digits, required above 5,000 ₪ before VAT from 1 Jun 2026 | [S36] [S37] |
| עוסק פטור ceiling 2026 | 122,833 ₪ | [S38] |
| Company name | must end with בערבון מוגבל / בע״מ (s.26) | [S39] |
| Kashrut certificate | 'כשר' in writing only with a certificate (s.3); display openly, only while valid (s.10); valid 1 year from issue (reg. 9) | [S47] [S48] |
| Private supervision | 'בהשגחה' / 'בפיקוח' wording, not 'כשר' (reform reversal pending at time of source) | [S50] |
| Pesach | separate Pesach certificate; chametz-display ban for business owners during Pesach | [S51] [S52] |
| Business license | default 15 years, may be shorter (s.7א) | [S53] |
| Restaurant price display | total price, ₪ only, visible place, legible numerals | [S54] [S55] |
| No-smoking signs | ≥20x30 cm, symbol ≥1/3, 1.80-2.20 m high, 1 per 10 m wall / per room | [S56] |
| Signage permit (Tel Aviv) | lapses 31 Dec yearly; Hebrew ≥ half the sign area | [S58] |
| Wolt menu photos | 16:9 landscape, ≤5 per item, no people/text/AI/multiple items; min 1000x563 (2nd) | [S63] [S64] |
| Spam law | consent; 'פרסומת' at start/subject; sender details; unsubscribe | [S43] [S44] |

## 2. Blueprint `business-basic` (עסק בסיסי)

Every digital asset a basic Israeli business needs to exist properly online and on paper. Slot counts: identification **69**, content **29**, media **11**.

### 2.1 Identification

| key | Hebrew label | English label | kind | constraints | req. | used in (targets) | renewal / expiry | source |
|---|---|---|---|---|---|---|---|---|
| `identity.logo.primary` | לוגו ראשי | Primary logo (horizontal lockup) | image | SVG/PNG; vector master + transparent PNG; Hebrew and Latin wordmark variants when the names differ; must read on light and dark backgrounds | yes | website, print, email, signage, invoice | none | — (convention) |
| `identity.logo.square` | לוגו ריבועי / אווטאר | Square logo / avatar | image | aspect 1:1; rec 1024x1024 master (Apple minimum); gbp: JPG/PNG 10 KB-5 MB, rec 720x720, min 250x250; apple-maps: square ≥1024x1024 HEIC/JPEG/PNG; linkedin: rec 400x400, min 268x268, PNG/JPEG ≤3 MB; youtube: renders 98x98; JPG/GIF/BMP/PNG, no animated GIF, ≤15 MB; x: 400x400; instagram: upload 320x320, shown 110x110 (2nd); tiktok: shown 200x200 (2nd); discord: icon rec 512x512 (2nd); facebook: shown 176x176 desktop / 196x196 phone (2nd); most platforms crop to a circle - keep the mark inside the inscribed circle | yes | gbp, apple-maps, facebook, instagram, whatsapp, youtube, x, tiktok, linkedin, discord | none | [S01], [S09], [S28], [S20], [S21], [S24], [S26], [S27], [S19] |
| `identity.logo.monochrome` | לוגו חד-צבעי (שחור / לבן) | Monochrome logo (black + white knockout) | image | SVG; single-colour versions for stamp, thermal receipts, B&W print, dark backgrounds | yes | print, invoice, signage | none | — (convention) |
| `identity.logo.favicon` | פביקון | Favicon | image | aspect 1:1; min 8x8; rec larger than 48x48; ICO/PNG/BMP/GIF/JPEG/PPM/TIFF; favicon URL must stay stable | yes | website, google-search | none | [S29] |
| `identity.logo.app-icon` | אייקון למסך הבית | App / home-screen icon | image | rec 192x192 and 512x512 PNG; add a maskable variant (purpose any maskable); iOS apple-touch-icon 180x180 reported by secondary sources (unverified) | no | website | none | [S30] |
| `identity.logo.animated` | לוגו מונפש | Animated logo sting | animation | no platform spec found (unknown); short intro/outro sting, MP4 or Lottie | no | youtube, instagram, tiktok, website | none | — (convention) |
| `identity.logo.video-watermark` | סימן מים לסרטונים | Video watermark | image | aspect 1:1; min 150x150; file <1 MB | no | youtube | none | [S20] |
| `identity.name.brand-he` | שם המותג בעברית | Brand name (Hebrew) | text | langs he; exactly as on signage/stationery; GBP forbids taglines, keywords, phone numbers, URLs and legal terms not on real signage | yes | website, gbp, apple-maps, bing, waze, b144, dapei-zahav, easy, facebook, instagram, whatsapp, print, signage, invoice | on-change | [S03] |
| `identity.name.brand-en` | שם המותג באנגלית | Brand name (English) | text | langs en; recommended; same naming rules as the Hebrew name | no | website, gbp, apple-maps, instagram, facebook, linkedin, print | on-change | [S03] |
| `identity.name.transliteration` | תעתיק לטיני של השם | Latin transliteration of the Hebrew name | text | basis for handle, domain and search variants | no | website, instagram, x, tiktok, youtube | on-change | — (convention) |
| `identity.name.legal` | שם משפטי רשום | Registered legal name | text | company name must end with 'בערבון מוגבל' or 'בע״מ' (Companies Law s.26); printed on tax invoices and legal pages | yes | invoice, print, website | on-change | [S39], [S34] |
| `identity.name.short` | שם תצוגה מקוצר | Short display name | text | ≤30 chars; fits the Instagram name field (30, 2nd) | no | instagram, x, tiktok, whatsapp | on-change | [S79] |
| `identity.slug` | מזהה (slug) וכינוי ברשתות | Slug / social handle | text | lowercase Latin + digits; one handle everywhere; Instagram username ≤30 (2nd); other platforms' limits unknown - check when claiming | yes | website, instagram, facebook, x, tiktok, youtube, linkedin | on-change | [S79] |
| `identity.domain` | דומיין | Web domain | link | .co.il / .com; renewal period per registrar (unknown) | yes | website, email | registrar term (renew) | — (convention) |
| `identity.legal.entity-type` | סוג העוסק | Business entity type | text | one of: עוסק פטור, עוסק מורשה, חברה בע״מ, שותפות, עמותה; drives document types: עוסק פטור cannot issue a חשבונית מס; 2026 עוסק פטור ceiling 122,833 ₪ turnover | yes | invoice, website | on-change (check turnover yearly) | [S34], [S38] |
| `identity.legal.business-number` | מספר עוסק / ח״פ | Business ID (VAT dealer no. / company no.) | text | mandatory on tax invoices; company number is 9 digits (2nd) | yes | invoice, print, website | none | [S34], [S40] |
| `identity.contact.address` | כתובת העסק | Business address | address | langs he+en; precise physical location, no P.O. boxes; mandatory on tax invoices; service-area businesses hide it on GBP | yes | gbp, apple-maps, bing, waze, b144, dapei-zahav, easy, website, invoice, print | on-change | [S03], [S34] |
| `identity.contact.map-pin` | נעיצה במפה | Map pin + entrance note | address | **required if:** customers visit the premises; lat/lng + entrance/parking hint; adding a Waze place from the app needs a storefront photo and volunteer review | no* | gbp, waze, apple-maps | on-change | [S11] |
| `identity.contact.phone` | טלפון ראשי | Main phone | phone | E.164 (+972...); a local number, not a redirect/referral number; GBP: primary + up to 2 more | yes | gbp, website, print, invoice, b144, dapei-zahav, easy, facebook | on-change | [S02], [S03] |
| `identity.contact.whatsapp` | מספר וואטסאפ עסקי | WhatsApp Business number | phone | number registered to WhatsApp Business; publish as a wa.me click-to-chat link and QR | yes | whatsapp, website, instagram, facebook, print | on-change | [S16] |
| `identity.contact.email` | דוא״ל עסקי | Business email | text | own-domain address; WhatsApp profile email ≤128 chars | yes | website, whatsapp, invoice, print, email | on-change | [S15] |
| `identity.contact.website-url` | כתובת האתר | Website URL | link | full URL with https://; WhatsApp profile: up to 2 websites, ≤256 chars each | yes | gbp, whatsapp, instagram, facebook, print, email | on-change | [S02], [S15] |
| `identity.hours.regular` | שעות פעילות קבועות | Regular opening hours | hours | per weekday Sun-Sat incl. Friday short day and Shabbat closure; customer-facing hours only | yes | gbp, apple-maps, bing, website, whatsapp, signage, facebook | on-change | [S02], [S03] |
| `identity.hours.special` | שעות מיוחדות (חגים וערבי חג) | Special hours (holidays, holiday eves, memorial days) | hours | per date, set ahead of every Jewish/Israeli holiday (Hebrew-calendar driven); feeds GBP special hours | yes | gbp, website, whatsapp, facebook, instagram | per-holiday | [S02], [S62] |
| `identity.hours.more` | שעות לפי שירות | Per-service hours (delivery, takeout, pickup, phone) | hours | GBP 'more hours' | no | gbp | on-change | [S02], [S06] |
| `identity.hours.shabbat-policy` | מדיניות שבת וחג | Shabbat & holiday observance | text | one of: closed, open, partial; drives away-message and special-hours automation | no | website, gbp, whatsapp | on-change | — (convention) |
| `identity.opening-date` | תאריך פתיחה | Opening date | text | month + year; may be set up to 1 year ahead; Google shows it from 90 days before | no | gbp | none | [S02] |
| `identity.tagline` | סלוגן | Tagline | text | langs he+en; ≤80 chars; self-imposed ≤80 so it fits the shortest bio (TikTok 80, 2nd) | no | website, print, instagram, x, tiktok, signage | on-change | [S25] |
| `identity.description.short` | תיאור קצר | Short description | text | langs he+en; ≤139 chars; WhatsApp About is 1-139 chars; also fits the Instagram bio (150) | yes | whatsapp, instagram, x, tiktok, facebook, b144, easy | on-change | [S15], [S23] |
| `identity.description.medium` | תיאור בינוני | Medium description | text | langs he+en; ≤256 chars; WhatsApp Business app description reportedly 256 (2nd); API description ≤512 | no | whatsapp, facebook, youtube, linkedin | on-change | [S15], [S80] |
| `identity.description.long` | תיאור מלא | Long description | text | langs he+en; ≤750 chars; GBP: no URLs or HTML; describe the business, not promotions or prices | yes | gbp, bing, apple-maps, b144, dapei-zahav, easy, website | on-change | [S02] |
| `identity.terminology` | מילון מונחים | Terminology / glossary | list | langs he+en; he↔en term pairs, preferred spellings, words to avoid, gender-inclusive forms | no | website, email, print | on-change | — (convention) |
| `identity.color.primary` | צבע ראשי | Primary colour | color | HEX/RGB + CMYK/Pantone for print; text on it needs WCAG 2.0 AA contrast 4.5:1 (IS 5568 is based on WCAG 2.0 AA) | yes | website, print, signage, instagram, facebook | on-change | [S33], [S76] |
| `identity.color.secondary` | צבעים משניים | Secondary colours | color | same contrast rule for any text colour pair | no | website, print, signage | on-change | [S76] |
| `identity.color.neutral` | צבעי רקע וטקסט | Neutral / background / text colours | color |  | no | website, print | on-change | [S76] |
| `identity.theme.typography` | גופנים | Typography (Hebrew + Latin fonts) | file | font files + license; a Hebrew-capable family paired with a Latin face | no | website, print | license term | — (convention) |
| `identity.theme.tokens` | ערכת עיצוב (tokens) | Theme tokens (light / dark) | file | JSON design tokens: colours, radii, spacing, light + dark | no | website | on-change | — (convention) |
| `identity.illustration.style` | סגנון איור ואייקונים | Illustration & icon style | image | SVG; reference set of illustrations / icons | no | website, instagram, print | on-change | — (convention) |
| `identity.profile.gbp.category-primary` | קטגוריה ראשית ב-Google | GBP primary category | text | exactly one; what the business IS, not what it HAS | yes | gbp | on-change | [S02], [S03] |
| `identity.profile.gbp.categories-extra` | קטגוריות נוספות ב-Google | GBP additional categories | list | up to 9; use as few as possible | no | gbp | on-change | [S02], [S03] |
| `identity.profile.gbp.attributes` | מאפיינים (Attributes) | GBP attributes | list | factual attributes (e.g. outdoor seating, accessibility); available set depends on category - full list unknown | no | gbp | on-change | [S02] |
| `identity.profile.gbp.service-area` | אזור שירות | Service area | list | **required if:** service-area business without a storefront; cities / postal codes / places served | no* | gbp | on-change | [S02], [S03] |
| `identity.profile.gbp.cover` | תמונת נושא ב-Google | GBP cover photo | image | min 250x250; rec 720x720; JPG/PNG; 10 KB-5 MB; cover crop aspect not specified by Google (unknown) | yes | gbp | on-change | [S01] |
| `identity.profile.gbp.url` | קישור לפרופיל Google וקישור לביקורת | GBP profile URL + review link | link | store place ID / URL and a short review link (for QR) | yes | website, whatsapp, email, print | none | — (convention) |
| `identity.listing.apple-maps` | כרטיס מקום ב-Apple Maps | Apple Business place card | link |  | no | apple-maps | none | [S09] |
| `identity.profile.apple-maps.cover` | תמונת נושא ל-Apple Maps | Apple Maps cover photo | image | min 1600x1040; HEIC/JPEG/PNG | no | apple-maps | on-change | [S09] |
| `identity.listing.bing` | Bing Places | Bing Places listing | link | can be imported from the Google profile | no | bing | none | [S10] |
| `identity.listing.waze` | מקום ב-Waze | Waze place | link | **required if:** customers drive to the premises | no* | waze | none | [S11] |
| `identity.listing.b144` | רישום ב-B144 | B144 listing | link | free self-registration | no | b144 | none | [S13] |
| `identity.listing.dapei-zahav` | רישום בדפי זהב | Dapei Zahav (d.co.il) listing | link | free basic listing | no | dapei-zahav | none | [S12] |
| `identity.listing.easy` | רישום באיזי | Easy (easy.co.il) listing | link |  | no | easy | none | [S14] |
| `identity.profile.facebook.page` | עמוד פייסבוק | Facebook Page | link |  | yes | facebook | none | — (convention) |
| `identity.profile.facebook.cover` | תמונת נושא בפייסבוק | Facebook cover | image | displays 820x312 on computers and 640x360 on phones (different crops); 851x315 JPG <100 KB loads fastest (2nd) | yes | facebook | on-change | [S18], [S19] |
| `identity.profile.facebook.intro` | תיאור (Intro) בפייסבוק | Facebook intro / bio | text | langs he; limit not verified (unknown) - reuse identity.description.short | yes | facebook | on-change | — (convention) |
| `identity.profile.instagram.account` | חשבון אינסטגרם עסקי | Instagram business account | link |  | yes | instagram | none | — (convention) |
| `identity.profile.instagram.bio` | ביו באינסטגרם | Instagram bio | text | langs he+en; ≤150 chars | yes | instagram | on-change | [S23] |
| `identity.profile.instagram.highlight-covers` | כיסויי הדגשות (Highlights) | Story highlight covers | image | story canvas 1080x1920 9:16 (2nd); icon shown as a circle | no | instagram | on-change | [S75] |
| `identity.profile.whatsapp.category` | קטגוריה בוואטסאפ | WhatsApp business category | text | vertical enum, e.g. RESTAURANT, RETAIL, PROF_SERVICES, BEAUTY, HEALTH, EDU, OTHER | yes | whatsapp | on-change | [S15] |
| `identity.profile.whatsapp.about` | אודות (About) בוואטסאפ | WhatsApp About line | text | ≤139 chars; 1-139 chars; links not clickable | yes | whatsapp | on-change | [S15] |
| `identity.profile.whatsapp.description` | תיאור העסק בוואטסאפ | WhatsApp business description | text | ≤512 chars; API limit 512; app field reportedly 256 (2nd) - author to 256 | yes | whatsapp | on-change | [S15], [S80] |
| `identity.profile.whatsapp.address` | כתובת בוואטסאפ | WhatsApp address | address | ≤256 chars | no | whatsapp | on-change | [S15] |
| `identity.profile.whatsapp.photo` | תמונת פרופיל בוואטסאפ | WhatsApp profile photo | image | derived from identity.logo.square; WhatsApp's own size spec unknown | yes | whatsapp | on-change | — (convention) |
| `identity.profile.youtube.banner` | באנר ערוץ יוטיוב | YouTube channel banner | image | aspect 16:9; min 2048x1152; rec 2560x1440; ≤6 MB; safe area for text/logo 1235x338 | no | youtube | on-change | [S20] |
| `identity.profile.x.header` | באנר ב-X | X header image | image | rec 1500x500 | no | x | on-change | [S21] |
| `identity.profile.x.bio` | ביו ב-X | X bio | text | ≤160 chars | no | x | on-change | [S21] |
| `identity.profile.tiktok.bio` | ביו בטיקטוק | TikTok bio | text | ≤80 chars; some accounts get 160 (2nd); author to 80 | no | tiktok | on-change | [S25] |
| `identity.profile.discord.banner` | באנר שרת דיסקורד | Discord server banner | image | aspect 16:9; min 960x540; (2nd); needs a server boost level | no | discord | on-change | [S27] |
| `identity.profile.linkedin.cover` | תמונת נושא בלינקדאין | LinkedIn Page cover | image | rec 1512x256; PNG/JPEG; ≤3 MB; minimum is also 1512x256; logo shown on light and dark backgrounds | no | linkedin | on-change | [S28] |
| `identity.profile.link-in-bio` | עמוד קישורים (Link in bio) | Link-in-bio page | link | own website page (e.g. /links): WhatsApp, booking/ordering, reviews; per-platform link counts not verified | no | instagram, tiktok, x, facebook | on-change | — (convention) |

### 2.2 Content

| key | Hebrew label | English label | kind | constraints | req. | used in (targets) | renewal / expiry | source |
|---|---|---|---|---|---|---|---|---|
| `content.about.story` | אודות / הסיפור שלנו | About / our story | rich-text | langs he+en | yes | website, facebook, linkedin | on-change | — (convention) |
| `content.about.owner` | על הבעלים | Owner / founder bio | rich-text | langs he+en | no | website, linkedin | on-change | — (convention) |
| `content.about.vision` | חזון וערכים | Vision & values | rich-text | langs he+en | no | website | on-change | — (convention) |
| `content.catalog.services` | שירותים ומחירים | Services & prices | price-list | item fields: name (GBP ≤80), description (GBP ≤300, 2nd), price ₪, duration / unit; prices shown as the total price incl. VAT (Consumer Protection s.17ד) | yes | website, gbp, whatsapp, facebook | on-change | [S07], [S55] |
| `content.catalog.products` | מוצרים | Products | price-list | item fields: name (GBP ≤58), description (GBP ≤1,000), price ₪ (total), photos, link, code; **required if:** the business sells goods; WhatsApp catalog ≤500 items and ≤10 images per item (2nd); GBP Products via POS listed for US/CA/UK/IE - Israel availability unknown | no* | website, gbp, whatsapp, instagram, facebook | on-change | [S07], [S17], [S55], [S02] |
| `content.faq` | שאלות ותשובות | FAQ (question/answer pairs) | list | langs he+en | no | website, whatsapp, gbp | on-change | — (convention) |
| `content.website.home` | דף הבית | Home page copy | rich-text | langs he+en; headline, sub-headline, primary CTA (WhatsApp / call / book), trust signals; RTL-first | yes | website | on-change | — (convention) |
| `content.website.services` | דף שירותים / מוצרים | Services / products page | rich-text | rendered from content.catalog.* | yes | website | on-change | — (convention) |
| `content.website.contact` | דף יצירת קשר | Contact page | rich-text | address + map, phone, WhatsApp link, hours, form; a form collecting personal data needs a privacy notice (duty to inform) | yes | website | on-change | [S45] |
| `content.website.privacy-policy` | מדיניות פרטיות | Privacy policy | document | **required if:** the site/app collects personal data (forms, analytics, pixels); Amendment 13 in force 14 Aug 2025: state purpose, controller identity + contact, whether providing data is a legal duty, data-subject rights (2nd detail) | no* | website | on-change | [S45] |
| `content.website.terms` | תקנון / תנאי שימוש | Terms of use / sale | document | langs he; **required if:** selling or booking online | no* | website | on-change | — (convention) |
| `content.website.accessibility-statement` | הצהרת נגישות | Accessibility statement | document | reg. 35ה: prominent place on site/app, the accessibility adjustments made + accessibility coordinator details and contact; usual fields: level (IS 5568 = WCAG 2.0 AA), browsers tested, exemptions, last update; exempt from web adjustments: עוסק פטור or avg turnover ≤100,000 ₪ (35ו(ז)), conditional ≤1,000,000 ₪ (35ו(ט)); statement duty for exempt businesses unknown | yes | website | on-change (shows last-update date) | [S32], [S33] |
| `content.website.cookie-notice` | הודעת עוגיות (Cookies) | Cookie notice / consent | text | **required if:** non-essential cookies or ad pixels are used; Privacy Protection Authority 2020 draft recommendation: explicit opt-in; binding status after Amendment 13 unknown | no* | website | on-change | [S46] |
| `content.website.seo-meta` | כותרות ותיאורי מטא | SEO titles & meta descriptions | text | langs he+en; per page; hard length limits unknown | yes | website, google-search | on-change | — (convention) |
| `content.docs.business-card` | כרטיס ביקור | Business card | document | 90x50 mm common in Israel (2nd); print PDF with printer-specific bleed; Hebrew front / English back | yes | print | on-change | [S41] |
| `content.docs.letterhead` | נייר מכתבים | Letterhead | document | A4 210x297 mm; legal name (company with בע״מ), business number, address, contacts | no | print, email | on-change | [S42], [S39] |
| `content.docs.invoice-header` | כותרת חשבונית / קבלה | Invoice / receipt header | document | tax invoice: serial no., the words 'חשבונית מס', 'מקור' / 'נאמן למקור', business name + address, עוסק מורשה no., date, transaction details, price without and with VAT, signature; 9-digit allocation no. (מספר הקצאה) for invoices above 5,000 ₪ before VAT from 1 Jun 2026; עוסק פטור issues receipts / transaction invoices only | yes | invoice, email | on-change (allocation threshold changes by date) | [S34], [S35], [S36], [S37] |
| `content.docs.email-signature` | חתימת דוא״ל | Email signature | rich-text | HTML: name, role, phone, WhatsApp link, address, logo with alt text; pixel spec unknown | yes | email | on-change | — (convention) |
| `content.docs.stamp` | חותמת עסק | Business stamp | image | legal name + business number (+ address); no legal requirement found (unknown) | no | print, invoice | on-change | — (convention) |
| `content.reviews.testimonials` | המלצות לקוחות | Testimonials | list | quote, name/initials with consent, date, source link | no | website, facebook, instagram | on-change | — (convention) |
| `content.reviews.request` | בקשת ביקורת | Review-request message | text | langs he; template + short Google review link + QR | no | whatsapp, email, print | on-change | — (convention) |
| `content.reviews.replies` | תבניות מענה לביקורות | Review reply templates | list | langs he+en | no | gbp, facebook | on-change | — (convention) |
| `content.gbp.posts` | פוסטים בפרופיל Google | GBP posts (update / offer / event) | rich-text | offer needs title + dates/times; ≤1,500 chars (2nd); archived after 6 months unless a date range is set | no | gbp | P6M (archived) | [S04], [S08] |
| `content.newsletter.template` | תבנית ניוזלטר | Newsletter template | rich-text | prior consent; the word 'פרסומת' at the start / in the subject; sender name, address, contact; unsubscribe in every message | no | email | on-change | [S43], [S44] |
| `content.newsletter.consent` | נוסח הסכמה לדיוור | Marketing-consent wording | text | **required if:** sending marketing messages (email / SMS / WhatsApp) | no* | website, whatsapp | on-change | [S43] |
| `content.whatsapp.greeting` | הודעת פתיחה בוואטסאפ | WhatsApp greeting message | text | langs he+en; length limit unknown | no | whatsapp | on-change | — (convention) |
| `content.whatsapp.away` | הודעת היעדרות בוואטסאפ | WhatsApp away message | text | tied to hours + Shabbat policy | no | whatsapp | per-holiday | — (convention) |
| `content.whatsapp.quick-replies` | תשובות מהירות | WhatsApp quick replies | list |  | no | whatsapp | on-change | — (convention) |
| `content.news` | חדשות ועדכונים | News & announcements | rich-text |  | no | website, facebook, gbp | none | — (convention) |

### 2.3 Media

| key | Hebrew label | English label | kind | constraints | req. | used in (targets) | renewal / expiry | source |
|---|---|---|---|---|---|---|---|---|
| `media.photo.storefront` | חזית העסק | Storefront / exterior | image | min 250x250; rec 720x720; JPG/PNG; **required if:** customers visit the premises; 10 KB-5 MB, in focus, no heavy filters; sign readable; Waze place creation needs one | no* | gbp, waze, apple-maps, website, b144, easy | yearly refresh (recommended) | [S01], [S11] |
| `media.photo.interior` | פנים העסק | Interior | image | **required if:** customers visit the premises; GBP photo spec | no* | gbp, website, facebook | yearly refresh (recommended) | [S01] |
| `media.photo.team` | צוות | Team | image | GBP photo spec | no | gbp, website, linkedin | on-change | [S01] |
| `media.photo.owner-portrait` | דיוקן בעלים | Owner portrait | image | square-safe + 4:5 crop; Instagram keeps 1080-wide images between 1.91:1 and 3:4 | no | website, linkedin, facebook, instagram | on-change | [S22] |
| `media.photo.products` | מוצרים / דוגמאות עבודה | Products / work samples | image | GBP spec; WhatsApp catalog ≤10 images per item (2nd) | yes | gbp, website, whatsapp, instagram, facebook | on-change | [S01], [S17], [S22] |
| `media.photo.at-work` | העסק בפעולה | At work / service in action | image |  | no | gbp, website, instagram | on-change | [S01] |
| `media.image.social-share` | תמונת שיתוף (Open Graph) | Social-share image (Open Graph) | image | aspect 1.91:1; min 600x315 (large preview); 200x200 absolute; rec 1200x630; ≤8 MB | yes | website, facebook, whatsapp, linkedin, x | on-change | [S31] |
| `media.image.post-templates` | תבניות פוסט וסטורי | Post & story templates | image | feed 1080 wide within 1.91:1-3:4 (e.g. 1080x1350); story/reel 1080x1920 (2nd) | no | instagram, facebook, whatsapp | on-change | [S22], [S75] |
| `media.image.qr-codes` | קודי QR | QR codes (WhatsApp chat, review link, website) | image | SVG | no | print, signage | on-change | — (convention) |
| `media.video.intro` | סרטון היכרות | Intro video | video | GBP: ≤30 s, ≤75 MB, ≥720p; vertical 1080x1920 cut for reels/stories (2nd) | no | gbp, website, youtube, instagram, facebook, tiktok | on-change | [S01], [S75] |
| `media.video.shorts` | סרטונים קצרים אנכיים | Short vertical videos | video | aspect 9:16; rec 1080x1920; (2nd) | no | instagram, tiktok, youtube, facebook | none | [S75] |

### 2.4 Recurring content calendar: `business-basic`

Asset shorthand: IG feed image = 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]; story = 1080x1920 (9:16) [S75]; GBP image = JPG/PNG 10 KB-5 MB, rec 720x720, min 250x250 [S01].

| unit | Hebrew name | trigger / date | channels | assets (kind: spec × count) | notes | source |
|---|---|---|---|---|---|---|
| `rosh-hashana` | ראש השנה | hebrew 1-2 Tishrei (5787: 12-13 Sep 2026); hours −14d; post −3d | gbp, instagram, facebook, whatsapp, email, website | hours: GBP special hours: erev chag + 2 days × 1<br>image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1<br>image: 1080x1920 (9:16) [S75] × 1<br>text: greeting he (+en) × 1<br>rich-text: newsletter; 'פרסומת' in subject if promotional [S43] × 1 | greeting + holiday hours | [S62], [S02], [S43] |
| `yom-kippur` | יום כיפור | hebrew 10 Tishrei (5787: 21 Sep 2026); hours −14d | gbp, whatsapp, website, instagram | hours: GBP special hours (closed) × 1<br>text: WhatsApp away message × 1<br>image: 1080x1920 (9:16) [S75] × 1 | closure notice; no promotions | [S62] |
| `sukkot` | סוכות ושמחת תורה | hebrew 15-22 Tishrei (5787: 26 Sep-3 Oct 2026) | gbp, instagram, facebook, whatsapp | hours: chol hamoed + chag hours × 1<br>image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1<br>image: 1080x1920 (9:16) [S75] × 1 |  | [S62] |
| `hanukkah` | חנוכה | hebrew 25 Kislev, 8 days (5787: 5-12 Dec 2026) | gbp, instagram, facebook, whatsapp, email | image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1<br>image: 1080x1920 (9:16) [S75] × 8<br>rich-text: GBP offer post: title + dates [S04] × 1 | greeting + optional 8-day campaign | [S62], [S04] |
| `tu-bishvat` | ט״ו בשבט | hebrew 15 Shevat (5787: 23 Jan 2027) | instagram, facebook | image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1 |  | [S62] |
| `purim` | פורים | hebrew 14 Adar (Adar II in leap years; 15 in Jerusalem) (5787: 23 Mar 2027) | gbp, instagram, facebook, whatsapp | image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1<br>image: 1080x1920 (9:16) [S75] × 2 |  | [S62] |
| `pesach` | פסח | hebrew 15-21 Nisan (5787: 22-28 Apr 2027); sale −21d; hours −14d | gbp, instagram, facebook, whatsapp, email, website | hours: GBP special hours for chag + chol hamoed × 1<br>image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 2<br>image: 1080x1920 (9:16) [S75] × 3<br>rich-text: pre-holiday sale newsletter [S43] × 1 |  | [S62], [S43] |
| `yom-hashoah` | יום הזיכרון לשואה ולגבורה | hebrew 27 Nisan (may shift; 5787: 4 May 2027) | instagram, facebook, website | text: memorial message, no promotion × 1<br>hours: eve-of-day hours × 1 | cafés close on the eve by law (per municipal notices) | [S62], [S60] |
| `yom-hazikaron` | יום הזיכרון לחללי מערכות ישראל | hebrew 4 Iyar (may shift; 5787: 11 May 2027) | instagram, facebook, website | text: memorial message, no promotion × 1<br>hours: eve-of-day hours × 1 | eve closures per municipal notice | [S62], [S61] |
| `yom-haatzmaut` | יום העצמאות | hebrew 5 Iyar (may shift; 5787: 12 May 2027) | gbp, instagram, facebook, whatsapp | image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1<br>image: 1080x1920 (9:16) [S75] × 1<br>hours: GBP special hours × 1 |  | [S62] |
| `shavuot` | שבועות | hebrew 6 Sivan (5787: 11 Jun 2027) | gbp, instagram, facebook, whatsapp | image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1<br>hours: GBP special hours × 1 |  | [S62] |
| `tisha-bav` | תשעה באב | hebrew 9 Av (Sunday if Shabbat) (5787: 12 Aug 2027) | gbp, whatsapp, website | hours: eve + day hours × 1 | no promotions; eating places may be closed on the eve by municipal bylaw | [S62], [S59] |
| `tu-bav` | ט״ו באב | hebrew 15 Av (5787: 18 Aug 2027) | instagram, facebook, whatsapp | image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1<br>image: 1080x1920 (9:16) [S75] × 1 | optional 'love day' promotion | [S62] |
| `back-to-school` | חזרה ללימודים | Israeli school-year opening (date set yearly by the Ministry of Education - verify); −21d | instagram, facebook, email | image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1<br>rich-text: newsletter [S43] × 1 | retail-relevant; optional | [S43] |
| `black-friday` | בלאק פריידיי / סייבר מאנדיי | rule: Friday after the 4th Thursday of November, + following Monday | gbp, instagram, facebook, whatsapp, email | image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 2<br>image: 1080x1920 (9:16) [S75] × 3<br>rich-text: GBP offer post [S04] × 1 | optional | [S04] |
| `weekly-shabbat` | שבת שלום / סוף שבוע | weekly: Friday, before closing | instagram, whatsapp | image: 1080x1920 (9:16) [S75] × 1 | weekend hours reminder | — (convention) |
| `monthly-newsletter` | ניוזלטר חודשי | monthly | email | rich-text: newsletter template (spam-law compliant) [S43] × 1 |  | [S43] |
| `quarterly-gbp-refresh` | רענון פרופיל Google | quarterly | gbp | image: JPG/PNG 10 KB-5 MB, rec 720x720, min 250x250 [S01] × 3<br>rich-text: GBP post text ≤1,500 chars (2nd) [S08] × 1 | fresh photos + a post; posts older than 6 months are archived [S04] | [S01], [S04] |
| `yearly-compliance` | בדיקת ציות שנתית | yearly: January | website, invoice | document: accessibility statement re-check, last-update date [S32] × 1<br>document: privacy policy review [S45] × 1<br>document: invoice header vs allocation-number threshold [S36] × 1<br>text: עוסק פטור ceiling check [S38] × 1 |  | [S32], [S45], [S36], [S38] |
| `business-anniversary` | יום הולדת לעסק | yearly on identity.opening-date | gbp, instagram, facebook, whatsapp, email | image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1<br>image: 1080x1920 (9:16) [S75] × 1 |  | [S02] |

## 3. Blueprint `basic-restaurant` (מסעדה בסיסית), extends `business-basic`

Everything a restaurant needs **on top of** `business-basic`. Rows whose key already exists in `business-basic` are **overrides**: `identity.profile.gbp.category-primary`, `identity.profile.whatsapp.category` and `media.photo.products`. Slot counts: identification **24**, content **37**, media **10**.

### 3.1 Identification

| key | Hebrew label | English label | kind | constraints | req. | used in (targets) | renewal / expiry | source |
|---|---|---|---|---|---|---|---|---|
| `identity.profile.gbp.category-primary` | קטגוריה ראשית ב-Google (מסעדה) | GBP primary category (restaurant) | text | override: a restaurant / cuisine category; restaurant hours = when diners can sit down and dine | yes | gbp | on-change | [S03], [S06] |
| `identity.profile.whatsapp.category` | קטגוריה בוואטסאפ | WhatsApp business category | text | one of: RESTAURANT; override | yes | whatsapp | on-change | [S15] |
| `identity.restaurant.cuisines` | סוגי מטבח | Cuisine types | list | map to each platform's taxonomy | yes | gbp, wolt, tenbis, rest, tripadvisor, website | on-change | [S02], [S70] |
| `identity.restaurant.kashrut-status` | סטטוס כשרות | Kashrut status | text | one of: not-kosher, kosher-rabbinate, kosher-rabbinate-mehadrin, private-supervision-only; only a certificate holder may present the place as 'כשר' in writing (s.3); private supervision alone: 'בהשגחה' / 'בפיקוח', not 'כשר' | yes | website, gbp, wolt, tenbis, mishloha, rest, tabit, ontopo, signage | on-change | [S47], [S50] |
| `identity.restaurant.kashrut-class` | סיווג: חלבי / בשרי / פרווה | Kashrut class (dairy / meat / pareve) | text | one of: חלבי, בשרי, פרווה; **required if:** kosher or supervised | no* | website, wolt, tenbis, rest | on-change | [S49] |
| `identity.restaurant.service-modes` | אופני שירות | Service modes | list | one of: dine-in, takeaway, pickup, delivery, catering | yes | gbp, website, wolt, tenbis | on-change | [S06] |
| `identity.restaurant.seating` | ישיבה וקיבולת | Seating & capacity | list | indoor / outdoor / sukkah / private room + seats; GBP attribute example: outdoor seating; Rest filters private rooms | no | gbp, rest, tabit, ontopo, website | on-change | [S02], [S70] |
| `identity.restaurant.accessibility` | נגישות המקום | Premises accessibility | list | entrance, restroom, seating; mirrored in the accessibility statement | yes | gbp, website, rest | on-change | [S02], [S32] |
| `identity.restaurant.price-range` | טווח מחירים | Price range | text | per-platform scale; GBP price-range field details unknown | no | gbp, rest, tripadvisor | on-change | [S70] |
| `identity.hours.kitchen` | שעות מטבח (הזמנה אחרונה) | Kitchen hours (last order) | hours | GBP restaurant hours = when diners can sit down and dine | yes | gbp, website, tabit, ontopo | on-change | [S03] |
| `identity.hours.delivery` | שעות משלוחים | Delivery hours | hours | **required if:** offers delivery | no* | gbp, wolt, tenbis, mishloha | on-change | [S06] |
| `identity.hours.takeaway` | שעות טייק-אווי / איסוף | Takeaway / pickup hours | hours | **required if:** offers takeaway | no* | gbp | on-change | [S06] |
| `identity.hours.business-lunch` | שעות עסקית | Business-lunch hours | hours |  | no | website, gbp, tenbis | on-change | — (convention) |
| `identity.links.menu` | קישור לתפריט | Menu URL | link |  | yes | gbp, instagram, facebook, whatsapp, rest | on-change | [S06] |
| `identity.links.order` | קישור להזמנה אונליין | Order-online link | link | Order with Google or platform ordering link | no | gbp, instagram, website | on-change | [S06] |
| `identity.links.reservations` | קישור להזמנת שולחן | Reservation link | link | **required if:** takes reservations; Tabit / Ontopo booking page; Reserve with Google availability in Israel unknown | no* | gbp, website, instagram, facebook | on-change | [S06], [S67], [S68] |
| `identity.listing.wolt` | עמוד בוולט | Wolt venue page | link |  | no | wolt | none | [S63] |
| `identity.listing.tenbis` | עמוד בתן ביס | 10bis page | link |  | no | tenbis | none | [S65] |
| `identity.listing.cibus` | סיבוס פלאקסי | Cibus Pluxee listing | link |  | no | cibus | none | [S66] |
| `identity.listing.mishloha` | משלוחה | Mishloha listing | link |  | no | mishloha | none | [S66] |
| `identity.listing.tabit` | טאביט | Tabit listing | link |  | no | tabit | none | [S68] |
| `identity.listing.ontopo` | אונטופו | Ontopo listing | link |  | no | ontopo | none | [S67] |
| `identity.listing.tripadvisor` | טריפאדוויזר | Tripadvisor listing | link |  | no | tripadvisor | none | [S69] |
| `identity.listing.rest` | רסט (Rest) | Rest (rest.co.il) listing | link |  | no | rest | none | [S70] |

### 3.2 Content

| key | Hebrew label | English label | kind | constraints | req. | used in (targets) | renewal / expiry | source |
|---|---|---|---|---|---|---|---|---|
| `content.menu.dine-in` | תפריט במקום | Dine-in menu | price-list | item fields: name he/en, description he/en, section, price ₪ (total), variants/portions, photos, allergens, dietary tags, spice level, kashrut class, availability (days/hours), popular flag, code/SKU; GBP menu editor holds sections, items, descriptions, prices; prices are total prices in ₪ incl. VAT | yes | website, gbp, print, rest, tabit, ontopo | on-change | [S05], [S54], [S55] |
| `content.menu.takeaway` | תפריט טייק-אווי | Takeaway menu | price-list | item fields: name he/en, description he/en, section, price ₪ (total), variants/portions, photos, allergens, dietary tags, spice level, kashrut class, availability (days/hours), popular flag, code/SKU | no | website, gbp, print | on-change | [S55] |
| `content.menu.delivery` | תפריט משלוחים | Delivery menu | price-list | item fields: name he/en, description he/en, section, price ₪ (total), variants/portions, photos, allergens, dietary tags, spice level, kashrut class, availability (days/hours), popular flag, code/SKU; **required if:** offers delivery; synced to platforms; one photo per item per platform spec | no* | wolt, tenbis, mishloha, cibus, website | on-change | [S63] |
| `content.menu.kids` | תפריט ילדים | Kids menu | price-list |  | no | website, print | on-change | — (convention) |
| `content.menu.drinks` | תפריט משקאות ויין | Drinks & wine list | price-list | alcohol: licensing item 4.8 conditions; Business Licensing Law s.2(א1) restricts selling/serving/supplying alcohol 23:00-06:00 with exceptions - verify scope for on-premise service | no | website, print, gbp | on-change | [S53], [S57] |
| `content.menu.desserts` | תפריט קינוחים | Desserts menu | price-list |  | no | website, print | on-change | — (convention) |
| `content.menu.business-lunch` | תפריט עסקית | Business-lunch menu (עסקית) | price-list |  | no | website, gbp, tenbis, instagram | on-change | [S55] |
| `content.menu.seasonal` | תפריט עונתי / חג | Seasonal / holiday menu | price-list |  | no | website, gbp, instagram, wolt | seasonal | — (convention) |
| `content.menu.pesach` | תפריט פסח (כשר לפסח) | Pesach (kosher-for-Passover) menu | price-list | **required if:** operating kosher-for-Passover; write 'כשר לפסח' only with a Pesach certificate; otherwise a closure notice or chametz-law-compliant operation (no public display of chametz for sale/consumption during Pesach; not in non-Jewish-majority localities) | no* | website, gbp, wolt, tenbis, print | seasonal: Pesach | [S47], [S51], [S52] |
| `content.menu.allergen-legend` | מקרא אלרגנים | Allergen legend | list | not mandated for restaurant menus (a 2022 bill proposed numbered marking); use the EU-14 set: cereals with gluten, crustaceans, eggs, fish, peanuts, soy, milk, tree nuts, celery, mustard, sesame, sulphites, lupin, molluscs | no | website, print, wolt, tenbis | on-change | [S72], [S73], [S74] |
| `content.menu.dietary-legend` | מקרא סימונים תזונתיים | Dietary tags legend | list | one of: Vegan, Vegetarian, GlutenFree, LowLactose, Kosher, Halal, Diabetic, LowCalorie, LowFat, LowSalt, Hindu; schema.org RestrictedDiet values | no | website, print, wolt, tenbis | on-change | [S71] |
| `content.menu.popular-dishes` | מנות פופולריות | Popular dishes | list |  | no | gbp | on-change | [S78] |
| `content.kosher.certificate` | תעודת כשרות | Kashrut certificate | document | **required if:** presenting the restaurant as kosher; issued by the local rabbi / Chief Rabbinate; shows owner, address, חלבי/בשרי/פרווה, רגיל/מהדרין, supervisor name + mobile, anti-forgery barcode sticker; valid 1 year from issue (reg. 9); display openly at the premises, only while valid (s.10) | no* | signage, website, gbp, wolt, tenbis, rest, tabit, ontopo | P1Y (from issue) | [S47], [S48], [S49] |
| `content.kosher.pesach-certificate` | תעודת כשרות לפסח | Pesach kashrut certificate | document | **required if:** operating kosher-for-Passover; separate Pesach certificate from the local rabbinate; a private badatz approval must come with a current local-rabbinate certificate | no* | signage, website, wolt, tenbis | seasonal: Pesach | [S51] |
| `content.kosher.private-hechsher` | תעודת השגחה פרטית (בד״ץ / צהר) | Private hechsher / supervision certificate | document | alongside a rabbinate certificate, or alone with 'בהשגחה' / 'בפיקוח' wording (not 'כשר') | no | signage, website | per issuer (unknown) | [S50] |
| `content.kosher.statement` | נוסח כשרות לפרסום | Kashrut statement text | text | langs he+en; **required if:** kosher or supervised | no* | website, wolt, tenbis, rest, gbp | on-change | [S47], [S50] |
| `content.license.business` | רישיון עסק | Business license | document | food businesses are licensed; default validity 15 years, shorter per business type (s.7א); a public-display duty is not in the Act (unknown - check license conditions) | yes | premises-file | P15Y default (license may set shorter) | [S53] |
| `content.license.alcohol-conditions` | תנאי רישוי לממכר משקאות משכרים | Alcohol licensing conditions | document | **required if:** serves alcohol | no* | premises-file | with business license | [S57] |
| `content.signage.price-display` | הצגת מחירים בעסק | Price display at the premises | document | total price per item/service, ₪ only, in a visible place, clear legible numerals | yes | signage | on-change | [S54], [S55] |
| `content.signage.no-smoking` | שלטי 'העישון אסור' | No-smoking signs | document | ≥20x30 cm; symbol ≥1/3 of the sign; mounted 1.80-2.20 m; 1 per 10 m of wall or at least 1 per room/area (except a smoking room) | yes | signage | none (keep in good order) | [S56] |
| `content.signage.alcohol-minors` | שלט איסור מכירת משקאות משכרים לקטינים | No-alcohol-to-minors notice | document | **required if:** serves alcohol; wording/size per police uniform licensing spec item 4.8 - exact values unknown | no* | signage | none | [S57] |
| `content.signage.storefront` | שלט חזית | Storefront sign | document | municipal signage permit + annual fee; Hebrew must cover at least half the sign when another language appears (TLV s.18); rules differ per city | yes | signage | yearly (TLV permit lapses 31 Dec) | [S58] |
| `content.signage.a-frame` | שלט מדרכה (A-frame) | A-frame sidewalk sign | document | sidewalk placement approval unknown - check city bylaw | no | signage | per municipal permit | [S58] |
| `content.signage.window` | מדבקות חלון | Window stickers | document | hours, accepted meal cards (10bis / Cibus), kashrut, accessibility, QR | no | signage | on-change | — (convention) |
| `content.signage.hours` | שלט שעות פתיחה | Opening-hours sign | document | rendered from identity.hours.regular; no legal spec found | no | signage | on-change | — (convention) |
| `content.table.qr-card` | כרטיס QR לתפריט | Table QR menu card | document | links to the web menu; size is a design choice | no | print | on-change | — (convention) |
| `content.table.tent` | סטנד שולחני | Table tent | document | specials, events, review QR | no | print | on-change | — (convention) |
| `content.delivery.wolt` | תוכן לוולט | Wolt listing content | list | menu + item photos (16:9 landscape, ≥1000x563 (2nd), ≤5 per item, no people/text/AI/multiple items); venue cover/logo spec unknown | no | wolt | on-change | [S63], [S64] |
| `content.delivery.tenbis` | תוכן לתן ביס | 10bis listing content | list | listing fields / image specs unknown (join via restaurant form) | no | tenbis | on-change | [S65] |
| `content.delivery.cibus-mishloha` | תוכן לסיבוס ומשלוחה | Cibus / Mishloha listing content | list | specs unknown | no | cibus, mishloha | on-change | [S66] |
| `content.delivery.own` | משלוחים עצמאיים | Own delivery (zones, fees, minimum order) | list | fees shown as part of total prices | no | website, whatsapp | on-change | [S55] |
| `content.reservations.policy` | מדיניות הזמנת מקומות | Reservation policy | text | **required if:** takes reservations; deposit, cancellation, table time, max party size | no* | tabit, ontopo, website | on-change | [S67], [S68] |
| `content.events.list` | אירועים | Events | list | GBP event post needs title + start/end dates and times | no | gbp, facebook, instagram, website | per event | [S04] |
| `content.specials.daily` | מנות היום | Daily specials | price-list |  | no | instagram, whatsapp, facebook, website | daily | — (convention) |
| `content.catering.menu` | תפריט אירועים / קייטרינג | Events / catering menu | price-list |  | no | website, whatsapp | on-change | — (convention) |
| `content.docs.bill-footer` | נוסח תחתית חשבון (שירות / טיפ) | Bill footer (service / tip wording) | text | mandatory service or other charges must be inside the displayed total price (s.17ד); only voluntary tip wording | no | invoice | on-change | [S55], [S77] |
| `content.reviews.platforms` | קישורי ביקורות | Review-site links | list | Google, Tripadvisor, Rest, Easy, Wolt | no | website, print, whatsapp | on-change | [S69], [S70] |

### 3.3 Media

| key | Hebrew label | English label | kind | constraints | req. | used in (targets) | renewal / expiry | source |
|---|---|---|---|---|---|---|---|---|
| `media.photo.products` | מוצרים / דוגמאות עבודה | Products / work samples | image | override: superseded by media.food.* | no | gbp, website | on-change | [S01] |
| `media.food.hero-dish` | מנת הדגל | Hero dish photo | image | landscape 16:9 master ≥1000x563 for Wolt (2nd) + square/4:5 crops; GBP JPG/PNG 10 KB-5 MB | yes | gbp, wolt, tenbis, instagram, website, tripadvisor | quarterly refresh (recommended) | [S01], [S63], [S64] |
| `media.food.menu-items` | צילום לכל מנה | Photo per menu item | image | **required if:** listed on a delivery platform; up to 5 per item on Wolt; landscape 16:9; whole dish centred; single item; no people, text, borders or AI images | no* | wolt, tenbis, mishloha, gbp, website | on-change | [S05], [S63] |
| `media.food.ambience` | אווירה ועיצוב פנים | Ambience / interior | image | Tripadvisor: landscape 1:1-4:3 and ≤10 MB reported (2nd, unverified) | yes | gbp, tripadvisor, rest, tabit, ontopo, website | yearly refresh (recommended) | [S01], [S69] |
| `media.food.chef` | השף / צוות המטבח | Chef / kitchen team | image | keep people out of item photos (Wolt rule) | no | website, instagram, rest | on-change | [S63] |
| `media.food.drinks` | משקאות וקוקטיילים | Drinks & cocktails | image |  | no | instagram, website, gbp | on-change | [S01] |
| `media.food.menu-photos` | צילום התפריט המודפס | Photos of the printed menu | image | GBP menu photos | yes | gbp | on-change | [S06] |
| `media.video.kitchen` | סרטון מטבח / מנה | Kitchen / dish reel | video | 1080x1920 9:16 (2nd); GBP copy ≤30 s, ≤75 MB, ≥720p | no | instagram, tiktok, gbp | on-change | [S01], [S75] |
| `media.image.qr-menu` | QR לתפריט | Menu QR code | image | SVG | no | print, signage | on-change | — (convention) |
| `media.image.delivery-cover` | תמונת נושא לפלטפורמות משלוחים | Delivery-platform cover image | image | spec unknown per platform | no | wolt, tenbis, mishloha | on-change | — (convention) |

### 3.4 One menu item: field schema (shared by every `content.menu.*` price-list)

| field | kind | constraint | required | source |
|---|---|---|---|---|
| `section` | text | e.g. starters / mains / desserts; GBP menu editor groups items into sections | yes | [S05] |
| `name_he`, `name_en` | text | limits unknown (the GBP menu editor states none) | he yes, en no | [S05] |
| `description_he`, `description_en` | text | limits unknown | no | [S05] |
| `price` | text (₪ amount) | total price incl. VAT, Israeli currency only | yes | [S54] [S55] |
| `variants` | list | portion / size / add-on with its own total price | no | [S55] |
| `photos` | image[] | Wolt: 16:9 landscape, ≤5, single item, no people/text/AI; GBP JPG/PNG 10 KB-5 MB | no (yes for delivery) | [S63] [S01] |
| `allergens` | list | EU-14 set (incl. sesame); not legally mandated on restaurant menus (bill only) | no | [S73] [S72] |
| `dietary` | list | schema.org RestrictedDiet: Vegan, Vegetarian, GlutenFree, LowLactose, Kosher, Halal, … | no | [S71] |
| `spice_level` | text | 0-3 scale (platform-defined; no standard found) | no | — (convention) |
| `kashrut_class` | text | חלבי / בשרי / פרווה (as on the certificate) | if kosher | [S49] |
| `availability` | hours | e.g. business lunch only, Pesach only | no | — (convention) |
| `popular` | text (flag) | GBP popular dishes | no | [S78] |
| `code` | text | POS / platform SKU for sync | no | — (convention) |

### 3.5 Recurring content calendar: `basic-restaurant` (in addition to `business-basic`)

| unit | Hebrew name | trigger / date | channels | assets (kind: spec × count) | notes | source |
|---|---|---|---|---|---|---|
| `daily-specials` | מנות היום | daily (open days), before lunch service | instagram, whatsapp, facebook | image: 1080x1920 (9:16) [S75] × 1<br>text: dish name + price (total ₪) [S55] × 1 |  | [S75], [S55] |
| `weekly-business-lunch` | עסקית השבוע | weekly: Sunday morning (for Sun-Thu lunch) | instagram, facebook, gbp, whatsapp | image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1<br>rich-text: GBP post text ≤1,500 chars (2nd) [S08] × 1 |  | [S08] |
| `weekly-weekend` | סוף שבוע / בראנץ׳ שישי | weekly: Thursday | instagram, facebook, whatsapp | image: 1080x1920 (9:16) [S75] × 1<br>hours: Friday / Saturday hours × 1 |  | — (convention) |
| `events` | אירוע במסעדה | per event: −14d and −1d | gbp, facebook, instagram, website | rich-text: GBP event post: title + start/end dates and times [S04] × 1<br>image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1<br>image: 1080x1920 (9:16) [S75] × 2 |  | [S04] |
| `rosh-hashana-menu` | תפריט ראש השנה והזמנות לחג | hebrew 1 Tishrei; announce −21d; order cutoff −3d | instagram, facebook, whatsapp, email, website | price-list: holiday takeaway menu × 1<br>image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 2<br>rich-text: newsletter [S43] × 1 |  | [S62], [S43] |
| `yom-kippur-closure` | סגירה ביום כיפור | hebrew 10 Tishrei | gbp, whatsapp, website | hours: GBP special hours (closed) × 1 |  | [S62] |
| `sukkot-sukkah` | ישיבה בסוכה | hebrew 15-21 Tishrei | instagram, facebook, gbp | image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1 | kosher restaurants | [S62] |
| `hanukkah-specials` | סופגניות ולביבות | hebrew 25 Kislev, 8 days | instagram, facebook, wolt | image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1<br>image: 1080x1920 (9:16) [S75] × 4 |  | [S62] |
| `purim` | פורים (משלוחי מנות) | hebrew 14 Adar (15 in Jerusalem) | instagram, whatsapp, website | price-list: mishloach-manot boxes × 1 |  | [S62] |
| `pesach` | פסח: תפריט כשר לפסח או סגירה | hebrew 15 Nisan; decide −45d; announce −21d; switch menus −1d | website, gbp, wolt, tenbis, instagram, whatsapp, signage | document: Pesach kashrut certificate scan [S51] × 1<br>price-list: content.menu.pesach × 1<br>hours: GBP special hours × 1<br>text: closure / 'כשר לפסח' notice (only with certificate) [S47] × 1 | chametz law: no public display of chametz for sale/consumption during Pesach [S52] | [S51], [S47], [S52], [S62] |
| `memorial-eves` | ערבי יום השואה ויום הזיכרון | hebrew 27 Nisan eve; 4 Iyar eve (both may shift) | gbp, whatsapp, website | hours: eve closure hours × 2<br>text: closure notice, no promotion × 2 | cafés/restaurants close on the eve | [S60], [S61], [S62] |
| `yom-haatzmaut` | יום העצמאות | hebrew 5 Iyar (may shift) | instagram, facebook, gbp | image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1<br>hours: GBP special hours × 1 |  | [S62] |
| `shavuot-dairy` | תפריט חלבי לשבועות | hebrew 6 Sivan; announce −14d | instagram, facebook, wolt, website | price-list: dairy holiday menu × 1<br>image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1 |  | [S62] |
| `tisha-bav` | תשעה באב - בדיקת חוק עזר עירוני | hebrew 9 Av eve | gbp, whatsapp, website | hours: eve hours / closure × 1 | the city may close eating places on the eve by bylaw | [S59], [S62] |
| `couples` | ט״ו באב / ולנטיין | hebrew 15 Av; gregorian 14 Feb | instagram, facebook, tabit, ontopo | price-list: couples menu × 1<br>image: 1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22] × 1 |  | [S62] |
| `kosher-renewal` | חידוש תעודת כשרות | content.kosher.certificate issue date + P1Y; remind −30d | signage, website, wolt, tenbis, rest | document: renewed certificate scan; replace everywhere × 1 | certificate valid 1 year from issue | [S48] |
| `signage-renewal` | חידוש רישיון שילוט | gregorian 1 Dec (permit lapses 31 Dec in Tel Aviv) | signage | document: permit renewal + fee receipt × 1 | city-specific | [S58] |
| `license-check` | בדיקת תוקף רישיון עסק | content.license.business expiry −180d | premises-file | document: license renewal file × 1 |  | [S53] |
| `menu-sync` | סנכרון תפריט לפלטפורמות | on change of any content.menu.* | gbp, wolt, tenbis, mishloha, tabit, ontopo, website, print | price-list: updated menu × 1<br>image: item photos per Wolt spec [S63] × 1 | GBP menu edits take 24-48 h to show [S05] | [S05], [S63] |
| `review-replies` | מענה לביקורות | weekly | gbp, tripadvisor, rest, easy, wolt | text: replies from content.reviews.replies × 1 |  | — (convention) |
| `photo-refresh` | רענון צילומי מנות | quarterly or on menu change | gbp, wolt, instagram, website | image: JPG/PNG 10 KB-5 MB, rec 720x720, min 250x250 [S01] × 5 |  | [S01] |

## 4. Future blueprints (distinctive slots only)

All five extend `business-basic`. Only the slots that differ from it are listed.

| id | Hebrew | English | distinctive slots |
|---|---|---|---|
| `clinic-therapist` | קליניקה / מטפל·ת | Clinic / therapist | `identity.professional.license-number` (per profession, unknown registry per profession) · `identity.professional.credentials` (diplomas, document) · `content.treatments.catalog` (price-list with duration) · `content.booking.policy` (cancellation / no-show) · `content.insurance.accepted` (קופות חולים / insurers, list) · `content.forms.intake` (health questionnaire; privacy notice required when personal data is collected [S45]) · `content.reminders.templates` (WhatsApp/SMS) · `media.photo.treatment-room` |
| `retail-shop` | חנות | Retail shop | `content.catalog.products` becomes **required** (SKU, barcode, stock; GBP 58/1,000 chars (2nd) [S07]; WhatsApp ≤500 items (2nd) [S17]) · `content.signage.price-tags` (total-price display on goods, Consumer Protection s.17א-17ז [S55]) · `content.policy.returns` (return & exchange policy) · `content.ecommerce.shipping` · `media.photo.packshots` · `content.gift-cards` · calendar: holiday gift seasons, back-to-school, Black Friday |
| `freelancer-consultant` | פרילנסר / יועץ | Freelancer / consultant | `media.photo.headshot` (required) · LinkedIn profile + cover **required** (1512x256 [S28]) · `content.portfolio.case-studies` · `content.docs.proposal-template` · `content.docs.engagement-letter` · `content.catalog.rate-card` · `identity.links.booking` (calendar link) · `content.lead-magnet` (PDF) · entity type drives invoice/receipt type (עוסק פטור ceiling 122,833 ₪ in 2026 [S38] [S34]) |
| `beauty-salon` | מספרה / מכון יופי | Beauty salon / hairdresser | `content.catalog.services` with duration + staff (price display duty applies to services at the premises [S54]) · `media.gallery.before-after` (client consent) · `identity.staff.profiles` · `identity.links.booking-app` · `content.policy.cancellation` · `content.retail.products` · calendar: erev-chag appointment rush, wedding season |
| `b2b-service-company` | חברת שירותים לעסקים | B2B service company | `content.docs.company-profile` (PDF deck) · `content.case-studies` · `media.logos.clients` (with permission) · `content.certifications` (e.g. ISO; expiry per certificate) · `content.docs.quote-template` · `content.docs.sla` · `content.legal.data-processing` (processor terms under Amendment 13 [S45]) · `content.releases.press` · `identity.legal.tax-certificates` (אישור ניהול ספרים / ניכוי במקור: validity unknown) · LinkedIn Page **required** [S28] |

## 5. Unknowns and open questions

1. **10bis, Cibus Pluxee, Mishloha**: listing fields and image specs are not published. Wolt venue cover and
   logo specs are also unknown. The Wolt menu-photo minimum of 1000x563 is from a secondary source [S64].
2. **WhatsApp**: the app's description limit is reportedly 256 (secondary) against 512 in the API [S15]. The
   profile-photo spec is unknown.
3. **TikTok bio** is 80 or 160 characters depending on the account (secondary). The Facebook intro, YouTube
   description and X handle limits were not verified.
4. **Apple Business**: the logo (≥1024) and cover (≥1600x1040) numbers come from Apple support search
   snippets; the page body could not be retrieved [S09]. The Tripadvisor limits could not be verified [S69].
5. **Alcohol-to-minors sign**: the wording and size are set by the police uniform specification (item 4.8),
   which was not retrieved [S57]. The Business Licensing Law's 23:00-06:00 alcohol restriction needs a scope
   check for on-premise service [S53].
6. **Business-license display**: no display duty was found in the Act. It may be a license condition [S53].
7. **Cookie consent**: the Privacy Protection Authority's 2020 text is a draft recommendation [S46]. Whether
   Amendment 13 makes a cookie banner binding is unknown.
8. **Accessibility statement**: whether exempt businesses (35ו) must still publish one is unknown [S32].
9. **Allergens on restaurant menus**: only a 2022 bill exists [S72]. EU-style labeling (by 2028) applies to
   pre-packaged food [S74].
10. **Kashrut reform**: the reversal had passed only a first reading at the time of the source, and Tzohar's
    litigation was ongoing [S50]. Re-check the permitted wording before launch.
11. **Reserve with Google** and GBP Products availability in Israel are unknown [S06] [S02]. Tisha B'Av closures
    depend on each city's bylaws [S59].

## Sources

| id | kind | what it supports | URL |
|---|---|---|---|
| S01 | primary | Google Business Profile - photos & videos (formats, sizes, video limits) | <https://support.google.com/business/answer/6103862?hl=en> |
| S02 | primary | Google Business Profile - edit profile (description 750, categories 1+9, phones 1+2, opening date, attributes, more hours, menu) | <https://support.google.com/business/answer/3039617?hl=en> |
| S03 | primary | Google Business Profile - guidelines for representing your business (name, address, hours, categories) | <https://support.google.com/business/answer/3038177?hl=en> |
| S04 | primary | Google Business Profile - posts (update/offer/event, 6-month archive) | <https://support.google.com/business/answer/7342169?hl=en> |
| S05 | primary | Google Business Profile - menu editor (sections, items, descriptions, prices) | <https://support.google.com/business/answer/9455840?hl=en> |
| S06 | primary | Google Business Profile - restaurants (menu URL, Order with Google, Reserve with Google, per-service hours) | <https://support.google.com/business/answer/14189260?hl=en> |
| S07 | secondary | GBP products (name 58 / description 1,000) and services (name 80 / description 300) | <https://www.gmbeverywhere.com/guides/your-easy-guide-to-services-products-on-google-business-profile> |
| S08 | secondary | GBP post text 1,500 characters | <https://lettercounter.org/blog/google-business-profile-character-limit/> |
| S09 | primary* | Apple Business (Connect) - cover photo >=1600x1040, logo square >=1024x1024, HEIC/JPEG/PNG (numbers from Apple support search snippets; page body not retrievable) | <https://support.apple.com/guide/apple-business-connect/about-the-cover-photo-abcb139fcd45/web> |
| S10 | primary | Bing Places - new experience, import from Google Business Profile | <https://blogs.bing.com/search/2025/10/Introducing-the-New-Bing-Places-for-Business-Built-for-Business-Owners,-Powered-by-Research/> |
| S11 | primary | Waze - add/edit a business with the Waze Map Editor (app route needs a storefront photo) | <https://support.google.com/waze/answer/6263233?hl=en> |
| S12 | primary | Dapei Zahav (d.co.il) - free business listing | <https://www.d.co.il/LandingPage/AddBusiness/> |
| S13 | secondary | B144 - free self-registration to the business index | <https://b144.walla.co.il/item/3382078> |
| S14 | primary | Easy (easy.co.il) - add a business | <https://easy.co.il/add> |
| S15 | primary | WhatsApp Business profile limits (about 1-139, description 512, address 256, email 128, 2 websites x 256, vertical enum) | <https://developers.facebook.com/docs/whatsapp/cloud-api/reference/business-profiles> |
| S16 | primary | WhatsApp Help - about your business profile (name, description, address, hours, category) | <https://faq.whatsapp.com/577829787429875> |
| S17 | secondary | WhatsApp catalog - 500 products/catalog, 10 images/item, item fields | <https://chatarmin.com/en/blog/whatsapp-business-catalog> |
| S18 | primary* | Facebook Help - Page profile picture and cover photo dimensions (page body not retrievable; numbers via S19) | <https://www.facebook.com/help/125379114252045> |
| S19 | secondary | Facebook cover 820x312 desktop / 640x360 phone; 851x315 JPG <100 KB; profile 176/196 | <https://snappa.com/blog/facebook-cover-photo-size/> |
| S20 | primary | YouTube - channel branding (profile 98x98 render, <=15 MB; banner min 2048x1152, safe 1235x338, <=6 MB; watermark 150x150 <1 MB) | <https://support.google.com/youtube/answer/10456525?hl=en> |
| S21 | primary* | X Help - profile 400x400, header 1500x500 (page blocked to fetch; numbers via search result); bio 160 | <https://help.x.com/en/managing-your-account/common-issues-when-uploading-profile-photo> |
| S22 | primary* | Instagram Help - photo resolution: widths 320-1080 kept when aspect 1.91:1 to 3:4 (1080 x 566-1440) | <https://help.instagram.com/1631821640426723/> |
| S23 | primary* | Instagram Help - add a bio (150 characters, via search result) | <https://help.instagram.com/728994388226960/> |
| S24 | secondary | Instagram profile picture upload 320x320, displayed 110x110 | <https://expertphotography.com/instagram-profile-picture-size-guide> |
| S25 | secondary | TikTok bio 80 characters (some accounts 160) | <https://boomp.net/resources/questions/tiktok-bio-character-limit-2026> |
| S26 | secondary | TikTok profile picture displayed 200x200 | <https://postfa.st/sizes/tiktok/profile> |
| S27 | secondary | Discord server banner 960x540 (16:9), icon 512x512, boost required | <https://www.krumzi.com/size-guide/discord-banner-size> |
| S28 | primary | LinkedIn Pages - logo 400x400 (min 268x268), cover 1512x256, PNG/JPEG <=3 MB | <https://www.linkedin.com/help/linkedin/answer/a563309/image-specifications-for-your-linkedin-pages-and-career-pages> |
| S29 | primary | Google Search - favicon (square, >=8x8, recommended >48x48, stable URL, formats) | <https://developers.google.com/search/docs/appearance/favicon-in-search> |
| S30 | primary | web.dev - manifest icons 192x192 + 512x512, maskable | <https://web.dev/articles/add-manifest> |
| S31 | primary | Meta - link-share images (>=1200x630, min 600x315, min 200x200, <=8 MB, ~1.91:1) | <https://developers.facebook.com/docs/sharing/webmasters/images> |
| S32 | primary | תקנות שוויון זכויות לאנשים עם מוגבלות (התאמות נגישות לשירות), תשע״ג-2013 - reg. 35, 35ה (statement), 35ו (exemptions) | <https://www.nevo.co.il/law_html/law01/500_865.htm> |
| S33 | secondary | ISOC-IL - legal aspects: IS 5568 = WCAG 2.0 level AA; statement contents; penalties | <https://www.isoc.org.il/freedom-of-internet/accessibility/legal-aspects-accessibility> |
| S34 | secondary | Tax invoice (חשבונית מס) mandatory details; עוסק פטור cannot issue one | <https://www.greeninvoice.co.il/magazine/tax-invoice/> |
| S35 | primary | הוראות מס הכנסה (ניהול פנקסי חשבונות), תשל״ג-1973 - primary text | <https://www.nevo.co.il/law_html/law01/255_179.htm> |
| S36 | primary | Israel Tax Authority - allocation number required above 5,000 ₪ (before VAT) from 1 June 2026 | <https://www.gov.il/he/pages/pa240525-1> |
| S37 | secondary | Allocation number (מספר הקצאה) - 9 digits, >5,000 ₪ from 1.6.2026 | <https://www.grantthornton.co.il/insights1/tax-insignths/2026/From_June_the_allocation_number/> |
| S38 | secondary | עוסק פטור ceiling 2026: 122,833 ₪ | <https://www.mako.co.il/news-money/2026_q3/Article-39baaaa750e10a1027.htm> |
| S39 | primary | חוק החברות, תשנ״ט-1999 - s.26 (name ends with בערבון מוגבל / בע״מ) | <https://www.nevo.co.il/law_html/law01/139_002.htm> |
| S40 | secondary | ח״פ - 9-digit company number | <https://cpa-ea.co.il/blog/heshbonaut/ma-ze-hp/> |
| S41 | secondary | Business card 90x50 mm common in Israel | <https://www.sizes.co.il/business-card/> |
| S42 | secondary | ISO 216 - A4 = 210x297 mm | <https://en.wikipedia.org/wiki/ISO_216> |
| S43 | primary | Ministry of Communications - spam (דבר פרסומת) FAQ, s.30א חוק התקשורת | <https://www.gov.il/he/departments/faq/17052018_7> |
| S44 | secondary | חוק הספאם - 'פרסומת' at the start / subject line, sender identity & contact, unsubscribe | <https://he.wikipedia.org/wiki/%D7%97%D7%95%D7%A7_%D7%94%D7%A1%D7%A4%D7%90%D7%9D> |
| S45 | primary | Privacy Protection Law, Amendment 13 (in force 14 Aug 2025; expanded duty to inform) | <https://www.gov.il/he/pages/13_amendment> |
| S46 | secondary | Privacy Protection Authority - 2020 draft recommendation: explicit opt-in consent for cookies | <https://www.law.co.il/news/2020/11/05/israeli-privacy-regulator-recommends-cookies-consent/> |
| S47 | primary | חוק איסור הונאה בכשרות, תשמ״ג-1983 - s.2 issuers, s.3 'כשר' only with certificate, s.10 display | <https://www.nevo.co.il/law_html/law00/74362.htm> |
| S48 | primary | תקנות איסור הונאה בכשרות (תעודות הכשר), תשמ״ט-1988 - reg. 9: valid one year from issue | <https://www.nevo.co.il/law_html/law00/74363.htm> |
| S49 | primary | Religious council - certificate contents (owner, address, חלבי/בשרי/פרווה, רגיל/מהדרין, supervisor, barcode sticker) | <https://mdyv.org.il/kosher/cert> |
| S50 | secondary | Kashrut reform status; private supervision may say 'בהשגחה'/'בפיקוח', not 'כשר' | <https://www.ynet.co.il/judaism/article/ryfav72lgx> |
| S51 | secondary | Separate Pesach kashrut certificate; private badatz must be accompanied by a local-rabbinate certificate | <https://www.inn.co.il/news/296161> |
| S52 | primary | חוק חג המצות (איסורי חמץ), תשמ״ו-1986 | <https://www.nevo.co.il/law_html/law01/140_001.htm> |
| S53 | primary | חוק רישוי עסקים, תשכ״ח-1968 - s.7א license 15 years default; s.2(א1) alcohol 23:00-06:00 | <https://www.nevo.co.il/law_html/law00/74267.htm> |
| S54 | primary | תקנות הגנת הצרכן (הצגת מחירי שירותים), תשע״ב-2012 - בית אוכל: total price, ₪ only, visible, legible | <https://www.nevo.co.il/law_html/law00/119031.htm> |
| S55 | primary | Consumer Protection Authority - price display, s.17א-17ז (total price only, s.17ד) | <https://www.gov.il/he/departments/general/cpfta_display_of_prices> |
| S56 | primary | תקנות הגבלת העישון במקומות ציבוריים (קביעת שלטים), תשמ״ד-1984 | <https://www.nevo.co.il/law_html/law00/71597.htm> |
| S57 | primary* | Israel Police - uniform licensing specification, item 4.8 (alcohol served for on-premise consumption) - not retrieved | <https://www.gov.il/BlobFolder/reports/police_regulation-group4-food/he/%D7%A4%D7%A8%D7%99%D7%98%20%D7%A8%D7%99%D7%A9%D7%95%D7%99%20%204.8%20-%20%D7%9E%D7%A9%D7%A7%D7%90%D7%95%D7%AA%20%D7%9E%D7%A9%D7%9B%D7%A8%D7%99%D7%9D%20%E2%80%93%20%D7%A4%D7%90%D7%91,%20%D7%91%D7%A8,%20%D7%9E%D7%A1%D7%91%D7%90%D7%94%20%D7%95%D7%9B%D7%9C%20%D7%A2%D7%A1%D7%A7%20%D7%A9%D7%A2%D7%99%D7%A7%D7%A8%20%D7%A4%D7%A2%D7%99%D7%9C%D7%95%D7%AA%D7%95%20%D7%94%D7%92%D7%A9%D7%AA%D7%9D%20%D7%9C%D7%A6%D7%95%D7%A8%D7%9A%20%D7%A6%D7%A8%D7%99%D7%9B%D7%94%20%D7%91%D7%9E%D7%A7%D7%95%D7%9D%20%D7%94%D7%94%D7%92%D7%A9%D7%94.pdf> |
| S58 | primary | חוק עזר לתל-אביב-יפו (שילוט) - permit + fee; lapses 31 Dec; Hebrew >= half of sign area | <https://www.nevo.co.il/law_html/law01/mek_001_008.htm> |
| S59 | primary | חוק איסור פתיחת בתי עינוגים בתשעה באב (הסמכה מיוחדת) - municipalities may close eating places on the eve | <https://www.nevo.co.il/law_html/law01/019m2_001.htm> |
| S60 | secondary | Municipal notice - business closures, Holocaust Remembrance Day eve (cafés closed by law) | <https://rosh-haayin.muni.il/news/391/> |
| S61 | primary | Tel Aviv-Yafo - business closures on Memorial Day eve | <https://www.tel-aviv.gov.il/Pages/MainItemPage.aspx?WebID=3af57d92-807c-43c5-8d5f-6fd455eb2776&ListID=81e17809-311d-4bba-9bf1-2363bb9debcd&ItemId=518> |
| S62 | secondary | Hebcal - Israeli holiday dates 5787 (2026-2027) | <https://www.hebcal.com/holidays/2026-2027?i=on> |
| S63 | primary | Wolt Merchant - menu photos: 16:9 landscape, up to 5 per item, no people/text/AI/multiple items | <https://merchant.wolt.com/learning-center/add-edit-menu-photos> |
| S64 | secondary | Wolt menu photo minimum 1000x563, JPG/PNG | <https://foodphoto.ai/delivery-photo-specs/wolt/> |
| S65 | primary | 10bis - restaurant join form (listing specs not published) | <https://www.10bis.co.il/res-form/> |
| S66 | primary | Cibus Pluxee x Mishloha cooperation | <https://cibus.pluxee.co.il/cooperations/mishloha> |
| S67 | primary | Ontopo - restaurant join (reservations) | <https://ontopo.co.il/en/join> |
| S68 | primary | Tabit - table reservations | <https://tabitisrael.co.il/> |
| S69 | primary* | Tripadvisor media guidelines (page blocked to fetch; limits reported by search only) | <https://www.tripadvisor.com/Trust-lpO1gcsIEejY-Media_guidelines.html> |
| S70 | primary | Rest (ZAP Rest) - 8,000+ restaurants; filters incl. kashrut, price, private room | <https://www.rest.co.il/about/> |
| S71 | primary | schema.org suitableForDiet / RestrictedDiet values | <https://schema.org/suitableForDiet> |
| S72 | primary | הצעת חוק סימון רכיבים אלרגניים בתפריטים של בתי אוכל, התשפ״ב (bill, not law) | <https://www.nevo.co.il/law_html/law04/24_lst_607444.htm> |
| S73 | secondary | EU 14 allergens list | <https://www.eufic.org/en/healthy-living/article/list-of-the-14-most-common-food-allergens> |
| S74 | secondary | Israel moving pre-packaged food labeling (incl. allergens) to EU style by 2028 | <https://www.israelhayom.co.il/business/consumers/article/19118233> |
| S75 | secondary | Stories/Reels 1080x1920 (9:16) | <https://blog.hootsuite.com/social-media-image-sizes-guide/> |
| S76 | primary | WCAG 2.0 SC 1.4.3 - contrast 4.5:1 (AA) | <https://www.w3.org/TR/WCAG20/#visual-audio-contrast-contrast> |
| S77 | secondary | Restaurant service charge outside the displayed total price (consumer case) | <https://www.mako.co.il/finances-consumer/Article-d1347ed7a9f4471027.htm> |
| S78 | primary | GBP - popular dishes for restaurants | <https://support.google.com/business/answer/9322475> |
| S79 | secondary | Instagram username / name 30 characters | <https://bitly.com/blog/instagram-character-limit/> |
| S80 | secondary | WhatsApp Business app description reportedly 256 characters | <https://helo.ai/resources/blog/whatsapp-business-description> |

`primary*` = official page whose body could not be fetched; the numbers were taken from search results that quote it.

[S01]: https://support.google.com/business/answer/6103862?hl=en
[S02]: https://support.google.com/business/answer/3039617?hl=en
[S03]: https://support.google.com/business/answer/3038177?hl=en
[S04]: https://support.google.com/business/answer/7342169?hl=en
[S05]: https://support.google.com/business/answer/9455840?hl=en
[S06]: https://support.google.com/business/answer/14189260?hl=en
[S07]: https://www.gmbeverywhere.com/guides/your-easy-guide-to-services-products-on-google-business-profile
[S08]: https://lettercounter.org/blog/google-business-profile-character-limit/
[S09]: https://support.apple.com/guide/apple-business-connect/about-the-cover-photo-abcb139fcd45/web
[S10]: https://blogs.bing.com/search/2025/10/Introducing-the-New-Bing-Places-for-Business-Built-for-Business-Owners,-Powered-by-Research/
[S11]: https://support.google.com/waze/answer/6263233?hl=en
[S12]: https://www.d.co.il/LandingPage/AddBusiness/
[S13]: https://b144.walla.co.il/item/3382078
[S14]: https://easy.co.il/add
[S15]: https://developers.facebook.com/docs/whatsapp/cloud-api/reference/business-profiles
[S16]: https://faq.whatsapp.com/577829787429875
[S17]: https://chatarmin.com/en/blog/whatsapp-business-catalog
[S18]: https://www.facebook.com/help/125379114252045
[S19]: https://snappa.com/blog/facebook-cover-photo-size/
[S20]: https://support.google.com/youtube/answer/10456525?hl=en
[S21]: https://help.x.com/en/managing-your-account/common-issues-when-uploading-profile-photo
[S22]: https://help.instagram.com/1631821640426723/
[S23]: https://help.instagram.com/728994388226960/
[S24]: https://expertphotography.com/instagram-profile-picture-size-guide
[S25]: https://boomp.net/resources/questions/tiktok-bio-character-limit-2026
[S26]: https://postfa.st/sizes/tiktok/profile
[S27]: https://www.krumzi.com/size-guide/discord-banner-size
[S28]: https://www.linkedin.com/help/linkedin/answer/a563309/image-specifications-for-your-linkedin-pages-and-career-pages
[S29]: https://developers.google.com/search/docs/appearance/favicon-in-search
[S30]: https://web.dev/articles/add-manifest
[S31]: https://developers.facebook.com/docs/sharing/webmasters/images
[S32]: https://www.nevo.co.il/law_html/law01/500_865.htm
[S33]: https://www.isoc.org.il/freedom-of-internet/accessibility/legal-aspects-accessibility
[S34]: https://www.greeninvoice.co.il/magazine/tax-invoice/
[S35]: https://www.nevo.co.il/law_html/law01/255_179.htm
[S36]: https://www.gov.il/he/pages/pa240525-1
[S37]: https://www.grantthornton.co.il/insights1/tax-insignths/2026/From_June_the_allocation_number/
[S38]: https://www.mako.co.il/news-money/2026_q3/Article-39baaaa750e10a1027.htm
[S39]: https://www.nevo.co.il/law_html/law01/139_002.htm
[S40]: https://cpa-ea.co.il/blog/heshbonaut/ma-ze-hp/
[S41]: https://www.sizes.co.il/business-card/
[S42]: https://en.wikipedia.org/wiki/ISO_216
[S43]: https://www.gov.il/he/departments/faq/17052018_7
[S44]: https://he.wikipedia.org/wiki/%D7%97%D7%95%D7%A7_%D7%94%D7%A1%D7%A4%D7%90%D7%9D
[S45]: https://www.gov.il/he/pages/13_amendment
[S46]: https://www.law.co.il/news/2020/11/05/israeli-privacy-regulator-recommends-cookies-consent/
[S47]: https://www.nevo.co.il/law_html/law00/74362.htm
[S48]: https://www.nevo.co.il/law_html/law00/74363.htm
[S49]: https://mdyv.org.il/kosher/cert
[S50]: https://www.ynet.co.il/judaism/article/ryfav72lgx
[S51]: https://www.inn.co.il/news/296161
[S52]: https://www.nevo.co.il/law_html/law01/140_001.htm
[S53]: https://www.nevo.co.il/law_html/law00/74267.htm
[S54]: https://www.nevo.co.il/law_html/law00/119031.htm
[S55]: https://www.gov.il/he/departments/general/cpfta_display_of_prices
[S56]: https://www.nevo.co.il/law_html/law00/71597.htm
[S57]: https://www.gov.il/BlobFolder/reports/police_regulation-group4-food/he/%D7%A4%D7%A8%D7%99%D7%98%20%D7%A8%D7%99%D7%A9%D7%95%D7%99%20%204.8%20-%20%D7%9E%D7%A9%D7%A7%D7%90%D7%95%D7%AA%20%D7%9E%D7%A9%D7%9B%D7%A8%D7%99%D7%9D%20%E2%80%93%20%D7%A4%D7%90%D7%91,%20%D7%91%D7%A8,%20%D7%9E%D7%A1%D7%91%D7%90%D7%94%20%D7%95%D7%9B%D7%9C%20%D7%A2%D7%A1%D7%A7%20%D7%A9%D7%A2%D7%99%D7%A7%D7%A8%20%D7%A4%D7%A2%D7%99%D7%9C%D7%95%D7%AA%D7%95%20%D7%94%D7%92%D7%A9%D7%AA%D7%9D%20%D7%9C%D7%A6%D7%95%D7%A8%D7%9A%20%D7%A6%D7%A8%D7%99%D7%9B%D7%94%20%D7%91%D7%9E%D7%A7%D7%95%D7%9D%20%D7%94%D7%94%D7%92%D7%A9%D7%94.pdf
[S58]: https://www.nevo.co.il/law_html/law01/mek_001_008.htm
[S59]: https://www.nevo.co.il/law_html/law01/019m2_001.htm
[S60]: https://rosh-haayin.muni.il/news/391/
[S61]: https://www.tel-aviv.gov.il/Pages/MainItemPage.aspx?WebID=3af57d92-807c-43c5-8d5f-6fd455eb2776&ListID=81e17809-311d-4bba-9bf1-2363bb9debcd&ItemId=518
[S62]: https://www.hebcal.com/holidays/2026-2027?i=on
[S63]: https://merchant.wolt.com/learning-center/add-edit-menu-photos
[S64]: https://foodphoto.ai/delivery-photo-specs/wolt/
[S65]: https://www.10bis.co.il/res-form/
[S66]: https://cibus.pluxee.co.il/cooperations/mishloha
[S67]: https://ontopo.co.il/en/join
[S68]: https://tabitisrael.co.il/
[S69]: https://www.tripadvisor.com/Trust-lpO1gcsIEejY-Media_guidelines.html
[S70]: https://www.rest.co.il/about/
[S71]: https://schema.org/suitableForDiet
[S72]: https://www.nevo.co.il/law_html/law04/24_lst_607444.htm
[S73]: https://www.eufic.org/en/healthy-living/article/list-of-the-14-most-common-food-allergens
[S74]: https://www.israelhayom.co.il/business/consumers/article/19118233
[S75]: https://blog.hootsuite.com/social-media-image-sizes-guide/
[S76]: https://www.w3.org/TR/WCAG20/#visual-audio-contrast-contrast
[S77]: https://www.mako.co.il/finances-consumer/Article-d1347ed7a9f4471027.htm
[S78]: https://support.google.com/business/answer/9322475
[S79]: https://bitly.com/blog/instagram-character-limit/
[S80]: https://helo.ai/resources/blog/whatsapp-business-description

## Appendix: machine-readable input

Slots with `required: false` may still carry `constraints.required_if`. `constraints.refs` lists source ids from the table above. In `basic-restaurant`, a slot whose key exists in the parent overrides the parent slot.

```yaml
# business-blueprints-input
# generated 2026-09-29; future blueprints (clinic-therapist, retail-shop, freelancer-consultant, beauty-salon, b2b-service-company) are described in section 4 only
blueprints:
  - id: business-basic
    name_he: "עסק בסיסי"
    name_en: "Basic business"
    extends: null
    slots:
      - key: "identity.logo.primary"
        section: identification
        label_he: "לוגו ראשי"
        label_en: "Primary logo (horizontal lockup)"
        kind: image
        constraints: {formats: ["SVG", "PNG"], note: "vector master + transparent PNG; Hebrew and Latin wordmark variants when the names differ; must read on light and dark backgrounds"}
        required: true
        targets: ["website", "print", "email", "signage", "invoice"]
        expires: "none"
      - key: "identity.logo.square"
        section: identification
        label_he: "לוגו ריבועי / אווטאר"
        label_en: "Square logo / avatar"
        kind: image
        constraints: {aspect: "1:1", rec_px: "1024x1024 master (Apple minimum)", per: {gbp: "JPG/PNG 10 KB-5 MB, rec 720x720, min 250x250", apple-maps: "square ≥1024x1024 HEIC/JPEG/PNG", linkedin: "rec 400x400, min 268x268, PNG/JPEG ≤3 MB", youtube: "renders 98x98; JPG/GIF/BMP/PNG, no animated GIF, ≤15 MB", x: "400x400", instagram: "upload 320x320, shown 110x110 (2nd)", tiktok: "shown 200x200 (2nd)", discord: "icon rec 512x512 (2nd)", facebook: "shown 176x176 desktop / 196x196 phone (2nd)"}, note: "most platforms crop to a circle - keep the mark inside the inscribed circle", refs: ["S01", "S09", "S28", "S20", "S21", "S24", "S26", "S27", "S19"]}
        required: true
        targets: ["gbp", "apple-maps", "facebook", "instagram", "whatsapp", "youtube", "x", "tiktok", "linkedin", "discord"]
        expires: "none"
      - key: "identity.logo.monochrome"
        section: identification
        label_he: "לוגו חד-צבעי (שחור / לבן)"
        label_en: "Monochrome logo (black + white knockout)"
        kind: image
        constraints: {formats: ["SVG"], note: "single-colour versions for stamp, thermal receipts, B&W print, dark backgrounds"}
        required: true
        targets: ["print", "invoice", "signage"]
        expires: "none"
      - key: "identity.logo.favicon"
        section: identification
        label_he: "פביקון"
        label_en: "Favicon"
        kind: image
        constraints: {aspect: "1:1", min_px: "8x8", rec_px: "larger than 48x48", formats: ["ICO", "PNG", "BMP", "GIF", "JPEG", "PPM", "TIFF"], note: "favicon URL must stay stable", refs: ["S29"]}
        required: true
        targets: ["website", "google-search"]
        expires: "none"
      - key: "identity.logo.app-icon"
        section: identification
        label_he: "אייקון למסך הבית"
        label_en: "App / home-screen icon"
        kind: image
        constraints: {rec_px: "192x192 and 512x512 PNG", note: "add a maskable variant (purpose any maskable); iOS apple-touch-icon 180x180 reported by secondary sources (unverified)", refs: ["S30"]}
        required: false
        targets: ["website"]
        expires: "none"
      - key: "identity.logo.animated"
        section: identification
        label_he: "לוגו מונפש"
        label_en: "Animated logo sting"
        kind: animation
        constraints: {note: "no platform spec found (unknown); short intro/outro sting, MP4 or Lottie"}
        required: false
        targets: ["youtube", "instagram", "tiktok", "website"]
        expires: "none"
      - key: "identity.logo.video-watermark"
        section: identification
        label_he: "סימן מים לסרטונים"
        label_en: "Video watermark"
        kind: image
        constraints: {aspect: "1:1", min_px: "150x150", note: "file <1 MB", refs: ["S20"]}
        required: false
        targets: ["youtube"]
        expires: "none"
      - key: "identity.name.brand-he"
        section: identification
        label_he: "שם המותג בעברית"
        label_en: "Brand name (Hebrew)"
        kind: text
        constraints: {langs: ["he"], note: "exactly as on signage/stationery; GBP forbids taglines, keywords, phone numbers, URLs and legal terms not on real signage", refs: ["S03"]}
        required: true
        targets: ["website", "gbp", "apple-maps", "bing", "waze", "b144", "dapei-zahav", "easy", "facebook", "instagram", "whatsapp", "print", "signage", "invoice"]
        expires: "on-change"
      - key: "identity.name.brand-en"
        section: identification
        label_he: "שם המותג באנגלית"
        label_en: "Brand name (English)"
        kind: text
        constraints: {langs: ["en"], note: "recommended; same naming rules as the Hebrew name", refs: ["S03"]}
        required: false
        targets: ["website", "gbp", "apple-maps", "instagram", "facebook", "linkedin", "print"]
        expires: "on-change"
      - key: "identity.name.transliteration"
        section: identification
        label_he: "תעתיק לטיני של השם"
        label_en: "Latin transliteration of the Hebrew name"
        kind: text
        constraints: {note: "basis for handle, domain and search variants"}
        required: false
        targets: ["website", "instagram", "x", "tiktok", "youtube"]
        expires: "on-change"
      - key: "identity.name.legal"
        section: identification
        label_he: "שם משפטי רשום"
        label_en: "Registered legal name"
        kind: text
        constraints: {note: "company name must end with 'בערבון מוגבל' or 'בע״מ' (Companies Law s.26); printed on tax invoices and legal pages", refs: ["S39", "S34"]}
        required: true
        targets: ["invoice", "print", "website"]
        expires: "on-change"
      - key: "identity.name.short"
        section: identification
        label_he: "שם תצוגה מקוצר"
        label_en: "Short display name"
        kind: text
        constraints: {max_chars: 30, note: "fits the Instagram name field (30, 2nd)", refs: ["S79"]}
        required: false
        targets: ["instagram", "x", "tiktok", "whatsapp"]
        expires: "on-change"
      - key: "identity.slug"
        section: identification
        label_he: "מזהה (slug) וכינוי ברשתות"
        label_en: "Slug / social handle"
        kind: text
        constraints: {note: "lowercase Latin + digits; one handle everywhere; Instagram username ≤30 (2nd); other platforms' limits unknown - check when claiming", refs: ["S79"]}
        required: true
        targets: ["website", "instagram", "facebook", "x", "tiktok", "youtube", "linkedin"]
        expires: "on-change"
      - key: "identity.domain"
        section: identification
        label_he: "דומיין"
        label_en: "Web domain"
        kind: link
        constraints: {note: ".co.il / .com; renewal period per registrar (unknown)"}
        required: true
        targets: ["website", "email"]
        expires: "registrar term (renew)"
      - key: "identity.legal.entity-type"
        section: identification
        label_he: "סוג העוסק"
        label_en: "Business entity type"
        kind: text
        constraints: {enum: ["עוסק פטור", "עוסק מורשה", "חברה בע״מ", "שותפות", "עמותה"], note: "drives document types: עוסק פטור cannot issue a חשבונית מס; 2026 עוסק פטור ceiling 122,833 ₪ turnover", refs: ["S34", "S38"]}
        required: true
        targets: ["invoice", "website"]
        expires: "on-change (check turnover yearly)"
      - key: "identity.legal.business-number"
        section: identification
        label_he: "מספר עוסק / ח״פ"
        label_en: "Business ID (VAT dealer no. / company no.)"
        kind: text
        constraints: {note: "mandatory on tax invoices; company number is 9 digits (2nd)", refs: ["S34", "S40"]}
        required: true
        targets: ["invoice", "print", "website"]
        expires: "none"
      - key: "identity.contact.address"
        section: identification
        label_he: "כתובת העסק"
        label_en: "Business address"
        kind: address
        constraints: {langs: ["he", "en"], note: "precise physical location, no P.O. boxes; mandatory on tax invoices; service-area businesses hide it on GBP", refs: ["S03", "S34"]}
        required: true
        targets: ["gbp", "apple-maps", "bing", "waze", "b144", "dapei-zahav", "easy", "website", "invoice", "print"]
        expires: "on-change"
      - key: "identity.contact.map-pin"
        section: identification
        label_he: "נעיצה במפה"
        label_en: "Map pin + entrance note"
        kind: address
        constraints: {required_if: "customers visit the premises", note: "lat/lng + entrance/parking hint; adding a Waze place from the app needs a storefront photo and volunteer review", refs: ["S11"]}
        required: false
        targets: ["gbp", "waze", "apple-maps"]
        expires: "on-change"
      - key: "identity.contact.phone"
        section: identification
        label_he: "טלפון ראשי"
        label_en: "Main phone"
        kind: phone
        constraints: {note: "E.164 (+972...); a local number, not a redirect/referral number; GBP: primary + up to 2 more", refs: ["S02", "S03"]}
        required: true
        targets: ["gbp", "website", "print", "invoice", "b144", "dapei-zahav", "easy", "facebook"]
        expires: "on-change"
      - key: "identity.contact.whatsapp"
        section: identification
        label_he: "מספר וואטסאפ עסקי"
        label_en: "WhatsApp Business number"
        kind: phone
        constraints: {note: "number registered to WhatsApp Business; publish as a wa.me click-to-chat link and QR", refs: ["S16"]}
        required: true
        targets: ["whatsapp", "website", "instagram", "facebook", "print"]
        expires: "on-change"
      - key: "identity.contact.email"
        section: identification
        label_he: "דוא״ל עסקי"
        label_en: "Business email"
        kind: text
        constraints: {note: "own-domain address; WhatsApp profile email ≤128 chars", refs: ["S15"]}
        required: true
        targets: ["website", "whatsapp", "invoice", "print", "email"]
        expires: "on-change"
      - key: "identity.contact.website-url"
        section: identification
        label_he: "כתובת האתר"
        label_en: "Website URL"
        kind: link
        constraints: {note: "full URL with https://; WhatsApp profile: up to 2 websites, ≤256 chars each", refs: ["S02", "S15"]}
        required: true
        targets: ["gbp", "whatsapp", "instagram", "facebook", "print", "email"]
        expires: "on-change"
      - key: "identity.hours.regular"
        section: identification
        label_he: "שעות פעילות קבועות"
        label_en: "Regular opening hours"
        kind: hours
        constraints: {note: "per weekday Sun-Sat incl. Friday short day and Shabbat closure; customer-facing hours only", refs: ["S02", "S03"]}
        required: true
        targets: ["gbp", "apple-maps", "bing", "website", "whatsapp", "signage", "facebook"]
        expires: "on-change"
      - key: "identity.hours.special"
        section: identification
        label_he: "שעות מיוחדות (חגים וערבי חג)"
        label_en: "Special hours (holidays, holiday eves, memorial days)"
        kind: hours
        constraints: {note: "per date, set ahead of every Jewish/Israeli holiday (Hebrew-calendar driven); feeds GBP special hours", refs: ["S02", "S62"]}
        required: true
        targets: ["gbp", "website", "whatsapp", "facebook", "instagram"]
        expires: "per-holiday"
      - key: "identity.hours.more"
        section: identification
        label_he: "שעות לפי שירות"
        label_en: "Per-service hours (delivery, takeout, pickup, phone)"
        kind: hours
        constraints: {note: "GBP 'more hours'", refs: ["S02", "S06"]}
        required: false
        targets: ["gbp"]
        expires: "on-change"
      - key: "identity.hours.shabbat-policy"
        section: identification
        label_he: "מדיניות שבת וחג"
        label_en: "Shabbat & holiday observance"
        kind: text
        constraints: {enum: ["closed", "open", "partial"], note: "drives away-message and special-hours automation"}
        required: false
        targets: ["website", "gbp", "whatsapp"]
        expires: "on-change"
      - key: "identity.opening-date"
        section: identification
        label_he: "תאריך פתיחה"
        label_en: "Opening date"
        kind: text
        constraints: {note: "month + year; may be set up to 1 year ahead; Google shows it from 90 days before", refs: ["S02"]}
        required: false
        targets: ["gbp"]
        expires: "none"
      - key: "identity.tagline"
        section: identification
        label_he: "סלוגן"
        label_en: "Tagline"
        kind: text
        constraints: {langs: ["he", "en"], max_chars: 80, note: "self-imposed ≤80 so it fits the shortest bio (TikTok 80, 2nd)", refs: ["S25"]}
        required: false
        targets: ["website", "print", "instagram", "x", "tiktok", "signage"]
        expires: "on-change"
      - key: "identity.description.short"
        section: identification
        label_he: "תיאור קצר"
        label_en: "Short description"
        kind: text
        constraints: {langs: ["he", "en"], max_chars: 139, note: "WhatsApp About is 1-139 chars; also fits the Instagram bio (150)", refs: ["S15", "S23"]}
        required: true
        targets: ["whatsapp", "instagram", "x", "tiktok", "facebook", "b144", "easy"]
        expires: "on-change"
      - key: "identity.description.medium"
        section: identification
        label_he: "תיאור בינוני"
        label_en: "Medium description"
        kind: text
        constraints: {langs: ["he", "en"], max_chars: 256, note: "WhatsApp Business app description reportedly 256 (2nd); API description ≤512", refs: ["S15", "S80"]}
        required: false
        targets: ["whatsapp", "facebook", "youtube", "linkedin"]
        expires: "on-change"
      - key: "identity.description.long"
        section: identification
        label_he: "תיאור מלא"
        label_en: "Long description"
        kind: text
        constraints: {langs: ["he", "en"], max_chars: 750, note: "GBP: no URLs or HTML; describe the business, not promotions or prices", refs: ["S02"]}
        required: true
        targets: ["gbp", "bing", "apple-maps", "b144", "dapei-zahav", "easy", "website"]
        expires: "on-change"
      - key: "identity.terminology"
        section: identification
        label_he: "מילון מונחים"
        label_en: "Terminology / glossary"
        kind: list
        constraints: {langs: ["he", "en"], note: "he↔en term pairs, preferred spellings, words to avoid, gender-inclusive forms"}
        required: false
        targets: ["website", "email", "print"]
        expires: "on-change"
      - key: "identity.color.primary"
        section: identification
        label_he: "צבע ראשי"
        label_en: "Primary colour"
        kind: color
        constraints: {note: "HEX/RGB + CMYK/Pantone for print; text on it needs WCAG 2.0 AA contrast 4.5:1 (IS 5568 is based on WCAG 2.0 AA)", refs: ["S33", "S76"]}
        required: true
        targets: ["website", "print", "signage", "instagram", "facebook"]
        expires: "on-change"
      - key: "identity.color.secondary"
        section: identification
        label_he: "צבעים משניים"
        label_en: "Secondary colours"
        kind: color
        constraints: {note: "same contrast rule for any text colour pair", refs: ["S76"]}
        required: false
        targets: ["website", "print", "signage"]
        expires: "on-change"
      - key: "identity.color.neutral"
        section: identification
        label_he: "צבעי רקע וטקסט"
        label_en: "Neutral / background / text colours"
        kind: color
        constraints: {refs: ["S76"]}
        required: false
        targets: ["website", "print"]
        expires: "on-change"
      - key: "identity.theme.typography"
        section: identification
        label_he: "גופנים"
        label_en: "Typography (Hebrew + Latin fonts)"
        kind: file
        constraints: {note: "font files + license; a Hebrew-capable family paired with a Latin face"}
        required: false
        targets: ["website", "print"]
        expires: "license term"
      - key: "identity.theme.tokens"
        section: identification
        label_he: "ערכת עיצוב (tokens)"
        label_en: "Theme tokens (light / dark)"
        kind: file
        constraints: {note: "JSON design tokens: colours, radii, spacing, light + dark"}
        required: false
        targets: ["website"]
        expires: "on-change"
      - key: "identity.illustration.style"
        section: identification
        label_he: "סגנון איור ואייקונים"
        label_en: "Illustration & icon style"
        kind: image
        constraints: {formats: ["SVG"], note: "reference set of illustrations / icons"}
        required: false
        targets: ["website", "instagram", "print"]
        expires: "on-change"
      - key: "identity.profile.gbp.category-primary"
        section: identification
        label_he: "קטגוריה ראשית ב-Google"
        label_en: "GBP primary category"
        kind: text
        constraints: {note: "exactly one; what the business IS, not what it HAS", refs: ["S02", "S03"]}
        required: true
        targets: ["gbp"]
        expires: "on-change"
      - key: "identity.profile.gbp.categories-extra"
        section: identification
        label_he: "קטגוריות נוספות ב-Google"
        label_en: "GBP additional categories"
        kind: list
        constraints: {note: "up to 9; use as few as possible", refs: ["S02", "S03"]}
        required: false
        targets: ["gbp"]
        expires: "on-change"
      - key: "identity.profile.gbp.attributes"
        section: identification
        label_he: "מאפיינים (Attributes)"
        label_en: "GBP attributes"
        kind: list
        constraints: {note: "factual attributes (e.g. outdoor seating, accessibility); available set depends on category - full list unknown", refs: ["S02"]}
        required: false
        targets: ["gbp"]
        expires: "on-change"
      - key: "identity.profile.gbp.service-area"
        section: identification
        label_he: "אזור שירות"
        label_en: "Service area"
        kind: list
        constraints: {required_if: "service-area business without a storefront", note: "cities / postal codes / places served", refs: ["S02", "S03"]}
        required: false
        targets: ["gbp"]
        expires: "on-change"
      - key: "identity.profile.gbp.cover"
        section: identification
        label_he: "תמונת נושא ב-Google"
        label_en: "GBP cover photo"
        kind: image
        constraints: {formats: ["JPG", "PNG"], rec_px: "720x720", min_px: "250x250", note: "10 KB-5 MB; cover crop aspect not specified by Google (unknown)", refs: ["S01"]}
        required: true
        targets: ["gbp"]
        expires: "on-change"
      - key: "identity.profile.gbp.url"
        section: identification
        label_he: "קישור לפרופיל Google וקישור לביקורת"
        label_en: "GBP profile URL + review link"
        kind: link
        constraints: {note: "store place ID / URL and a short review link (for QR)"}
        required: true
        targets: ["website", "whatsapp", "email", "print"]
        expires: "none"
      - key: "identity.listing.apple-maps"
        section: identification
        label_he: "כרטיס מקום ב-Apple Maps"
        label_en: "Apple Business place card"
        kind: link
        constraints: {refs: ["S09"]}
        required: false
        targets: ["apple-maps"]
        expires: "none"
      - key: "identity.profile.apple-maps.cover"
        section: identification
        label_he: "תמונת נושא ל-Apple Maps"
        label_en: "Apple Maps cover photo"
        kind: image
        constraints: {min_px: "1600x1040", formats: ["HEIC", "JPEG", "PNG"], refs: ["S09"]}
        required: false
        targets: ["apple-maps"]
        expires: "on-change"
      - key: "identity.listing.bing"
        section: identification
        label_he: "Bing Places"
        label_en: "Bing Places listing"
        kind: link
        constraints: {note: "can be imported from the Google profile", refs: ["S10"]}
        required: false
        targets: ["bing"]
        expires: "none"
      - key: "identity.listing.waze"
        section: identification
        label_he: "מקום ב-Waze"
        label_en: "Waze place"
        kind: link
        constraints: {required_if: "customers drive to the premises", refs: ["S11"]}
        required: false
        targets: ["waze"]
        expires: "none"
      - key: "identity.listing.b144"
        section: identification
        label_he: "רישום ב-B144"
        label_en: "B144 listing"
        kind: link
        constraints: {note: "free self-registration", refs: ["S13"]}
        required: false
        targets: ["b144"]
        expires: "none"
      - key: "identity.listing.dapei-zahav"
        section: identification
        label_he: "רישום בדפי זהב"
        label_en: "Dapei Zahav (d.co.il) listing"
        kind: link
        constraints: {note: "free basic listing", refs: ["S12"]}
        required: false
        targets: ["dapei-zahav"]
        expires: "none"
      - key: "identity.listing.easy"
        section: identification
        label_he: "רישום באיזי"
        label_en: "Easy (easy.co.il) listing"
        kind: link
        constraints: {refs: ["S14"]}
        required: false
        targets: ["easy"]
        expires: "none"
      - key: "identity.profile.facebook.page"
        section: identification
        label_he: "עמוד פייסבוק"
        label_en: "Facebook Page"
        kind: link
        constraints: {}
        required: true
        targets: ["facebook"]
        expires: "none"
      - key: "identity.profile.facebook.cover"
        section: identification
        label_he: "תמונת נושא בפייסבוק"
        label_en: "Facebook cover"
        kind: image
        constraints: {note: "displays 820x312 on computers and 640x360 on phones (different crops); 851x315 JPG <100 KB loads fastest (2nd)", refs: ["S18", "S19"]}
        required: true
        targets: ["facebook"]
        expires: "on-change"
      - key: "identity.profile.facebook.intro"
        section: identification
        label_he: "תיאור (Intro) בפייסבוק"
        label_en: "Facebook intro / bio"
        kind: text
        constraints: {langs: ["he"], note: "limit not verified (unknown) - reuse identity.description.short"}
        required: true
        targets: ["facebook"]
        expires: "on-change"
      - key: "identity.profile.instagram.account"
        section: identification
        label_he: "חשבון אינסטגרם עסקי"
        label_en: "Instagram business account"
        kind: link
        constraints: {}
        required: true
        targets: ["instagram"]
        expires: "none"
      - key: "identity.profile.instagram.bio"
        section: identification
        label_he: "ביו באינסטגרם"
        label_en: "Instagram bio"
        kind: text
        constraints: {langs: ["he", "en"], max_chars: 150, refs: ["S23"]}
        required: true
        targets: ["instagram"]
        expires: "on-change"
      - key: "identity.profile.instagram.highlight-covers"
        section: identification
        label_he: "כיסויי הדגשות (Highlights)"
        label_en: "Story highlight covers"
        kind: image
        constraints: {note: "story canvas 1080x1920 9:16 (2nd); icon shown as a circle", refs: ["S75"]}
        required: false
        targets: ["instagram"]
        expires: "on-change"
      - key: "identity.profile.whatsapp.category"
        section: identification
        label_he: "קטגוריה בוואטסאפ"
        label_en: "WhatsApp business category"
        kind: text
        constraints: {note: "vertical enum, e.g. RESTAURANT, RETAIL, PROF_SERVICES, BEAUTY, HEALTH, EDU, OTHER", refs: ["S15"]}
        required: true
        targets: ["whatsapp"]
        expires: "on-change"
      - key: "identity.profile.whatsapp.about"
        section: identification
        label_he: "אודות (About) בוואטסאפ"
        label_en: "WhatsApp About line"
        kind: text
        constraints: {max_chars: 139, note: "1-139 chars; links not clickable", refs: ["S15"]}
        required: true
        targets: ["whatsapp"]
        expires: "on-change"
      - key: "identity.profile.whatsapp.description"
        section: identification
        label_he: "תיאור העסק בוואטסאפ"
        label_en: "WhatsApp business description"
        kind: text
        constraints: {max_chars: 512, note: "API limit 512; app field reportedly 256 (2nd) - author to 256", refs: ["S15", "S80"]}
        required: true
        targets: ["whatsapp"]
        expires: "on-change"
      - key: "identity.profile.whatsapp.address"
        section: identification
        label_he: "כתובת בוואטסאפ"
        label_en: "WhatsApp address"
        kind: address
        constraints: {max_chars: 256, refs: ["S15"]}
        required: false
        targets: ["whatsapp"]
        expires: "on-change"
      - key: "identity.profile.whatsapp.photo"
        section: identification
        label_he: "תמונת פרופיל בוואטסאפ"
        label_en: "WhatsApp profile photo"
        kind: image
        constraints: {note: "derived from identity.logo.square; WhatsApp's own size spec unknown"}
        required: true
        targets: ["whatsapp"]
        expires: "on-change"
      - key: "identity.profile.youtube.banner"
        section: identification
        label_he: "באנר ערוץ יוטיוב"
        label_en: "YouTube channel banner"
        kind: image
        constraints: {aspect: "16:9", min_px: "2048x1152", rec_px: "2560x1440", max_mb: 6, note: "safe area for text/logo 1235x338", refs: ["S20"]}
        required: false
        targets: ["youtube"]
        expires: "on-change"
      - key: "identity.profile.x.header"
        section: identification
        label_he: "באנר ב-X"
        label_en: "X header image"
        kind: image
        constraints: {rec_px: "1500x500", refs: ["S21"]}
        required: false
        targets: ["x"]
        expires: "on-change"
      - key: "identity.profile.x.bio"
        section: identification
        label_he: "ביו ב-X"
        label_en: "X bio"
        kind: text
        constraints: {max_chars: 160, refs: ["S21"]}
        required: false
        targets: ["x"]
        expires: "on-change"
      - key: "identity.profile.tiktok.bio"
        section: identification
        label_he: "ביו בטיקטוק"
        label_en: "TikTok bio"
        kind: text
        constraints: {max_chars: 80, note: "some accounts get 160 (2nd); author to 80", refs: ["S25"]}
        required: false
        targets: ["tiktok"]
        expires: "on-change"
      - key: "identity.profile.discord.banner"
        section: identification
        label_he: "באנר שרת דיסקורד"
        label_en: "Discord server banner"
        kind: image
        constraints: {aspect: "16:9", min_px: "960x540", note: "(2nd); needs a server boost level", refs: ["S27"]}
        required: false
        targets: ["discord"]
        expires: "on-change"
      - key: "identity.profile.linkedin.cover"
        section: identification
        label_he: "תמונת נושא בלינקדאין"
        label_en: "LinkedIn Page cover"
        kind: image
        constraints: {rec_px: "1512x256", formats: ["PNG", "JPEG"], max_mb: 3, note: "minimum is also 1512x256; logo shown on light and dark backgrounds", refs: ["S28"]}
        required: false
        targets: ["linkedin"]
        expires: "on-change"
      - key: "identity.profile.link-in-bio"
        section: identification
        label_he: "עמוד קישורים (Link in bio)"
        label_en: "Link-in-bio page"
        kind: link
        constraints: {note: "own website page (e.g. /links): WhatsApp, booking/ordering, reviews; per-platform link counts not verified"}
        required: false
        targets: ["instagram", "tiktok", "x", "facebook"]
        expires: "on-change"
      - key: "content.about.story"
        section: content
        label_he: "אודות / הסיפור שלנו"
        label_en: "About / our story"
        kind: rich-text
        constraints: {langs: ["he", "en"]}
        required: true
        targets: ["website", "facebook", "linkedin"]
        expires: "on-change"
      - key: "content.about.owner"
        section: content
        label_he: "על הבעלים"
        label_en: "Owner / founder bio"
        kind: rich-text
        constraints: {langs: ["he", "en"]}
        required: false
        targets: ["website", "linkedin"]
        expires: "on-change"
      - key: "content.about.vision"
        section: content
        label_he: "חזון וערכים"
        label_en: "Vision & values"
        kind: rich-text
        constraints: {langs: ["he", "en"]}
        required: false
        targets: ["website"]
        expires: "on-change"
      - key: "content.catalog.services"
        section: content
        label_he: "שירותים ומחירים"
        label_en: "Services & prices"
        kind: price-list
        constraints: {item_fields: ["name (GBP ≤80)", "description (GBP ≤300, 2nd)", "price ₪", "duration / unit"], note: "prices shown as the total price incl. VAT (Consumer Protection s.17ד)", refs: ["S07", "S55"]}
        required: true
        targets: ["website", "gbp", "whatsapp", "facebook"]
        expires: "on-change"
      - key: "content.catalog.products"
        section: content
        label_he: "מוצרים"
        label_en: "Products"
        kind: price-list
        constraints: {required_if: "the business sells goods", item_fields: ["name (GBP ≤58)", "description (GBP ≤1,000)", "price ₪ (total)", "photos", "link", "code"], note: "WhatsApp catalog ≤500 items and ≤10 images per item (2nd); GBP Products via POS listed for US/CA/UK/IE - Israel availability unknown", refs: ["S07", "S17", "S55", "S02"]}
        required: false
        targets: ["website", "gbp", "whatsapp", "instagram", "facebook"]
        expires: "on-change"
      - key: "content.faq"
        section: content
        label_he: "שאלות ותשובות"
        label_en: "FAQ (question/answer pairs)"
        kind: list
        constraints: {langs: ["he", "en"]}
        required: false
        targets: ["website", "whatsapp", "gbp"]
        expires: "on-change"
      - key: "content.website.home"
        section: content
        label_he: "דף הבית"
        label_en: "Home page copy"
        kind: rich-text
        constraints: {langs: ["he", "en"], note: "headline, sub-headline, primary CTA (WhatsApp / call / book), trust signals; RTL-first"}
        required: true
        targets: ["website"]
        expires: "on-change"
      - key: "content.website.services"
        section: content
        label_he: "דף שירותים / מוצרים"
        label_en: "Services / products page"
        kind: rich-text
        constraints: {note: "rendered from content.catalog.*"}
        required: true
        targets: ["website"]
        expires: "on-change"
      - key: "content.website.contact"
        section: content
        label_he: "דף יצירת קשר"
        label_en: "Contact page"
        kind: rich-text
        constraints: {note: "address + map, phone, WhatsApp link, hours, form; a form collecting personal data needs a privacy notice (duty to inform)", refs: ["S45"]}
        required: true
        targets: ["website"]
        expires: "on-change"
      - key: "content.website.privacy-policy"
        section: content
        label_he: "מדיניות פרטיות"
        label_en: "Privacy policy"
        kind: document
        constraints: {required_if: "the site/app collects personal data (forms, analytics, pixels)", note: "Amendment 13 in force 14 Aug 2025: state purpose, controller identity + contact, whether providing data is a legal duty, data-subject rights (2nd detail)", refs: ["S45"]}
        required: false
        targets: ["website"]
        expires: "on-change"
      - key: "content.website.terms"
        section: content
        label_he: "תקנון / תנאי שימוש"
        label_en: "Terms of use / sale"
        kind: document
        constraints: {required_if: "selling or booking online", langs: ["he"]}
        required: false
        targets: ["website"]
        expires: "on-change"
      - key: "content.website.accessibility-statement"
        section: content
        label_he: "הצהרת נגישות"
        label_en: "Accessibility statement"
        kind: document
        constraints: {note: "reg. 35ה: prominent place on site/app, the accessibility adjustments made + accessibility coordinator details and contact; usual fields: level (IS 5568 = WCAG 2.0 AA), browsers tested, exemptions, last update; exempt from web adjustments: עוסק פטור or avg turnover ≤100,000 ₪ (35ו(ז)), conditional ≤1,000,000 ₪ (35ו(ט)); statement duty for exempt businesses unknown", refs: ["S32", "S33"]}
        required: true
        targets: ["website"]
        expires: "on-change (shows last-update date)"
      - key: "content.website.cookie-notice"
        section: content
        label_he: "הודעת עוגיות (Cookies)"
        label_en: "Cookie notice / consent"
        kind: text
        constraints: {required_if: "non-essential cookies or ad pixels are used", note: "Privacy Protection Authority 2020 draft recommendation: explicit opt-in; binding status after Amendment 13 unknown", refs: ["S46"]}
        required: false
        targets: ["website"]
        expires: "on-change"
      - key: "content.website.seo-meta"
        section: content
        label_he: "כותרות ותיאורי מטא"
        label_en: "SEO titles & meta descriptions"
        kind: text
        constraints: {langs: ["he", "en"], note: "per page; hard length limits unknown"}
        required: true
        targets: ["website", "google-search"]
        expires: "on-change"
      - key: "content.docs.business-card"
        section: content
        label_he: "כרטיס ביקור"
        label_en: "Business card"
        kind: document
        constraints: {note: "90x50 mm common in Israel (2nd); print PDF with printer-specific bleed; Hebrew front / English back", refs: ["S41"]}
        required: true
        targets: ["print"]
        expires: "on-change"
      - key: "content.docs.letterhead"
        section: content
        label_he: "נייר מכתבים"
        label_en: "Letterhead"
        kind: document
        constraints: {note: "A4 210x297 mm; legal name (company with בע״מ), business number, address, contacts", refs: ["S42", "S39"]}
        required: false
        targets: ["print", "email"]
        expires: "on-change"
      - key: "content.docs.invoice-header"
        section: content
        label_he: "כותרת חשבונית / קבלה"
        label_en: "Invoice / receipt header"
        kind: document
        constraints: {note: "tax invoice: serial no., the words 'חשבונית מס', 'מקור' / 'נאמן למקור', business name + address, עוסק מורשה no., date, transaction details, price without and with VAT, signature; 9-digit allocation no. (מספר הקצאה) for invoices above 5,000 ₪ before VAT from 1 Jun 2026; עוסק פטור issues receipts / transaction invoices only", refs: ["S34", "S35", "S36", "S37"]}
        required: true
        targets: ["invoice", "email"]
        expires: "on-change (allocation threshold changes by date)"
      - key: "content.docs.email-signature"
        section: content
        label_he: "חתימת דוא״ל"
        label_en: "Email signature"
        kind: rich-text
        constraints: {note: "HTML: name, role, phone, WhatsApp link, address, logo with alt text; pixel spec unknown"}
        required: true
        targets: ["email"]
        expires: "on-change"
      - key: "content.docs.stamp"
        section: content
        label_he: "חותמת עסק"
        label_en: "Business stamp"
        kind: image
        constraints: {note: "legal name + business number (+ address); no legal requirement found (unknown)"}
        required: false
        targets: ["print", "invoice"]
        expires: "on-change"
      - key: "content.reviews.testimonials"
        section: content
        label_he: "המלצות לקוחות"
        label_en: "Testimonials"
        kind: list
        constraints: {note: "quote, name/initials with consent, date, source link"}
        required: false
        targets: ["website", "facebook", "instagram"]
        expires: "on-change"
      - key: "content.reviews.request"
        section: content
        label_he: "בקשת ביקורת"
        label_en: "Review-request message"
        kind: text
        constraints: {langs: ["he"], note: "template + short Google review link + QR"}
        required: false
        targets: ["whatsapp", "email", "print"]
        expires: "on-change"
      - key: "content.reviews.replies"
        section: content
        label_he: "תבניות מענה לביקורות"
        label_en: "Review reply templates"
        kind: list
        constraints: {langs: ["he", "en"]}
        required: false
        targets: ["gbp", "facebook"]
        expires: "on-change"
      - key: "content.gbp.posts"
        section: content
        label_he: "פוסטים בפרופיל Google"
        label_en: "GBP posts (update / offer / event)"
        kind: rich-text
        constraints: {note: "offer needs title + dates/times; ≤1,500 chars (2nd); archived after 6 months unless a date range is set", refs: ["S04", "S08"]}
        required: false
        targets: ["gbp"]
        expires: "P6M (archived)"
      - key: "content.newsletter.template"
        section: content
        label_he: "תבנית ניוזלטר"
        label_en: "Newsletter template"
        kind: rich-text
        constraints: {note: "prior consent; the word 'פרסומת' at the start / in the subject; sender name, address, contact; unsubscribe in every message", refs: ["S43", "S44"]}
        required: false
        targets: ["email"]
        expires: "on-change"
      - key: "content.newsletter.consent"
        section: content
        label_he: "נוסח הסכמה לדיוור"
        label_en: "Marketing-consent wording"
        kind: text
        constraints: {required_if: "sending marketing messages (email / SMS / WhatsApp)", refs: ["S43"]}
        required: false
        targets: ["website", "whatsapp"]
        expires: "on-change"
      - key: "content.whatsapp.greeting"
        section: content
        label_he: "הודעת פתיחה בוואטסאפ"
        label_en: "WhatsApp greeting message"
        kind: text
        constraints: {langs: ["he", "en"], note: "length limit unknown"}
        required: false
        targets: ["whatsapp"]
        expires: "on-change"
      - key: "content.whatsapp.away"
        section: content
        label_he: "הודעת היעדרות בוואטסאפ"
        label_en: "WhatsApp away message"
        kind: text
        constraints: {note: "tied to hours + Shabbat policy"}
        required: false
        targets: ["whatsapp"]
        expires: "per-holiday"
      - key: "content.whatsapp.quick-replies"
        section: content
        label_he: "תשובות מהירות"
        label_en: "WhatsApp quick replies"
        kind: list
        constraints: {}
        required: false
        targets: ["whatsapp"]
        expires: "on-change"
      - key: "content.news"
        section: content
        label_he: "חדשות ועדכונים"
        label_en: "News & announcements"
        kind: rich-text
        constraints: {}
        required: false
        targets: ["website", "facebook", "gbp"]
        expires: "none"
      - key: "media.photo.storefront"
        section: media
        label_he: "חזית העסק"
        label_en: "Storefront / exterior"
        kind: image
        constraints: {required_if: "customers visit the premises", formats: ["JPG", "PNG"], rec_px: "720x720", min_px: "250x250", note: "10 KB-5 MB, in focus, no heavy filters; sign readable; Waze place creation needs one", refs: ["S01", "S11"]}
        required: false
        targets: ["gbp", "waze", "apple-maps", "website", "b144", "easy"]
        expires: "yearly refresh (recommended)"
      - key: "media.photo.interior"
        section: media
        label_he: "פנים העסק"
        label_en: "Interior"
        kind: image
        constraints: {required_if: "customers visit the premises", note: "GBP photo spec", refs: ["S01"]}
        required: false
        targets: ["gbp", "website", "facebook"]
        expires: "yearly refresh (recommended)"
      - key: "media.photo.team"
        section: media
        label_he: "צוות"
        label_en: "Team"
        kind: image
        constraints: {note: "GBP photo spec", refs: ["S01"]}
        required: false
        targets: ["gbp", "website", "linkedin"]
        expires: "on-change"
      - key: "media.photo.owner-portrait"
        section: media
        label_he: "דיוקן בעלים"
        label_en: "Owner portrait"
        kind: image
        constraints: {note: "square-safe + 4:5 crop; Instagram keeps 1080-wide images between 1.91:1 and 3:4", refs: ["S22"]}
        required: false
        targets: ["website", "linkedin", "facebook", "instagram"]
        expires: "on-change"
      - key: "media.photo.products"
        section: media
        label_he: "מוצרים / דוגמאות עבודה"
        label_en: "Products / work samples"
        kind: image
        constraints: {note: "GBP spec; WhatsApp catalog ≤10 images per item (2nd)", refs: ["S01", "S17", "S22"]}
        required: true
        targets: ["gbp", "website", "whatsapp", "instagram", "facebook"]
        expires: "on-change"
      - key: "media.photo.at-work"
        section: media
        label_he: "העסק בפעולה"
        label_en: "At work / service in action"
        kind: image
        constraints: {refs: ["S01"]}
        required: false
        targets: ["gbp", "website", "instagram"]
        expires: "on-change"
      - key: "media.image.social-share"
        section: media
        label_he: "תמונת שיתוף (Open Graph)"
        label_en: "Social-share image (Open Graph)"
        kind: image
        constraints: {aspect: "1.91:1", rec_px: "1200x630", min_px: "600x315 (large preview); 200x200 absolute", max_mb: 8, refs: ["S31"]}
        required: true
        targets: ["website", "facebook", "whatsapp", "linkedin", "x"]
        expires: "on-change"
      - key: "media.image.post-templates"
        section: media
        label_he: "תבניות פוסט וסטורי"
        label_en: "Post & story templates"
        kind: image
        constraints: {note: "feed 1080 wide within 1.91:1-3:4 (e.g. 1080x1350); story/reel 1080x1920 (2nd)", refs: ["S22", "S75"]}
        required: false
        targets: ["instagram", "facebook", "whatsapp"]
        expires: "on-change"
      - key: "media.image.qr-codes"
        section: media
        label_he: "קודי QR"
        label_en: "QR codes (WhatsApp chat, review link, website)"
        kind: image
        constraints: {formats: ["SVG"]}
        required: false
        targets: ["print", "signage"]
        expires: "on-change"
      - key: "media.video.intro"
        section: media
        label_he: "סרטון היכרות"
        label_en: "Intro video"
        kind: video
        constraints: {note: "GBP: ≤30 s, ≤75 MB, ≥720p; vertical 1080x1920 cut for reels/stories (2nd)", refs: ["S01", "S75"]}
        required: false
        targets: ["gbp", "website", "youtube", "instagram", "facebook", "tiktok"]
        expires: "on-change"
      - key: "media.video.shorts"
        section: media
        label_he: "סרטונים קצרים אנכיים"
        label_en: "Short vertical videos"
        kind: video
        constraints: {aspect: "9:16", rec_px: "1080x1920", note: "(2nd)", refs: ["S75"]}
        required: false
        targets: ["instagram", "tiktok", "youtube", "facebook"]
        expires: "none"
    calendar:
      - id: "rosh-hashana"
        name_he: "ראש השנה"
        trigger: "hebrew 1-2 Tishrei (5787: 12-13 Sep 2026); hours −14d; post −3d"
        channels: ["gbp", "instagram", "facebook", "whatsapp", "email", "website"]
        assets:
          - {kind: "hours", spec: "GBP special hours: erev chag + 2 days", count: 1}
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
          - {kind: "image", spec: "1080x1920 (9:16) [S75]", count: 1}
          - {kind: "text", spec: "greeting he (+en)", count: 1}
          - {kind: "rich-text", spec: "newsletter; 'פרסומת' in subject if promotional [S43]", count: 1}
      - id: "yom-kippur"
        name_he: "יום כיפור"
        trigger: "hebrew 10 Tishrei (5787: 21 Sep 2026); hours −14d"
        channels: ["gbp", "whatsapp", "website", "instagram"]
        assets:
          - {kind: "hours", spec: "GBP special hours (closed)", count: 1}
          - {kind: "text", spec: "WhatsApp away message", count: 1}
          - {kind: "image", spec: "1080x1920 (9:16) [S75]", count: 1}
      - id: "sukkot"
        name_he: "סוכות ושמחת תורה"
        trigger: "hebrew 15-22 Tishrei (5787: 26 Sep-3 Oct 2026)"
        channels: ["gbp", "instagram", "facebook", "whatsapp"]
        assets:
          - {kind: "hours", spec: "chol hamoed + chag hours", count: 1}
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
          - {kind: "image", spec: "1080x1920 (9:16) [S75]", count: 1}
      - id: "hanukkah"
        name_he: "חנוכה"
        trigger: "hebrew 25 Kislev, 8 days (5787: 5-12 Dec 2026)"
        channels: ["gbp", "instagram", "facebook", "whatsapp", "email"]
        assets:
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
          - {kind: "image", spec: "1080x1920 (9:16) [S75]", count: 8}
          - {kind: "rich-text", spec: "GBP offer post: title + dates [S04]", count: 1}
      - id: "tu-bishvat"
        name_he: "ט״ו בשבט"
        trigger: "hebrew 15 Shevat (5787: 23 Jan 2027)"
        channels: ["instagram", "facebook"]
        assets:
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
      - id: "purim"
        name_he: "פורים"
        trigger: "hebrew 14 Adar (Adar II in leap years; 15 in Jerusalem) (5787: 23 Mar 2027)"
        channels: ["gbp", "instagram", "facebook", "whatsapp"]
        assets:
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
          - {kind: "image", spec: "1080x1920 (9:16) [S75]", count: 2}
      - id: "pesach"
        name_he: "פסח"
        trigger: "hebrew 15-21 Nisan (5787: 22-28 Apr 2027); sale −21d; hours −14d"
        channels: ["gbp", "instagram", "facebook", "whatsapp", "email", "website"]
        assets:
          - {kind: "hours", spec: "GBP special hours for chag + chol hamoed", count: 1}
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 2}
          - {kind: "image", spec: "1080x1920 (9:16) [S75]", count: 3}
          - {kind: "rich-text", spec: "pre-holiday sale newsletter [S43]", count: 1}
      - id: "yom-hashoah"
        name_he: "יום הזיכרון לשואה ולגבורה"
        trigger: "hebrew 27 Nisan (may shift; 5787: 4 May 2027)"
        channels: ["instagram", "facebook", "website"]
        assets:
          - {kind: "text", spec: "memorial message, no promotion", count: 1}
          - {kind: "hours", spec: "eve-of-day hours", count: 1}
      - id: "yom-hazikaron"
        name_he: "יום הזיכרון לחללי מערכות ישראל"
        trigger: "hebrew 4 Iyar (may shift; 5787: 11 May 2027)"
        channels: ["instagram", "facebook", "website"]
        assets:
          - {kind: "text", spec: "memorial message, no promotion", count: 1}
          - {kind: "hours", spec: "eve-of-day hours", count: 1}
      - id: "yom-haatzmaut"
        name_he: "יום העצמאות"
        trigger: "hebrew 5 Iyar (may shift; 5787: 12 May 2027)"
        channels: ["gbp", "instagram", "facebook", "whatsapp"]
        assets:
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
          - {kind: "image", spec: "1080x1920 (9:16) [S75]", count: 1}
          - {kind: "hours", spec: "GBP special hours", count: 1}
      - id: "shavuot"
        name_he: "שבועות"
        trigger: "hebrew 6 Sivan (5787: 11 Jun 2027)"
        channels: ["gbp", "instagram", "facebook", "whatsapp"]
        assets:
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
          - {kind: "hours", spec: "GBP special hours", count: 1}
      - id: "tisha-bav"
        name_he: "תשעה באב"
        trigger: "hebrew 9 Av (Sunday if Shabbat) (5787: 12 Aug 2027)"
        channels: ["gbp", "whatsapp", "website"]
        assets:
          - {kind: "hours", spec: "eve + day hours", count: 1}
      - id: "tu-bav"
        name_he: "ט״ו באב"
        trigger: "hebrew 15 Av (5787: 18 Aug 2027)"
        channels: ["instagram", "facebook", "whatsapp"]
        assets:
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
          - {kind: "image", spec: "1080x1920 (9:16) [S75]", count: 1}
      - id: "back-to-school"
        name_he: "חזרה ללימודים"
        trigger: "Israeli school-year opening (date set yearly by the Ministry of Education - verify); −21d"
        channels: ["instagram", "facebook", "email"]
        assets:
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
          - {kind: "rich-text", spec: "newsletter [S43]", count: 1}
      - id: "black-friday"
        name_he: "בלאק פריידיי / סייבר מאנדיי"
        trigger: "rule: Friday after the 4th Thursday of November, + following Monday"
        channels: ["gbp", "instagram", "facebook", "whatsapp", "email"]
        assets:
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 2}
          - {kind: "image", spec: "1080x1920 (9:16) [S75]", count: 3}
          - {kind: "rich-text", spec: "GBP offer post [S04]", count: 1}
      - id: "weekly-shabbat"
        name_he: "שבת שלום / סוף שבוע"
        trigger: "weekly: Friday, before closing"
        channels: ["instagram", "whatsapp"]
        assets:
          - {kind: "image", spec: "1080x1920 (9:16) [S75]", count: 1}
      - id: "monthly-newsletter"
        name_he: "ניוזלטר חודשי"
        trigger: "monthly"
        channels: ["email"]
        assets:
          - {kind: "rich-text", spec: "newsletter template (spam-law compliant) [S43]", count: 1}
      - id: "quarterly-gbp-refresh"
        name_he: "רענון פרופיל Google"
        trigger: "quarterly"
        channels: ["gbp"]
        assets:
          - {kind: "image", spec: "JPG/PNG 10 KB-5 MB, rec 720x720, min 250x250 [S01]", count: 3}
          - {kind: "rich-text", spec: "GBP post text ≤1,500 chars (2nd) [S08]", count: 1}
      - id: "yearly-compliance"
        name_he: "בדיקת ציות שנתית"
        trigger: "yearly: January"
        channels: ["website", "invoice"]
        assets:
          - {kind: "document", spec: "accessibility statement re-check, last-update date [S32]", count: 1}
          - {kind: "document", spec: "privacy policy review [S45]", count: 1}
          - {kind: "document", spec: "invoice header vs allocation-number threshold [S36]", count: 1}
          - {kind: "text", spec: "עוסק פטור ceiling check [S38]", count: 1}
      - id: "business-anniversary"
        name_he: "יום הולדת לעסק"
        trigger: "yearly on identity.opening-date"
        channels: ["gbp", "instagram", "facebook", "whatsapp", "email"]
        assets:
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
          - {kind: "image", spec: "1080x1920 (9:16) [S75]", count: 1}
  - id: basic-restaurant
    name_he: "מסעדה בסיסית"
    name_en: "Basic restaurant"
    extends: "business-basic"
    slots:
      - key: "identity.profile.gbp.category-primary"
        section: identification
        label_he: "קטגוריה ראשית ב-Google (מסעדה)"
        label_en: "GBP primary category (restaurant)"
        kind: text
        constraints: {note: "override: a restaurant / cuisine category; restaurant hours = when diners can sit down and dine", refs: ["S03", "S06"]}
        required: true
        targets: ["gbp"]
        expires: "on-change"
      - key: "identity.profile.whatsapp.category"
        section: identification
        label_he: "קטגוריה בוואטסאפ"
        label_en: "WhatsApp business category"
        kind: text
        constraints: {enum: ["RESTAURANT"], note: "override", refs: ["S15"]}
        required: true
        targets: ["whatsapp"]
        expires: "on-change"
      - key: "media.photo.products"
        section: media
        label_he: "מוצרים / דוגמאות עבודה"
        label_en: "Products / work samples"
        kind: image
        constraints: {note: "override: superseded by media.food.*", refs: ["S01"]}
        required: false
        targets: ["gbp", "website"]
        expires: "on-change"
      - key: "identity.restaurant.cuisines"
        section: identification
        label_he: "סוגי מטבח"
        label_en: "Cuisine types"
        kind: list
        constraints: {note: "map to each platform's taxonomy", refs: ["S02", "S70"]}
        required: true
        targets: ["gbp", "wolt", "tenbis", "rest", "tripadvisor", "website"]
        expires: "on-change"
      - key: "identity.restaurant.kashrut-status"
        section: identification
        label_he: "סטטוס כשרות"
        label_en: "Kashrut status"
        kind: text
        constraints: {enum: ["not-kosher", "kosher-rabbinate", "kosher-rabbinate-mehadrin", "private-supervision-only"], note: "only a certificate holder may present the place as 'כשר' in writing (s.3); private supervision alone: 'בהשגחה' / 'בפיקוח', not 'כשר'", refs: ["S47", "S50"]}
        required: true
        targets: ["website", "gbp", "wolt", "tenbis", "mishloha", "rest", "tabit", "ontopo", "signage"]
        expires: "on-change"
      - key: "identity.restaurant.kashrut-class"
        section: identification
        label_he: "סיווג: חלבי / בשרי / פרווה"
        label_en: "Kashrut class (dairy / meat / pareve)"
        kind: text
        constraints: {enum: ["חלבי", "בשרי", "פרווה"], required_if: "kosher or supervised", refs: ["S49"]}
        required: false
        targets: ["website", "wolt", "tenbis", "rest"]
        expires: "on-change"
      - key: "identity.restaurant.service-modes"
        section: identification
        label_he: "אופני שירות"
        label_en: "Service modes"
        kind: list
        constraints: {enum: ["dine-in", "takeaway", "pickup", "delivery", "catering"], refs: ["S06"]}
        required: true
        targets: ["gbp", "website", "wolt", "tenbis"]
        expires: "on-change"
      - key: "identity.restaurant.seating"
        section: identification
        label_he: "ישיבה וקיבולת"
        label_en: "Seating & capacity"
        kind: list
        constraints: {note: "indoor / outdoor / sukkah / private room + seats; GBP attribute example: outdoor seating; Rest filters private rooms", refs: ["S02", "S70"]}
        required: false
        targets: ["gbp", "rest", "tabit", "ontopo", "website"]
        expires: "on-change"
      - key: "identity.restaurant.accessibility"
        section: identification
        label_he: "נגישות המקום"
        label_en: "Premises accessibility"
        kind: list
        constraints: {note: "entrance, restroom, seating; mirrored in the accessibility statement", refs: ["S02", "S32"]}
        required: true
        targets: ["gbp", "website", "rest"]
        expires: "on-change"
      - key: "identity.restaurant.price-range"
        section: identification
        label_he: "טווח מחירים"
        label_en: "Price range"
        kind: text
        constraints: {note: "per-platform scale; GBP price-range field details unknown", refs: ["S70"]}
        required: false
        targets: ["gbp", "rest", "tripadvisor"]
        expires: "on-change"
      - key: "identity.hours.kitchen"
        section: identification
        label_he: "שעות מטבח (הזמנה אחרונה)"
        label_en: "Kitchen hours (last order)"
        kind: hours
        constraints: {note: "GBP restaurant hours = when diners can sit down and dine", refs: ["S03"]}
        required: true
        targets: ["gbp", "website", "tabit", "ontopo"]
        expires: "on-change"
      - key: "identity.hours.delivery"
        section: identification
        label_he: "שעות משלוחים"
        label_en: "Delivery hours"
        kind: hours
        constraints: {required_if: "offers delivery", refs: ["S06"]}
        required: false
        targets: ["gbp", "wolt", "tenbis", "mishloha"]
        expires: "on-change"
      - key: "identity.hours.takeaway"
        section: identification
        label_he: "שעות טייק-אווי / איסוף"
        label_en: "Takeaway / pickup hours"
        kind: hours
        constraints: {required_if: "offers takeaway", refs: ["S06"]}
        required: false
        targets: ["gbp"]
        expires: "on-change"
      - key: "identity.hours.business-lunch"
        section: identification
        label_he: "שעות עסקית"
        label_en: "Business-lunch hours"
        kind: hours
        constraints: {}
        required: false
        targets: ["website", "gbp", "tenbis"]
        expires: "on-change"
      - key: "identity.links.menu"
        section: identification
        label_he: "קישור לתפריט"
        label_en: "Menu URL"
        kind: link
        constraints: {refs: ["S06"]}
        required: true
        targets: ["gbp", "instagram", "facebook", "whatsapp", "rest"]
        expires: "on-change"
      - key: "identity.links.order"
        section: identification
        label_he: "קישור להזמנה אונליין"
        label_en: "Order-online link"
        kind: link
        constraints: {note: "Order with Google or platform ordering link", refs: ["S06"]}
        required: false
        targets: ["gbp", "instagram", "website"]
        expires: "on-change"
      - key: "identity.links.reservations"
        section: identification
        label_he: "קישור להזמנת שולחן"
        label_en: "Reservation link"
        kind: link
        constraints: {required_if: "takes reservations", note: "Tabit / Ontopo booking page; Reserve with Google availability in Israel unknown", refs: ["S06", "S67", "S68"]}
        required: false
        targets: ["gbp", "website", "instagram", "facebook"]
        expires: "on-change"
      - key: "identity.listing.wolt"
        section: identification
        label_he: "עמוד בוולט"
        label_en: "Wolt venue page"
        kind: link
        constraints: {refs: ["S63"]}
        required: false
        targets: ["wolt"]
        expires: "none"
      - key: "identity.listing.tenbis"
        section: identification
        label_he: "עמוד בתן ביס"
        label_en: "10bis page"
        kind: link
        constraints: {refs: ["S65"]}
        required: false
        targets: ["tenbis"]
        expires: "none"
      - key: "identity.listing.cibus"
        section: identification
        label_he: "סיבוס פלאקסי"
        label_en: "Cibus Pluxee listing"
        kind: link
        constraints: {refs: ["S66"]}
        required: false
        targets: ["cibus"]
        expires: "none"
      - key: "identity.listing.mishloha"
        section: identification
        label_he: "משלוחה"
        label_en: "Mishloha listing"
        kind: link
        constraints: {refs: ["S66"]}
        required: false
        targets: ["mishloha"]
        expires: "none"
      - key: "identity.listing.tabit"
        section: identification
        label_he: "טאביט"
        label_en: "Tabit listing"
        kind: link
        constraints: {refs: ["S68"]}
        required: false
        targets: ["tabit"]
        expires: "none"
      - key: "identity.listing.ontopo"
        section: identification
        label_he: "אונטופו"
        label_en: "Ontopo listing"
        kind: link
        constraints: {refs: ["S67"]}
        required: false
        targets: ["ontopo"]
        expires: "none"
      - key: "identity.listing.tripadvisor"
        section: identification
        label_he: "טריפאדוויזר"
        label_en: "Tripadvisor listing"
        kind: link
        constraints: {refs: ["S69"]}
        required: false
        targets: ["tripadvisor"]
        expires: "none"
      - key: "identity.listing.rest"
        section: identification
        label_he: "רסט (Rest)"
        label_en: "Rest (rest.co.il) listing"
        kind: link
        constraints: {refs: ["S70"]}
        required: false
        targets: ["rest"]
        expires: "none"
      - key: "content.menu.dine-in"
        section: content
        label_he: "תפריט במקום"
        label_en: "Dine-in menu"
        kind: price-list
        constraints: {item_fields: ["name he/en", "description he/en", "section", "price ₪ (total)", "variants/portions", "photos", "allergens", "dietary tags", "spice level", "kashrut class", "availability (days/hours)", "popular flag", "code/SKU"], note: "GBP menu editor holds sections, items, descriptions, prices; prices are total prices in ₪ incl. VAT", refs: ["S05", "S54", "S55"]}
        required: true
        targets: ["website", "gbp", "print", "rest", "tabit", "ontopo"]
        expires: "on-change"
      - key: "content.menu.takeaway"
        section: content
        label_he: "תפריט טייק-אווי"
        label_en: "Takeaway menu"
        kind: price-list
        constraints: {item_fields: ["name he/en", "description he/en", "section", "price ₪ (total)", "variants/portions", "photos", "allergens", "dietary tags", "spice level", "kashrut class", "availability (days/hours)", "popular flag", "code/SKU"], refs: ["S55"]}
        required: false
        targets: ["website", "gbp", "print"]
        expires: "on-change"
      - key: "content.menu.delivery"
        section: content
        label_he: "תפריט משלוחים"
        label_en: "Delivery menu"
        kind: price-list
        constraints: {required_if: "offers delivery", item_fields: ["name he/en", "description he/en", "section", "price ₪ (total)", "variants/portions", "photos", "allergens", "dietary tags", "spice level", "kashrut class", "availability (days/hours)", "popular flag", "code/SKU"], note: "synced to platforms; one photo per item per platform spec", refs: ["S63"]}
        required: false
        targets: ["wolt", "tenbis", "mishloha", "cibus", "website"]
        expires: "on-change"
      - key: "content.menu.kids"
        section: content
        label_he: "תפריט ילדים"
        label_en: "Kids menu"
        kind: price-list
        constraints: {}
        required: false
        targets: ["website", "print"]
        expires: "on-change"
      - key: "content.menu.drinks"
        section: content
        label_he: "תפריט משקאות ויין"
        label_en: "Drinks & wine list"
        kind: price-list
        constraints: {note: "alcohol: licensing item 4.8 conditions; Business Licensing Law s.2(א1) restricts selling/serving/supplying alcohol 23:00-06:00 with exceptions - verify scope for on-premise service", refs: ["S53", "S57"]}
        required: false
        targets: ["website", "print", "gbp"]
        expires: "on-change"
      - key: "content.menu.desserts"
        section: content
        label_he: "תפריט קינוחים"
        label_en: "Desserts menu"
        kind: price-list
        constraints: {}
        required: false
        targets: ["website", "print"]
        expires: "on-change"
      - key: "content.menu.business-lunch"
        section: content
        label_he: "תפריט עסקית"
        label_en: "Business-lunch menu (עסקית)"
        kind: price-list
        constraints: {refs: ["S55"]}
        required: false
        targets: ["website", "gbp", "tenbis", "instagram"]
        expires: "on-change"
      - key: "content.menu.seasonal"
        section: content
        label_he: "תפריט עונתי / חג"
        label_en: "Seasonal / holiday menu"
        kind: price-list
        constraints: {}
        required: false
        targets: ["website", "gbp", "instagram", "wolt"]
        expires: "seasonal"
      - key: "content.menu.pesach"
        section: content
        label_he: "תפריט פסח (כשר לפסח)"
        label_en: "Pesach (kosher-for-Passover) menu"
        kind: price-list
        constraints: {required_if: "operating kosher-for-Passover", note: "write 'כשר לפסח' only with a Pesach certificate; otherwise a closure notice or chametz-law-compliant operation (no public display of chametz for sale/consumption during Pesach; not in non-Jewish-majority localities)", refs: ["S47", "S51", "S52"]}
        required: false
        targets: ["website", "gbp", "wolt", "tenbis", "print"]
        expires: "seasonal: Pesach"
      - key: "content.menu.allergen-legend"
        section: content
        label_he: "מקרא אלרגנים"
        label_en: "Allergen legend"
        kind: list
        constraints: {note: "not mandated for restaurant menus (a 2022 bill proposed numbered marking); use the EU-14 set: cereals with gluten, crustaceans, eggs, fish, peanuts, soy, milk, tree nuts, celery, mustard, sesame, sulphites, lupin, molluscs", refs: ["S72", "S73", "S74"]}
        required: false
        targets: ["website", "print", "wolt", "tenbis"]
        expires: "on-change"
      - key: "content.menu.dietary-legend"
        section: content
        label_he: "מקרא סימונים תזונתיים"
        label_en: "Dietary tags legend"
        kind: list
        constraints: {enum: ["Vegan", "Vegetarian", "GlutenFree", "LowLactose", "Kosher", "Halal", "Diabetic", "LowCalorie", "LowFat", "LowSalt", "Hindu"], note: "schema.org RestrictedDiet values", refs: ["S71"]}
        required: false
        targets: ["website", "print", "wolt", "tenbis"]
        expires: "on-change"
      - key: "content.menu.popular-dishes"
        section: content
        label_he: "מנות פופולריות"
        label_en: "Popular dishes"
        kind: list
        constraints: {refs: ["S78"]}
        required: false
        targets: ["gbp"]
        expires: "on-change"
      - key: "content.kosher.certificate"
        section: content
        label_he: "תעודת כשרות"
        label_en: "Kashrut certificate"
        kind: document
        constraints: {required_if: "presenting the restaurant as kosher", note: "issued by the local rabbi / Chief Rabbinate; shows owner, address, חלבי/בשרי/פרווה, רגיל/מהדרין, supervisor name + mobile, anti-forgery barcode sticker; valid 1 year from issue (reg. 9); display openly at the premises, only while valid (s.10)", refs: ["S47", "S48", "S49"]}
        required: false
        targets: ["signage", "website", "gbp", "wolt", "tenbis", "rest", "tabit", "ontopo"]
        expires: "P1Y (from issue)"
      - key: "content.kosher.pesach-certificate"
        section: content
        label_he: "תעודת כשרות לפסח"
        label_en: "Pesach kashrut certificate"
        kind: document
        constraints: {required_if: "operating kosher-for-Passover", note: "separate Pesach certificate from the local rabbinate; a private badatz approval must come with a current local-rabbinate certificate", refs: ["S51"]}
        required: false
        targets: ["signage", "website", "wolt", "tenbis"]
        expires: "seasonal: Pesach"
      - key: "content.kosher.private-hechsher"
        section: content
        label_he: "תעודת השגחה פרטית (בד״ץ / צהר)"
        label_en: "Private hechsher / supervision certificate"
        kind: document
        constraints: {note: "alongside a rabbinate certificate, or alone with 'בהשגחה' / 'בפיקוח' wording (not 'כשר')", refs: ["S50"]}
        required: false
        targets: ["signage", "website"]
        expires: "per issuer (unknown)"
      - key: "content.kosher.statement"
        section: content
        label_he: "נוסח כשרות לפרסום"
        label_en: "Kashrut statement text"
        kind: text
        constraints: {required_if: "kosher or supervised", langs: ["he", "en"], refs: ["S47", "S50"]}
        required: false
        targets: ["website", "wolt", "tenbis", "rest", "gbp"]
        expires: "on-change"
      - key: "content.license.business"
        section: content
        label_he: "רישיון עסק"
        label_en: "Business license"
        kind: document
        constraints: {note: "food businesses are licensed; default validity 15 years, shorter per business type (s.7א); a public-display duty is not in the Act (unknown - check license conditions)", refs: ["S53"]}
        required: true
        targets: ["premises-file"]
        expires: "P15Y default (license may set shorter)"
      - key: "content.license.alcohol-conditions"
        section: content
        label_he: "תנאי רישוי לממכר משקאות משכרים"
        label_en: "Alcohol licensing conditions"
        kind: document
        constraints: {required_if: "serves alcohol", refs: ["S57"]}
        required: false
        targets: ["premises-file"]
        expires: "with business license"
      - key: "content.signage.price-display"
        section: content
        label_he: "הצגת מחירים בעסק"
        label_en: "Price display at the premises"
        kind: document
        constraints: {note: "total price per item/service, ₪ only, in a visible place, clear legible numerals", refs: ["S54", "S55"]}
        required: true
        targets: ["signage"]
        expires: "on-change"
      - key: "content.signage.no-smoking"
        section: content
        label_he: "שלטי 'העישון אסור'"
        label_en: "No-smoking signs"
        kind: document
        constraints: {note: "≥20x30 cm; symbol ≥1/3 of the sign; mounted 1.80-2.20 m; 1 per 10 m of wall or at least 1 per room/area (except a smoking room)", refs: ["S56"]}
        required: true
        targets: ["signage"]
        expires: "none (keep in good order)"
      - key: "content.signage.alcohol-minors"
        section: content
        label_he: "שלט איסור מכירת משקאות משכרים לקטינים"
        label_en: "No-alcohol-to-minors notice"
        kind: document
        constraints: {required_if: "serves alcohol", note: "wording/size per police uniform licensing spec item 4.8 - exact values unknown", refs: ["S57"]}
        required: false
        targets: ["signage"]
        expires: "none"
      - key: "content.signage.storefront"
        section: content
        label_he: "שלט חזית"
        label_en: "Storefront sign"
        kind: document
        constraints: {note: "municipal signage permit + annual fee; Hebrew must cover at least half the sign when another language appears (TLV s.18); rules differ per city", refs: ["S58"]}
        required: true
        targets: ["signage"]
        expires: "yearly (TLV permit lapses 31 Dec)"
      - key: "content.signage.a-frame"
        section: content
        label_he: "שלט מדרכה (A-frame)"
        label_en: "A-frame sidewalk sign"
        kind: document
        constraints: {note: "sidewalk placement approval unknown - check city bylaw", refs: ["S58"]}
        required: false
        targets: ["signage"]
        expires: "per municipal permit"
      - key: "content.signage.window"
        section: content
        label_he: "מדבקות חלון"
        label_en: "Window stickers"
        kind: document
        constraints: {note: "hours, accepted meal cards (10bis / Cibus), kashrut, accessibility, QR"}
        required: false
        targets: ["signage"]
        expires: "on-change"
      - key: "content.signage.hours"
        section: content
        label_he: "שלט שעות פתיחה"
        label_en: "Opening-hours sign"
        kind: document
        constraints: {note: "rendered from identity.hours.regular; no legal spec found"}
        required: false
        targets: ["signage"]
        expires: "on-change"
      - key: "content.table.qr-card"
        section: content
        label_he: "כרטיס QR לתפריט"
        label_en: "Table QR menu card"
        kind: document
        constraints: {note: "links to the web menu; size is a design choice"}
        required: false
        targets: ["print"]
        expires: "on-change"
      - key: "content.table.tent"
        section: content
        label_he: "סטנד שולחני"
        label_en: "Table tent"
        kind: document
        constraints: {note: "specials, events, review QR"}
        required: false
        targets: ["print"]
        expires: "on-change"
      - key: "content.delivery.wolt"
        section: content
        label_he: "תוכן לוולט"
        label_en: "Wolt listing content"
        kind: list
        constraints: {note: "menu + item photos (16:9 landscape, ≥1000x563 (2nd), ≤5 per item, no people/text/AI/multiple items); venue cover/logo spec unknown", refs: ["S63", "S64"]}
        required: false
        targets: ["wolt"]
        expires: "on-change"
      - key: "content.delivery.tenbis"
        section: content
        label_he: "תוכן לתן ביס"
        label_en: "10bis listing content"
        kind: list
        constraints: {note: "listing fields / image specs unknown (join via restaurant form)", refs: ["S65"]}
        required: false
        targets: ["tenbis"]
        expires: "on-change"
      - key: "content.delivery.cibus-mishloha"
        section: content
        label_he: "תוכן לסיבוס ומשלוחה"
        label_en: "Cibus / Mishloha listing content"
        kind: list
        constraints: {note: "specs unknown", refs: ["S66"]}
        required: false
        targets: ["cibus", "mishloha"]
        expires: "on-change"
      - key: "content.delivery.own"
        section: content
        label_he: "משלוחים עצמאיים"
        label_en: "Own delivery (zones, fees, minimum order)"
        kind: list
        constraints: {note: "fees shown as part of total prices", refs: ["S55"]}
        required: false
        targets: ["website", "whatsapp"]
        expires: "on-change"
      - key: "content.reservations.policy"
        section: content
        label_he: "מדיניות הזמנת מקומות"
        label_en: "Reservation policy"
        kind: text
        constraints: {required_if: "takes reservations", note: "deposit, cancellation, table time, max party size", refs: ["S67", "S68"]}
        required: false
        targets: ["tabit", "ontopo", "website"]
        expires: "on-change"
      - key: "content.events.list"
        section: content
        label_he: "אירועים"
        label_en: "Events"
        kind: list
        constraints: {note: "GBP event post needs title + start/end dates and times", refs: ["S04"]}
        required: false
        targets: ["gbp", "facebook", "instagram", "website"]
        expires: "per event"
      - key: "content.specials.daily"
        section: content
        label_he: "מנות היום"
        label_en: "Daily specials"
        kind: price-list
        constraints: {}
        required: false
        targets: ["instagram", "whatsapp", "facebook", "website"]
        expires: "daily"
      - key: "content.catering.menu"
        section: content
        label_he: "תפריט אירועים / קייטרינג"
        label_en: "Events / catering menu"
        kind: price-list
        constraints: {}
        required: false
        targets: ["website", "whatsapp"]
        expires: "on-change"
      - key: "content.docs.bill-footer"
        section: content
        label_he: "נוסח תחתית חשבון (שירות / טיפ)"
        label_en: "Bill footer (service / tip wording)"
        kind: text
        constraints: {note: "mandatory service or other charges must be inside the displayed total price (s.17ד); only voluntary tip wording", refs: ["S55", "S77"]}
        required: false
        targets: ["invoice"]
        expires: "on-change"
      - key: "content.reviews.platforms"
        section: content
        label_he: "קישורי ביקורות"
        label_en: "Review-site links"
        kind: list
        constraints: {note: "Google, Tripadvisor, Rest, Easy, Wolt", refs: ["S69", "S70"]}
        required: false
        targets: ["website", "print", "whatsapp"]
        expires: "on-change"
      - key: "media.food.hero-dish"
        section: media
        label_he: "מנת הדגל"
        label_en: "Hero dish photo"
        kind: image
        constraints: {note: "landscape 16:9 master ≥1000x563 for Wolt (2nd) + square/4:5 crops; GBP JPG/PNG 10 KB-5 MB", refs: ["S01", "S63", "S64"]}
        required: true
        targets: ["gbp", "wolt", "tenbis", "instagram", "website", "tripadvisor"]
        expires: "quarterly refresh (recommended)"
      - key: "media.food.menu-items"
        section: media
        label_he: "צילום לכל מנה"
        label_en: "Photo per menu item"
        kind: image
        constraints: {required_if: "listed on a delivery platform", note: "up to 5 per item on Wolt; landscape 16:9; whole dish centred; single item; no people, text, borders or AI images", refs: ["S05", "S63"]}
        required: false
        targets: ["wolt", "tenbis", "mishloha", "gbp", "website"]
        expires: "on-change"
      - key: "media.food.ambience"
        section: media
        label_he: "אווירה ועיצוב פנים"
        label_en: "Ambience / interior"
        kind: image
        constraints: {note: "Tripadvisor: landscape 1:1-4:3 and ≤10 MB reported (2nd, unverified)", refs: ["S01", "S69"]}
        required: true
        targets: ["gbp", "tripadvisor", "rest", "tabit", "ontopo", "website"]
        expires: "yearly refresh (recommended)"
      - key: "media.food.chef"
        section: media
        label_he: "השף / צוות המטבח"
        label_en: "Chef / kitchen team"
        kind: image
        constraints: {note: "keep people out of item photos (Wolt rule)", refs: ["S63"]}
        required: false
        targets: ["website", "instagram", "rest"]
        expires: "on-change"
      - key: "media.food.drinks"
        section: media
        label_he: "משקאות וקוקטיילים"
        label_en: "Drinks & cocktails"
        kind: image
        constraints: {refs: ["S01"]}
        required: false
        targets: ["instagram", "website", "gbp"]
        expires: "on-change"
      - key: "media.food.menu-photos"
        section: media
        label_he: "צילום התפריט המודפס"
        label_en: "Photos of the printed menu"
        kind: image
        constraints: {note: "GBP menu photos", refs: ["S06"]}
        required: true
        targets: ["gbp"]
        expires: "on-change"
      - key: "media.video.kitchen"
        section: media
        label_he: "סרטון מטבח / מנה"
        label_en: "Kitchen / dish reel"
        kind: video
        constraints: {note: "1080x1920 9:16 (2nd); GBP copy ≤30 s, ≤75 MB, ≥720p", refs: ["S01", "S75"]}
        required: false
        targets: ["instagram", "tiktok", "gbp"]
        expires: "on-change"
      - key: "media.image.qr-menu"
        section: media
        label_he: "QR לתפריט"
        label_en: "Menu QR code"
        kind: image
        constraints: {formats: ["SVG"]}
        required: false
        targets: ["print", "signage"]
        expires: "on-change"
      - key: "media.image.delivery-cover"
        section: media
        label_he: "תמונת נושא לפלטפורמות משלוחים"
        label_en: "Delivery-platform cover image"
        kind: image
        constraints: {note: "spec unknown per platform"}
        required: false
        targets: ["wolt", "tenbis", "mishloha"]
        expires: "on-change"
    calendar:
      - id: "daily-specials"
        name_he: "מנות היום"
        trigger: "daily (open days), before lunch service"
        channels: ["instagram", "whatsapp", "facebook"]
        assets:
          - {kind: "image", spec: "1080x1920 (9:16) [S75]", count: 1}
          - {kind: "text", spec: "dish name + price (total ₪) [S55]", count: 1}
      - id: "weekly-business-lunch"
        name_he: "עסקית השבוע"
        trigger: "weekly: Sunday morning (for Sun-Thu lunch)"
        channels: ["instagram", "facebook", "gbp", "whatsapp"]
        assets:
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
          - {kind: "rich-text", spec: "GBP post text ≤1,500 chars (2nd) [S08]", count: 1}
      - id: "weekly-weekend"
        name_he: "סוף שבוע / בראנץ׳ שישי"
        trigger: "weekly: Thursday"
        channels: ["instagram", "facebook", "whatsapp"]
        assets:
          - {kind: "image", spec: "1080x1920 (9:16) [S75]", count: 1}
          - {kind: "hours", spec: "Friday / Saturday hours", count: 1}
      - id: "events"
        name_he: "אירוע במסעדה"
        trigger: "per event: −14d and −1d"
        channels: ["gbp", "facebook", "instagram", "website"]
        assets:
          - {kind: "rich-text", spec: "GBP event post: title + start/end dates and times [S04]", count: 1}
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
          - {kind: "image", spec: "1080x1920 (9:16) [S75]", count: 2}
      - id: "rosh-hashana-menu"
        name_he: "תפריט ראש השנה והזמנות לחג"
        trigger: "hebrew 1 Tishrei; announce −21d; order cutoff −3d"
        channels: ["instagram", "facebook", "whatsapp", "email", "website"]
        assets:
          - {kind: "price-list", spec: "holiday takeaway menu", count: 1}
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 2}
          - {kind: "rich-text", spec: "newsletter [S43]", count: 1}
      - id: "yom-kippur-closure"
        name_he: "סגירה ביום כיפור"
        trigger: "hebrew 10 Tishrei"
        channels: ["gbp", "whatsapp", "website"]
        assets:
          - {kind: "hours", spec: "GBP special hours (closed)", count: 1}
      - id: "sukkot-sukkah"
        name_he: "ישיבה בסוכה"
        trigger: "hebrew 15-21 Tishrei"
        channels: ["instagram", "facebook", "gbp"]
        assets:
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
      - id: "hanukkah-specials"
        name_he: "סופגניות ולביבות"
        trigger: "hebrew 25 Kislev, 8 days"
        channels: ["instagram", "facebook", "wolt"]
        assets:
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
          - {kind: "image", spec: "1080x1920 (9:16) [S75]", count: 4}
      - id: "purim"
        name_he: "פורים (משלוחי מנות)"
        trigger: "hebrew 14 Adar (15 in Jerusalem)"
        channels: ["instagram", "whatsapp", "website"]
        assets:
          - {kind: "price-list", spec: "mishloach-manot boxes", count: 1}
      - id: "pesach"
        name_he: "פסח: תפריט כשר לפסח או סגירה"
        trigger: "hebrew 15 Nisan; decide −45d; announce −21d; switch menus −1d"
        channels: ["website", "gbp", "wolt", "tenbis", "instagram", "whatsapp", "signage"]
        assets:
          - {kind: "document", spec: "Pesach kashrut certificate scan [S51]", count: 1}
          - {kind: "price-list", spec: "content.menu.pesach", count: 1}
          - {kind: "hours", spec: "GBP special hours", count: 1}
          - {kind: "text", spec: "closure / 'כשר לפסח' notice (only with certificate) [S47]", count: 1}
      - id: "memorial-eves"
        name_he: "ערבי יום השואה ויום הזיכרון"
        trigger: "hebrew 27 Nisan eve; 4 Iyar eve (both may shift)"
        channels: ["gbp", "whatsapp", "website"]
        assets:
          - {kind: "hours", spec: "eve closure hours", count: 2}
          - {kind: "text", spec: "closure notice, no promotion", count: 2}
      - id: "yom-haatzmaut"
        name_he: "יום העצמאות"
        trigger: "hebrew 5 Iyar (may shift)"
        channels: ["instagram", "facebook", "gbp"]
        assets:
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
          - {kind: "hours", spec: "GBP special hours", count: 1}
      - id: "shavuot-dairy"
        name_he: "תפריט חלבי לשבועות"
        trigger: "hebrew 6 Sivan; announce −14d"
        channels: ["instagram", "facebook", "wolt", "website"]
        assets:
          - {kind: "price-list", spec: "dairy holiday menu", count: 1}
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
      - id: "tisha-bav"
        name_he: "תשעה באב - בדיקת חוק עזר עירוני"
        trigger: "hebrew 9 Av eve"
        channels: ["gbp", "whatsapp", "website"]
        assets:
          - {kind: "hours", spec: "eve hours / closure", count: 1}
      - id: "couples"
        name_he: "ט״ו באב / ולנטיין"
        trigger: "hebrew 15 Av; gregorian 14 Feb"
        channels: ["instagram", "facebook", "tabit", "ontopo"]
        assets:
          - {kind: "price-list", spec: "couples menu", count: 1}
          - {kind: "image", spec: "1080x1350 (4:5, inside Instagram's kept range 1.91:1-3:4) [S22]", count: 1}
      - id: "kosher-renewal"
        name_he: "חידוש תעודת כשרות"
        trigger: "content.kosher.certificate issue date + P1Y; remind −30d"
        channels: ["signage", "website", "wolt", "tenbis", "rest"]
        assets:
          - {kind: "document", spec: "renewed certificate scan; replace everywhere", count: 1}
      - id: "signage-renewal"
        name_he: "חידוש רישיון שילוט"
        trigger: "gregorian 1 Dec (permit lapses 31 Dec in Tel Aviv)"
        channels: ["signage"]
        assets:
          - {kind: "document", spec: "permit renewal + fee receipt", count: 1}
      - id: "license-check"
        name_he: "בדיקת תוקף רישיון עסק"
        trigger: "content.license.business expiry −180d"
        channels: ["premises-file"]
        assets:
          - {kind: "document", spec: "license renewal file", count: 1}
      - id: "menu-sync"
        name_he: "סנכרון תפריט לפלטפורמות"
        trigger: "on change of any content.menu.*"
        channels: ["gbp", "wolt", "tenbis", "mishloha", "tabit", "ontopo", "website", "print"]
        assets:
          - {kind: "price-list", spec: "updated menu", count: 1}
          - {kind: "image", spec: "item photos per Wolt spec [S63]", count: 1}
      - id: "review-replies"
        name_he: "מענה לביקורות"
        trigger: "weekly"
        channels: ["gbp", "tripadvisor", "rest", "easy", "wolt"]
        assets:
          - {kind: "text", spec: "replies from content.reviews.replies", count: 1}
      - id: "photo-refresh"
        name_he: "רענון צילומי מנות"
        trigger: "quarterly or on menu change"
        channels: ["gbp", "wolt", "instagram", "website"]
        assets:
          - {kind: "image", spec: "JPG/PNG 10 KB-5 MB, rec 720x720, min 250x250 [S01]", count: 5}
```
