"""«זהות» is the one place the business is defined (DGO-2048): /api/brand answers the WHOLE contract
(brand_fields.CORE) from the active versions, whatever blueprint an office applied; the slots it lacks are
created at start (definitions only); `missing` names what holds nothing; a contract slot's plan says the products
read it live; and the blueprint generator takes its brand map from the same table.

    python3 apps/digital-assets/tests/test_brand.py       (in the app's image: it needs requests + PyYAML)
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
os.environ["APP_STATE_DIR"] = tempfile.mkdtemp(prefix="da-brand-")
sys.path.insert(0, str(HERE))
import brand_fields  # noqa: E402
import propagate  # noqa: E402
import store  # noqa: E402

FAIL: list = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


def put(key, text):
    a = store.add_asset(key, "text", text=text, source="test")
    store.set_active(key, a["id"], by="test")


store.init()

# 1. an office with no blueprint: every contract slot is created once, empty, and every field is missing
made = propagate.ensure_identity()
check(sorted(made) == sorted(f["slots"][0] for f in brand_fields.CORE), f"ensure created {len(made)} slots")
check(propagate.ensure_identity() == [], "a second start creates nothing")
b = propagate.brand()
check(b["brand"] == {}, f"no value → empty brand: {b['brand']}")
check(set(b["missing"]) == set(brand_fields.FIELDS), "every field missing")
sig = store.get_slot("identity.legal.signatory")
check(sig and sig["section"] == "identity" and sig["grp"] == "legal", "the signatory slot is identity/legal")
check(not store.active_of("identity.legal.signatory"), "a created slot holds no value")

# 2. values: the business as its books show it
put("identity.name.brand-he", "בינה סולושנס")
put("identity.legal.business-number", "300000015")
put("identity.legal.entity-type", "עוסק פטור")
put("identity.contact.email", "   ")                      # blank is not a value
put("identity.color.primary", "#002e5f")
b = propagate.brand()
check(b["brand"].get("name") == "בינה סולושנס", "name")
check(b["brand"].get("business_number") == "300000015", "business_number")
check(b["brand"].get("entity_type") == "עוסק פטור", "entity_type")
check(b["brand"].get("color") == "#002e5f", "color")
check("email" not in b["brand"] and "email" in b["missing"], "a blank email is missing, not empty")
check("name" not in b["missing"], "a set field is not missing")

# 3. fallback: the square logo falls back to the primary one
fsha = "ab" * 32
logo = store.add_asset("identity.logo.primary", "image", file={"sha": fsha, "ext": "png", "mime": "image/png"})
store.set_active("identity.logo.primary", logo["id"])
b = propagate.brand("http://x")
check(b["brand"].get("logo", {}).get("url") == f"http://x/files/{fsha}.png", f"logo url {b['brand'].get('logo')}")
check(b["brand"].get("logo_square") == b["brand"].get("logo"), "logo_square falls back to the primary logo")

# 4. a blueprint's extra brand target (the product) still reads; a contract field is never overridden by one
store.upsert_slot({"key": "identity.product.name", "section": "identity", "kind": "text",
                   "targets": [{"channel": "brand", "brand": "product"}]})
store.upsert_slot({"key": "identity.odd", "section": "identity", "kind": "text",
                   "targets": [{"channel": "brand", "brand": "name"}]})
put("identity.product.name", "הלשכה הדיגיטלית")
put("identity.odd", "לא זה")
b = propagate.brand()
check(b["brand"].get("product") == "הלשכה הדיגיטלית", "the product field from a blueprint target")
check(b["brand"].get("name") == "בינה סולושנס", "a stray target never overrides the contract's name")

# 5. the plan of a contract slot says the products read it live — once, even when a target also says so
p = propagate.plan("identity.legal.business-number")
live = [i for i in p["items"] if i["channel"] == "brand"]
check(len(live) == 1 and live[0]["action"] == "live" and live[0]["field"] == "business_number", f"plan {live}")
store.patch_slot("identity.legal.business-number", {"targets": [{"channel": "brand", "brand": "business_number"}]})
live = [i for i in propagate.plan("identity.legal.business-number")["items"] if i["channel"] == "brand"]
check(len(live) == 1, f"one live line with a declared target too: {live}")

# 6. the generator's brand map IS the contract's
src = (HERE / "research" / "build_blueprints.py").read_text(encoding="utf-8")
check("BRAND = dict(brand_fields.BY_SLOT)" in src, "the generator takes its brand map from brand_fields")
check(brand_fields.BY_SLOT["identity.logo.primary"] == "logo" and brand_fields.BY_SLOT["identity.logo.square"] == "logo_square",
      "a slot feeds the FIRST field that names it")

if FAIL:
    print("FAIL", *FAIL, sep="\n  ")
    sys.exit(1)
print("ok — test_brand: the contract, the created slots, missing, fallback, extras, the plan, the generator")
