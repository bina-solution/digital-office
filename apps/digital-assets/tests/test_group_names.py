"""Every group a slot can be declared in has a Hebrew title on the screen (DGO-2101). A group the screen does not
name shows its key: «bank» stood in English over «זהות»' bank details, because brand_fields.py (DGO-2048) declared
the group and static/app.js's GROUP_HE never learned it; «home», «footer» and fourteen more stood over «תוכן», the
pages of the website blueprints. Enumerated mechanically from what the SERVER stores as a slot's group — a
blueprint slot's `group:` (or `grp:`; blueprints.py `s.setdefault("grp", s.get("group") …)`) and a brand field's
"group" (brand_fields.slot_definition) — not from the slot's key, which says something else (`content.website.…`
holds the pages `home`, `footer` …): so the next one is caught here, not on the owner's screen.

    python3 apps/digital-assets/tests/test_group_names.py        (plain Python, no packages)
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FAIL: list = []


def check(cond, what):
    if not cond:
        FAIL.append(what)


js = (HERE / "static" / "app.js").read_text(encoding="utf-8")
body = js.split("const GROUP_HE = {", 1)[1].split("};", 1)[0]
body = re.sub(r"//[^\n]*", "", body)                      # the comments inside the map are not keys
keys = [a or b for a, b in re.findall(r"(?:'([a-z0-9-]+)'|\b([a-z0-9_]+)):\s*'", body)]
named = set(keys)
check(len(keys) == len(named), f"GROUP_HE names a group twice: {sorted(k for k in named if keys.count(k) > 1)}")
check(len(named) > 50, f"GROUP_HE was not read: {len(named)} keys")

declared: dict = {}
for f in sorted((HERE / "blueprints").glob("*.yaml")):
    for m in re.finditer(r"^\s*(?:-\s+)?(?:group|grp):\s*['\"]?([a-z0-9_-]+)", f.read_text(encoding="utf-8"), re.M):
        declared.setdefault(m.group(1), set()).add(f.name)
for m in re.finditer(r'"group": "([a-z0-9_-]+)"', (HERE / "brand_fields.py").read_text(encoding="utf-8")):
    declared.setdefault(m.group(1), set()).add("brand_fields.py")
check(len(declared) > 50, f"the declared groups were not read: {len(declared)}")
check({"bank", "home", "footer"} <= set(declared), f"the reading misses known groups: {sorted(declared)[:20]}")
for g, where in sorted(declared.items()):
    check(g in named, f"the group «{g}» ({', '.join(sorted(where))}) has no Hebrew title in static/app.js GROUP_HE")

if FAIL:
    print("FAIL", *FAIL, sep="\n  ")
    sys.exit(1)
print(f"ok — test_group_names: {len(declared)} declared groups, each titled; {len(named)} titles, none twice")
