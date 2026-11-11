#!/usr/bin/env python3
"""test_security_model — `ai/context/dgo-extend-plan.md` §9, read OUT OF the document (rel-3).

The release condition `rel-3` says: “every claim in §9 is a test”. A table of quoted sentences kept by
hand is a claim ABOUT the document, not a measurement of it: a sentence written into §9 tomorrow would
be held by nothing, and this file would still print a green table. So this file does not carry §9 — it
PARSES it, and then proves both directions against the document itself:

  (a) every claim the document makes has a test → a parsed claim with no mapped check FAILS, printed
      with the claim's own words;
  (b) every mapped key is a claim the document makes → a quote that §9 no longer contains FAILS,
      printed with the quote.

§9 turns out to be machine-readable — one markdown table (asset | where | backup) and two prose
paragraphs — so nothing here is hand-counted: one claim per table row, one per prose sentence, and the
count in the verdict line is the document's own. (Had the section been shaped so that sentences could
not be cut out of it, the fallback would have been a declared list plus a count of what it captured;
the parse is stronger, so it is what this file does.)

The checks themselves live where they already did — `test_link_security.py` (25 checks), plus the one
below for the sentence about the module §9 says was removed. Three sibling suites are RUN as they are
meant to be run, not re-implemented. A claim only a live office can prove is `SKIP live` with its
reason: silence is not a pass, and a skip says what would have to run.

Two entries used to sit in this map under a §9 label while their sentences are not in §9 at all — one
is the `serve:` contract (the app's own brief, riding on §6's transport), the other is the control
plane's write refusal. They are now in `ELSEWHERE`, tagged with where they really come from: the same
checks, and §9's coverage no longer counts them.

    python3 apps/dgo-extend/tests/test_security_model.py     # non-zero exit on any FAIL

The verdict line is printed LAST, deliberately: it is what a gate that ran this file reports.

Hermetic by construction. The only things read are the repo's own files, and `node`/`openssl` are
asked for before the one suite that needs them (`pair_contract.py`).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
ROOT = APP.parent.parent
PLAN = ROOT / "ai" / "context" / "dgo-extend-plan.md"
SECTION = 9

sys.path.insert(0, str(APP))
sys.path.insert(0, str(HERE))

import test_link_security as link_security  # noqa: E402  — the §9 claims themselves

# A sentence ends at `.`/`!`/`?` and whitespace and something that starts a claim. `0.0.0.0`,
# `trust.py` and `2026-09-30` therefore stay inside their sentence: the character after the dot is not
# whitespace, or the one after the space is not the start of a claim.
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z({\"“*])")
_HEADING = re.compile(r"^## (\d+)\.")
_BOLD_TITLE = re.compile(r"^\*\*.+\*\*\.?$")          # `**The link's identity, … (DGO-31).**`


# ── §9, as the document writes it ────────────────────────────────────────────────────────────────────
def section_body(text: str, number: int) -> str:
    """§<number> of the plan, from its heading to the next one."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        at = _HEADING.match(line)
        if at and int(at.group(1)) == number:
            start = i
            break
    if start is None:
        raise LookupError(f"`{PLAN}` has no `## {number}.` heading")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if _HEADING.match(lines[j]):
            end = j
            break
    return "\n".join(lines[start + 1:end])


def section9_claims(text: str | None = None) -> list[str]:
    """§9's claims as the DOCUMENT makes them: one per markdown table row, one per prose sentence."""
    if text is None:
        text = PLAN.read_text(encoding="utf-8")
    claims: list[str] = []
    prose: list[str] = []
    last_was_row = False

    def flush() -> None:
        block = " ".join(prose).strip()
        prose.clear()
        if not block:
            return
        for part in _SENTENCE.split(block):
            part = part.strip()
            if not part:
                continue
            # A bold lead-in introduces the sentence after it; it is not a claim of its own.
            if claims and _BOLD_TITLE.match(claims[-1]) and len(claims[-1]) < 160:
                claims[-1] = f"{claims[-1]} {part}"
            else:
                claims.append(part)

    for raw in section_body(text, SECTION).splitlines():
        line = raw.strip()
        if not line:
            flush()
            last_was_row = False
            continue
        if line.startswith("|"):
            flush()
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(c and set(c) <= set("-: ") for c in cells):     # the header's separator
                if last_was_row and claims:
                    claims.pop()                                   # a header row is not a claim
                last_was_row = False
                continue
            claims.append(" | ".join(cells))
            last_was_row = True
            continue
        prose.append(line)
        last_was_row = False
    flush()
    return claims


