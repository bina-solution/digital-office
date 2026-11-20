"""brand_fields — the business's identity as ONE contract: every field the office's products read (`brand.v1`).

«זהות» (this app, id `digital-assets`) is the one place an office defines its business: the names, the legal
details, the contact details, the marks, the colours, who signs and the bank. No other app DEFINES them
(DGO-2048): the ledger's documents read them from `GET /api/brand` (apitools `entities.get_business`, keeping a
mirror only to draw documents while «זהות» is out of reach); esign's name and «המסמכים שלי»'s screen are to
follow (DGO-2047).

Each field is filled from the ACTIVE version of its slot; the first slot in its list that holds one wins (a
square logo falls back to the primary one). A field whose slots hold nothing is absent from `brand` and named
in `missing`, so a reader can tell "not set yet" from "empty on purpose".

`CORE` is also the set of slots this app guarantees on every office, whatever blueprint was applied: a slot
in it that the office lacks is created at start (a definition only — never a value).
"""
from __future__ import annotations

#: field → (slot keys, first that holds a value wins), kind, group, label {he, en}. The order is the order a
#: screen shows them in.
CORE: list[dict] = [
    # names
    {"field": "name", "slots": ["identity.name.brand-he"], "kind": "text", "group": "name",
     "label": {"he": "שם העסק", "en": "Business name"}, "required": True, "lang": "he"},
    {"field": "name_en", "slots": ["identity.name.brand-en"], "kind": "text", "group": "name",
     "label": {"he": "שם העסק באנגלית", "en": "Business name (English)"}, "lang": "en"},
    {"field": "legal_name", "slots": ["identity.name.legal"], "kind": "text", "group": "name",
     "label": {"he": "שם משפטי רשום", "en": "Registered legal name"}, "required": True},
    {"field": "short_name", "slots": ["identity.name.short"], "kind": "text", "group": "name",
     "label": {"he": "שם תצוגה מקוצר", "en": "Short display name"}},
    {"field": "slug", "slots": ["identity.slug"], "kind": "text", "group": "",
     "label": {"he": "מזהה (slug) וכינוי ברשתות", "en": "Slug / social handle"}},
    {"field": "domain", "slots": ["identity.domain"], "kind": "link", "group": "",
     "label": {"he": "דומיין", "en": "Web domain"}},
    # legal — what a document must carry
    {"field": "entity_type", "slots": ["identity.legal.entity-type"], "kind": "text", "group": "legal",
     "label": {"he": "סוג העוסק", "en": "Business entity type"}, "required": True,
     "constraints": {"enum": ["עוסק פטור", "עוסק מורשה", "חברה בע״מ", "שותפות", "עמותה"],
                     "note": "drives document types: an עוסק פטור issues «חשבון עסקה» and «קבלה», no VAT"}},
    {"field": "business_number", "slots": ["identity.legal.business-number"], "kind": "text", "group": "legal",
     "label": {"he": "מספר עוסק / ח״פ", "en": "Business ID (VAT dealer no. / company no.)"}, "required": True},
    {"field": "signatory", "slots": ["identity.legal.signatory"], "kind": "text", "group": "legal",
     "label": {"he": "החותם בשם העסק", "en": "Signs for the business"},
     "constraints": {"note": "the person whose name signs the business's documents and agreements"}},
    {"field": "signatory_title", "slots": ["identity.legal.signatory-title"], "kind": "text", "group": "legal",
     "label": {"he": "תפקיד החותם", "en": "Signatory's title"}},
    # contact
    {"field": "address", "slots": ["identity.contact.address"], "kind": "address", "group": "contact",
     "label": {"he": "כתובת העסק", "en": "Business address"}, "required": True},
    {"field": "phone", "slots": ["identity.contact.phone"], "kind": "text", "group": "contact",
     "label": {"he": "טלפון", "en": "Phone"}, "required": True},
    {"field": "whatsapp", "slots": ["identity.contact.whatsapp"], "kind": "text", "group": "contact",
     "label": {"he": "וואטסאפ", "en": "WhatsApp"}},
    {"field": "email", "slots": ["identity.contact.email"], "kind": "text", "group": "contact",
     "label": {"he": "אימייל", "en": "Email"}, "required": True},
    {"field": "website", "slots": ["identity.contact.website-url"], "kind": "link", "group": "contact",
     "label": {"he": "אתר", "en": "Website"}},
    # words
    {"field": "tagline", "slots": ["identity.tagline"], "kind": "text", "group": "",
     "label": {"he": "סלוגן", "en": "Tagline"}},
    {"field": "description", "slots": ["identity.description.short"], "kind": "text", "group": "description",
     "label": {"he": "תיאור קצר", "en": "Short description"}},
    {"field": "description_long", "slots": ["identity.description.long"], "kind": "richtext", "group": "description",
     "label": {"he": "תיאור מלא", "en": "Long description"}},
    # marks
    {"field": "logo", "slots": ["identity.logo.primary"], "kind": "image", "group": "logo",
     "label": {"he": "לוגו ראשי", "en": "Primary logo"}, "required": True},
    {"field": "logo_square", "slots": ["identity.logo.square", "identity.logo.primary"], "kind": "image",
     "group": "logo", "label": {"he": "לוגו ריבועי", "en": "Square logo"}},
    {"field": "logo_mono", "slots": ["identity.logo.monochrome"], "kind": "image", "group": "logo",
     "label": {"he": "לוגו בצבע אחד", "en": "Monochrome logo"}},
    {"field": "logo_reversed", "slots": ["identity.logo.reversed"], "kind": "image", "group": "logo",
     "label": {"he": "לוגו לרקע כהה", "en": "Logo for dark backgrounds"},
     "constraints": {"note": "the logo in light colours, for a dark cover, header or banner (a dark logo disappears there)"}},
    {"field": "favicon", "slots": ["identity.logo.favicon"], "kind": "image", "group": "logo",
     "label": {"he": "סמל לדפדפן (favicon)", "en": "Favicon"}},
    # colours
    {"field": "color", "slots": ["identity.color.primary"], "kind": "color", "group": "color",
     "label": {"he": "צבע ראשי", "en": "Primary colour"}},
    {"field": "color_secondary", "slots": ["identity.color.secondary"], "kind": "color", "group": "color",
     "label": {"he": "צבע משני", "en": "Secondary colour"}},
    {"field": "color_neutral", "slots": ["identity.color.neutral"], "kind": "color", "group": "color",
     "label": {"he": "צבע ניטרלי", "en": "Neutral colour"}},
    # bank — printed on a payment request
    {"field": "bank_name", "slots": ["identity.bank.name"], "kind": "text", "group": "bank",
     "label": {"he": "בנק", "en": "Bank"}},
    {"field": "bank_branch", "slots": ["identity.bank.branch"], "kind": "text", "group": "bank",
     "label": {"he": "סניף", "en": "Branch"}},
    {"field": "bank_account", "slots": ["identity.bank.account"], "kind": "text", "group": "bank",
     "label": {"he": "מספר חשבון", "en": "Account number"}},
]

#: slot key → field, for the slots that feed a field FIRST (the plan's «live» line names them)
BY_SLOT: dict[str, str] = {}
for _f in CORE:
    for _k in _f["slots"]:
        BY_SLOT.setdefault(_k, _f["field"])

FIELDS: tuple[str, ...] = tuple(f["field"] for f in CORE)


def slot_definition(f: dict) -> dict:
    """The slot this app creates when an office lacks one of the contract's: its definition, never a value."""
    return {"key": f["slots"][0], "section": "identity", "grp": f.get("group") or "", "kind": f["kind"],
            "label": dict(f["label"]), "lang": f.get("lang") or "", "required": bool(f.get("required")),
            "constraints": dict(f.get("constraints") or {}),
            "targets": [{"channel": "brand", "brand": f["field"]}]}
