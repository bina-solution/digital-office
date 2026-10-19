#!/usr/bin/env python3
"""
seed_demo.py — put believable business data behind the UI before photographing it.

Empty apps make an empty mockup, and worse, they make the coverage number lie: most
render code is behind `if (rows.length)`, so an empty system can never exercise the
table/row/detail branches no matter how many screenshots you take. Seeding is therefore
the single biggest lever on BOTH numbers — view coverage (parameterised routes finally
have a real id to visit) and view-code coverage (the populated branches run).

Writes through apitools, which is the source of truth my-docs proxies to:
    /business    business identity  -> the "הגדרות עסק" view
    /customers   customers          -> "לקוחות" + document targets
    /items       catalogue items    -> "פריטים"
    /documents   issued documents   -> "מסמכים" + the dashboard KPIs

Idempotent: skips a record when one with the same natural key already exists, so it is
safe to re-run before every capture.

Run:  python3 scripts/ui-coverage/seed_demo.py [--base http://apitools:8080]
"""
from __future__ import annotations
# Hebrew output: python defaults stdout to the ANSI codepage on Windows (cp1255) and dies
# with UnicodeEncodeError. Linux/macOS are already UTF-8 — a no-op there.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"): _sys.stdout.reconfigure(encoding="utf-8")

import argparse
import json
import sys
import urllib.error
import urllib.request

BUSINESS = {
    "name": "בינה פתרונות בע\"מ",
    "company_id": "514789234",
    "address": "הרכס 35, מודיעין",
    "email": "person116@example.com",
    "phone": "08-9740123",
}

CUSTOMERS = [
    {"name": "מ.ש. הכהנים בע\"מ", "company_id": "511020471", "city": "מודיעין",
     "email": "person119@example.com", "phone": "08-9741234"},
    {"name": "סבח סוכנויות בע\"מ", "company_id": "570043745", "city": "משמר השבעה",
     "email": "person120@example.com", "phone": "03-9021188"},
    {"name": "פוליראן תעשיות", "company_id": "513498345", "city": "אשדוד",
     "email": "person121@example.com", "phone": "08-8563377"},
    {"name": "אגן שיווק", "company_id": "511301129", "city": "פתח תקווה",
     "email": "person117@example.com", "phone": "03-9312244"},
    {"name": "ישראל קרטון", "company_id": "512093170", "city": "חיפה",
     "email": "person118@example.com", "phone": "04-8112255"},
]

ITEMS = [
    {"name": "שירותי ייעוץ טכנולוגי", "price": 450, "unit": "שעה"},
    {"name": "רישוי תוכנה שנתי", "price": 12000, "unit": "שנה"},
    {"name": "הטמעת מערכת", "price": 8500, "unit": "יחידה"},
    {"name": "תחזוקה חודשית", "price": 1800, "unit": "חודש"},
    {"name": "הדרכת משתמשים", "price": 2400, "unit": "יום"},
]

DOCS = [
    {"type": "INVOICE", "customer": 0, "date": "12/06/2026", "lines": [(0, 12), (3, 1)]},
    {"type": "INVOICE", "customer": 1, "date": "03/06/2026", "lines": [(1, 1)]},
    {"type": "ORDER",   "customer": 2, "date": "28/05/2026", "lines": [(2, 1)]},
    {"type": "QUOTE",   "customer": 3, "date": "21/05/2026", "lines": [(4, 3), (0, 6)]},
    {"type": "INVOICE", "customer": 4, "date": "14/05/2026", "lines": [(3, 12)]},
]


def _party(src: dict) -> dict:
    """Party accepts a narrow field set; pass only what it declares."""
    return {k: v for k, v in
            {"name": src.get("name"), "company_id": src.get("company_id")}.items() if v}


def call(base: str, path: str, method: str = "GET", body=None):
    req = urllib.request.Request(
        base.rstrip("/") + path, method=method,
        data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
        headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]
    except Exception as e:
        return 0, str(e)[:200]


def seed(base: str) -> int:
    made = {"business": 0, "customers": 0, "items": 0, "documents": 0}

    st, _ = call(base, "/business", "PUT", BUSINESS)
    if st in (200, 201, 204):
        made["business"] = 1
    else:
        st2, _ = call(base, "/business", "POST", BUSINESS)
        made["business"] = 1 if st2 in (200, 201) else 0

    st, existing = call(base, "/customers")
    have = {c.get("company_id") for c in existing} if isinstance(existing, list) else set()
    cust_ids = []
    for c in CUSTOMERS:
        if c["company_id"] in have:
            st, cur = call(base, "/customers")
            match = next((x for x in cur if x.get("company_id") == c["company_id"]), None)
            if match:
                cust_ids.append(match.get("id"))
            continue
        st, resp = call(base, "/customers", "POST", c)
        if st in (200, 201):
            made["customers"] += 1
            cust_ids.append(resp.get("id") if isinstance(resp, dict) else None)
        else:
            print(f"  customer {c['name']}: HTTP {st} {str(resp)[:90]}")

    st, existing = call(base, "/items")
    have = {i.get("name") for i in existing} if isinstance(existing, list) else set()
    item_ids = []
    for it in ITEMS:
        if it["name"] in have:
            st, cur = call(base, "/items")
            match = next((x for x in cur if x.get("name") == it["name"]), None)
            if match:
                item_ids.append(match.get("id"))
            continue
        st, resp = call(base, "/items", "POST", it)
        if st in (200, 201):
            made["items"] += 1
            item_ids.append(resp.get("id") if isinstance(resp, dict) else None)
        else:
            print(f"  item {it['name']}: HTTP {st} {str(resp)[:90]}")

    st, existing = call(base, "/documents")
    n_have = len(existing) if isinstance(existing, list) else 0
    if n_have < len(DOCS):
        for d in DOCS:
            cid = cust_ids[d["customer"]] if d["customer"] < len(cust_ids) else None
            # LineItem fields are (sku, description, qty, unit, unit_price, ...) — an
            # earlier guess at {item_id, quantity} was rejected by the dataclass.
            lines = [{"sku": f"IT-{i + 1:03d}", "description": ITEMS[i]["name"],
                      "qty": q, "unit": ITEMS[i]["unit"],
                      "unit_price": ITEMS[i]["price"]}
                     for i, q in d["lines"]]
            body = {"doc_type": d["type"], "doc_date": d["date"], "lines": lines,
                    "customer": _party(CUSTOMERS[d["customer"]]),
                    "supplier": _party(BUSINESS)}
            st, resp = call(base, "/documents", "POST", body)
            if st in (200, 201):
                made["documents"] += 1
            else:
                print(f"  doc {d['type']}: HTTP {st} {str(resp)[:120]}")

    print(f"seeded: business={made['business']} customers={made['customers']} "
          f"items={made['items']} documents={made['documents']}")
    for p in ("/customers", "/items", "/documents"):
        st, cur = call(base, p)
        print(f"  {p:<12} now holds {len(cur) if isinstance(cur, list) else '?'} record(s)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    a = ap.parse_args()
    raise SystemExit(seed(a.base))