# The map: a VERBATIM quote out of §9 → the checks that hold that claim. Every quote is checked to be
# in §9 and in exactly one of its claims, and every claim is checked to be held by at least one quote.
SECTION9: list[tuple[str, tuple[str, ...]]] = [
    # the asset table, one row at a time
    ("`dgo-identity` volume, root-only",
     ("c_the_office_keys_are_root_only_and_backed_up", "c_identity_is_root_only_and_public")),
    ("WireGuard key | same | same",
     ("c_the_office_keys_are_root_only_and_backed_up",)),
    ("protocol `dgo_link`",
     ("c_the_link_token_lives_in_the_vault", "c_link_token_is_vault_made")),
    ("Pairing offer | remote's memory, 10 min | none",
     ("c_the_offer_lives_only_in_memory", "c_offer_is_public_short_and_single_use")),
    # “The link's identity, as implemented” — two offices authenticate their own users
    ("Two offices authenticate their own users",
     ("c_no_secret_crosses", "c_identity_crosses_boundedly")),
    # … the sending side overwrites the headers, the door removes them and writes the mapped user
    ("it listens on the pair's tunnel address for that peer alone",
     ("c_identity_crosses_boundedly", "c_mapped_user_is_a_header_value", "c_mapping_crosses_intact")),
    ("One link, one identity — and it is never the peer's word",
     ("c_door_with_no_tile_is_narrow", "c_identity_crosses_boundedly")),
    # … the pure function that came first, and the module §9 says was removed
    ("the module was removed on 2026-10-05",
     ("c_the_name_map_is_not_a_module",)),
    # “Threats → mitigations”
    ("adapter and link API never on `0.0.0.0`",
     ("c_the_link_is_not_on_every_address",)),
    ("Stolen token → useless without the peer's WireGuard key",
     ("c_a_token_alone_opens_nothing", "c_direction_and_silence")),
    ("Forged identity headers → dropped unless from the link proxy's address",
     ("c_identity_crosses_boundedly", "c_mapped_user_is_a_header_value")),
    ("Rogue office by QR → single-use, 10-min offer",
     ("c_offer_is_public_short_and_single_use", "c_confirmation_code_both_sides")),
    ("Lost keys → in the backup set",
     ("c_the_office_keys_are_root_only_and_backed_up",)),
    ("Wrong direction → enforced on the receiving side",
     ("c_direction_and_silence",)),
    ("Commit drift → placements refused",
     ("c_commit_drift_is_refused",)),
    ("Audit → offices run log + connections events + computers command log",
     ("c_the_actions_are_recorded",)),
    # “Not done”, and the one exception it names: the carriers' TCP door
    ("Not done: shared passwords, authentik federation, any public port besides WireGuard UDP",
     ("c_wireguard_udp_is_the_only_public_port", "c_the_link_door_is_three_paths")),
    ("That door answers nothing to a connection that cannot name the pair",
     ("c_carrier_answers_no_stranger", "c_carrier_needs_the_pair_key")),
    ("It is published on loopback by default",
     ("c_only_wireguard_is_published", "c_wireguard_udp_is_the_only_public_port")),
]

# Not §9. Kept, with the same checks, tagged with where the claim really comes from — so that the map
# above stays exactly `§9`, and a reader who asks “where is this promised?” is not sent to §9.
ELSEWHERE: list[tuple[str, str, tuple[str, ...]]] = [
    ("§6 apps-across-offices · the app's own `serve:` contract, not §9",
     "a paired office is served only what it declares, and `*` never reaches this app — promised by "
     "`apps/dgo-extend/AGENT.md` (“The door answers only for those apps”) on §6's transport",
     ("c_serves_only_what_it_declares", "c_star_never_reaches_this_app")),
    ("the control plane's own contract (app-management), not §9",
     "a call that arrives from a linked office is refused on every write — promised by "
     "app-management's own brief, not by the security model of the link",
     ("c_lifecycle_write_is_refused",)),
]


