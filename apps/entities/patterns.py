"""patterns — what an entity is, and the roles («דפוסים») it can hold (DGO-2101, ai/context/business-domains.md).

An ENTITY is a person or an organization the business deals with — everyone but the business itself, which is
«זהות» (digital-assets, brand.v1). Its own fields are the ones every role needs (a name, how to reach it). A ROLE
is a pattern of fields one relationship needs: a customer's billing terms, a supplier's bank, a company's legal
record, a salesperson's commission, a contact's place in an organization. An entity holds several roles at once —
an organization can be our customer and our supplier.

This table is the one place the vocabulary is written: the store checks against it, `/api/patterns` serves it, the
screen and the CLI draw from it. A field is (key, Hebrew label, English label) and optionally a closed list of values.
"""
from __future__ import annotations

KINDS = {
    "organization": {"he": "ארגון", "en": "Organization"},
    "person": {"he": "אדם", "en": "Person"},
}

#: the fields of the entity itself, whatever its roles. The address is three fields, as a document prints it — one
#: text parsed back into street and city lost the city of a customer that had no street (the second reader)
ENTITY_FIELDS = [
    ("phone", "טלפון", "Phone"),
    ("mobile", "נייד", "Mobile"),
    ("email", "אימייל", "Email"),
    ("street", "רחוב ומספר", "Street"),
    ("city", "עיר", "City"),
    ("zip", "מיקוד", "Zip code"),
    ("website", "אתר", "Website"),
    ("notes", "הערות", "Notes"),
]

ENTITY_TYPES = ["עוסק פטור", "עוסק מורשה", "חברה בע״מ", "שותפות", "עמותה"]

#: role → its pattern. `kinds`: who may hold it. `fields`: (key, he, en[, choices]).
ROLES = {
    "company": {
        "he": "חברה", "en": "Company", "plural_he": "חברות",
        "kinds": ["organization", "person"],   # a sole trader (עוסק) is a person with a business record
        "about": "the legal record a document prints: the registered name, the number and its kind",
        "fields": [
            ("legal_name", "שם משפטי", "Legal name"),
            ("business_number", "ח״פ / מספר עוסק", "Business number"),
            ("entity_type", "סוג העוסק", "Entity type", ENTITY_TYPES),
            ("vat_file", "תיק מע״מ", "VAT file"),
        ],
    },
    "customer": {
        "he": "לקוח", "en": "Customer", "plural_he": "לקוחות",
        "kinds": ["organization", "person"],
        "about": "whoever we sell to: how we bill them",
        "fields": [
            ("customer_no", "מספר לקוח", "Customer number"),
            ("billing_email", "אימייל לחשבוניות", "Billing email"),
            ("payment_terms", "תנאי תשלום", "Payment terms"),
            ("price_list", "מחירון", "Price list"),
            ("credit_limit", "מסגרת אשראי", "Credit limit"),
            ("salesperson", "איש המכירות שלנו", "Our salesperson"),
        ],
    },
    "supplier": {
        "he": "ספק", "en": "Supplier", "plural_he": "ספקים",
        "kinds": ["organization", "person"],
        "about": "whoever we buy from: how we pay them",
        "fields": [
            ("supplier_no", "מספר ספק", "Supplier number"),
            ("bank_name", "בנק", "Bank"),
            ("bank_branch", "סניף", "Branch"),
            ("bank_account", "מספר חשבון", "Account number"),
            ("deduction_file", "תיק ניכויים", "Deduction file"),
            ("withholding_rate", "ניכוי במקור", "Withholding rate"),
            ("withholding_until", "אישור הניכוי בתוקף עד", "Withholding certificate valid until"),
            ("payment_terms", "תנאי תשלום", "Payment terms"),
        ],
    },
    "salesperson": {
        "he": "איש מכירות", "en": "Salesperson", "plural_he": "אנשי מכירות",
        "kinds": ["person"],
        "about": "a person who sells — ours or theirs",
        "fields": [
            ("commission", "עמלה", "Commission"),
            ("region", "אזור", "Region"),
        ],
    },
    "contact": {
        "he": "איש קשר", "en": "Contact person", "plural_he": "אנשי קשר",
        "kinds": ["person"],
        "about": "a person at an organization (the relation names which): who receives what",
        "fields": [
            ("title", "תפקיד", "Title"),
            ("receives", "מקבל/ת", "Receives"),
        ],
    },
}

#: relation kinds: from → to
RELATIONS = {
    "works_at": {"he": "עובד/ת ב", "en": "works at"},        # a person → an organization (title on the relation)
    "handles": {"he": "מטפל/ת ב", "en": "handles"},           # a salesperson → a customer
}


def field_keys(role: str) -> set[str]:
    return {f[0] for f in ROLES[role]["fields"]}


def entity_keys() -> set[str]:
    return {f[0] for f in ENTITY_FIELDS}


def as_json() -> dict:
    """The vocabulary as `/api/patterns` serves it (the screen and every reader draw from this)."""
    def fields(fs):
        return [{"key": f[0], "he": f[1], "en": f[2], **({"choices": f[3]} if len(f) > 3 else {})} for f in fs]
    return {"kinds": KINDS, "entity_fields": fields(ENTITY_FIELDS),
            "roles": {k: {"he": v["he"], "en": v["en"], "plural_he": v["plural_he"], "kinds": v["kinds"],
                          "about": v["about"], "fields": fields(v["fields"])} for k, v in ROLES.items()},
            "relations": RELATIONS}