def c_the_name_map_is_not_a_module() -> list[str]:
    """§9: the identity rule “was first written as a pure function … and the module was removed”.

    Measured as the three things that make the sentence true today: the module is not in the tree,
    nothing imports or calls the function it held, and the door that replaced it is here — so a reader
    who looks for `decide()` finds the replacement instead of a ghost.
    """
    problems = []
    if (APP / "trust.py").exists():
        problems.append("`trust.py` is back in the tree, so §9's “the module was removed” is false")
    uses = (re.compile(r"^\s*(?:import\s+trust\b|from\s+trust\s+import)", re.M),
            re.compile(r"\btrust\.decide\b"))
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in path.parts or path == Path(__file__).resolve():
            continue                                       # this file names the needles, it does not use them
        text = path.read_text(encoding="utf-8", errors="replace")
        for at in uses:
            found = at.search(text)
            if found:
                problems.append(f"{path.relative_to(APP)} still uses `{found.group(0).strip()}`")
    if not ((APP / "link-proxy.py").exists() or (APP / "linkproxy.py").exists()):
        problems.append("the door §9 names (`link-proxy.py`) is gone, so nothing replaced the module")
    return problems


LOCAL_CLAIMS: list[tuple[str, str, object]] = [
    ("c_the_name_map_is_not_a_module",
     "§9 · the pure function's module is gone and the door that replaces the identity is here",
     c_the_name_map_is_not_a_module),
]

# The sibling suites that also hold a §9 sentence, run as they are meant to be run. Hermetic ones get
# their exit code; the one that needs a live office is reported as SKIP, never as a pass.
SIBLINGS: list[tuple[str, str, tuple[str, ...]]] = [
    ("pair_contract.py", "§9 · the pairing codes hold in both languages, one side's output read by "
     "the other (offer, reply, six digits)", ("node", "openssl")),
    ("test_serve_block.py", "§9 · an office that links to nobody is served nothing (direction)", ()),
    ("test_secret_pull.py", "§9 · a named secret goes only to the office its holder named, into that "
     "office's own vault", ()),
]

LIVE: list[tuple[str, str]] = [
    ("phase3.py c_door_identity / c_link_listener",
     "a LIVE office: the door's per-request identity rewrite and the listener's addresses are only "
     "provable against a running dgo-extend, its tunnel and its edge (needs docker and a paired "
     "office)"),
]


def _first_sentence(doc: str | None) -> str:
    if not doc:
        return ""
    text = " ".join(doc.split())
    for stop in (". ", ".\n"):
        at = text.find(stop)
        if at != -1:
            return text[:at + 1]
    return text


def _short(text: str, width: int) -> str:
    return text if len(text) <= width else text[:width - 1] + "…"


def _claim_names() -> set[str]:
    return {fn.__name__ for _n, _x, fn in list(link_security.CLAIMS) + LOCAL_CLAIMS}


def coverage_problems(claims: list[str] | None = None) -> list[str]:
    """Both directions, against §9 itself. The document is the only place the claims come from."""
    if claims is None:
        try:
            claims = section9_claims()
        except (LookupError, OSError) as e:
            return [f"§9 cannot be read as claims: {e}"]
    names = _claim_names()
    problems: list[str] = []

    for claim in claims:                                    # (a) a claim with no test
        if not any(q in claim for q, _c in SECTION9):
            problems.append(f"§9 claim with no test: “{_short(claim, 130)}”")

    for quote, checks in SECTION9:                           # (b) a key that §9 does not say
        inside = [c for c in claims if quote in c]
        if not inside:
            problems.append(f"the map quotes what §9 does not say: “{_short(quote, 130)}”")
        elif len(inside) > 1:
            problems.append(f"“{_short(quote, 60)}” sits in {len(inside)} of §9's claims, not one")
        ghost = [c for c in checks if c not in names]
        if ghost:
            problems.append(f"“{_short(quote, 60)}” names a check that does not exist: {ghost}")

    mapped = {c for _q, checks in SECTION9 for c in checks}
    mapped |= {c for _t, _w, checks in ELSEWHERE for c in checks}
    orphan = sorted(names - mapped)
    if orphan:
        problems.append(f"check(s) that no claim at all holds: {orphan}")
    if not SECTION9:
        problems.append("the §9 map is empty")
    return problems


def main() -> int:
    rows: list[tuple[str, str, str, str]] = []   # verdict, claim/sentence, what, evidence
    failed = 0

    try:
        claims = section9_claims()
    except (LookupError, OSError) as e:
        claims = []
        failed += 1
        rows.append(("FAIL", "§9", "the document could not be read", _short(str(e), 90)))

    # (a) the document's own claims — one row each, so a missing test is named by the claim's words
    for i, claim in enumerate(claims, 1):
        holders = [q for q, checks in SECTION9 if q in claim] if claims else []
        held = [c for q, checks in SECTION9 if q in claim for c in checks]
        if holders:
            rows.append(("PASS", f"§9/{i:02d}", _short(claim, 86),
                         f"held by {len(held)} check(s) via “{_short(holders[0], 40)}”"))
        else:
            failed += 1
            rows.append(("FAIL", f"§9/{i:02d}", _short(claim, 86),
                         "no check in this file holds this claim"))

    # (b) the map's keys — one row each, so a key that left the document is named by its quote
    for i, (quote, checks) in enumerate(SECTION9, 1):
        inside = [c for c in claims if quote in c]
        if inside:
            rows.append(("PASS", f"map/{i:02d}", _short(quote, 86),
                         f"quoted from §9 (claim {claims.index(inside[0]) + 1}); {len(checks)} check(s)"))
        else:
            failed += 1
            rows.append(("FAIL", f"map/{i:02d}", _short(quote, 86),
                         "this quote is not in §9 — the document changed under the map"))

    cover = coverage_problems(claims)
    # The per-claim and per-key rows above already carry the first two kinds of problem; what is left
    # (a key spanning two claims, a ghost check, an orphan, an empty map) is counted here, once.
    counted = ("§9 claim with no test", "the map quotes what §9 does not say")
    extra = [p for p in cover if not p.startswith(counted)]
    rows.append(("PASS" if not cover else "FAIL", "two-way coverage",
                 f"{len(claims)} claim(s) parsed out of §9 · {len(SECTION9)} quoted key(s) · "
                 f"{len(_claim_names())} check(s) in all",
                 "every claim has a test and every key is a claim" if not cover
                 else _short(cover[0], 90)))
    failed += len(extra)
    for p in extra:
        rows.append(("FAIL", "coverage", _short(p, 86), "…"))

    for name, xfail, fn in list(link_security.CLAIMS) + LOCAL_CLAIMS:
        try:
            problems = list(fn())
        except Exception as e:                              # noqa: BLE001 — a claim that cannot run
            problems = [f"the claim could not be checked: {type(e).__name__}: {e}"]
        what = _first_sentence(fn.__doc__) or name
        what = what.replace("§9: ", "").rstrip(".")
        if problems:
            failed += 1
            rows.append(("FAIL", name, _short(what, 86), _short(problems[0], 90)))
        else:
            rows.append(("PASS", name, _short(what, 86),
                         f"`{fn.__name__}()` measured it and returned no problem"))

    for script, why, needs in SIBLINGS:
        path = HERE / script
        if not path.exists():
            failed += 1
            rows.append(("FAIL", script, _short(why, 86), "the suite this row names is gone"))
            continue
        absent = [b for b in needs if not shutil.which(b)]
        if absent:
            rows.append(("SKIP", script, _short(why, 86),
                         f"not run: {', '.join(absent)} not on PATH here"))
            continue
        try:
            done = subprocess.run([sys.executable, str(path)], capture_output=True, text=True,
                                  timeout=900, cwd=str(APP))
        except subprocess.TimeoutExpired:
            failed += 1
            rows.append(("FAIL", script, _short(why, 86), "the suite did not finish within 900 s"))
            continue
        tail = [ln for ln in (done.stdout or "").splitlines() if ln.strip()]
        last = tail[-1] if tail else (done.stderr or "").strip().splitlines()[-1:] or ["no output"]
        last = last if isinstance(last, str) else last[0]
        if done.returncode == 0:
            rows.append(("PASS", script, _short(why, 86), _short(f"exit 0 · {last}", 90)))
        else:
            failed += 1
            rows.append(("FAIL", script, _short(why, 86), _short(f"exit {done.returncode} · {last}", 90)))

    for name, why in LIVE:
        rows.append(("SKIP", name, _short("live only", 86), _short(why, 90)))

    width = max(len(r[1]) for r in rows) + 2
    print(f"{'VERDICT':7} {'CHECK':{width}} WHAT WAS MEASURED")
    for verdict, claim, what, evidence in rows:
        print(f"{verdict:7} {claim:{width}} {what}")
        print(f"{'':7} {'':{width}} → {evidence}")

    passed = sum(1 for r in rows if r[0] == "PASS")
    skipped = sum(1 for r in rows if r[0] == "SKIP")
    # THE LAST LINE IS THE VERDICT: this is what a gate that ran this file prints as its report.
    print(f"security_model: §9 read from the document — {len(claims)} claim(s) parsed, "
          f"{len(SECTION9)} quoted key(s), {len(_claim_names())} check(s); "
          f"{passed} pass, {skipped} skip (live only), {failed} fail")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
