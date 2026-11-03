import os
import re
from typing import List

from src.ocr_core.ocr_data import OcrData
from src.ocr_core.ocr_drawings import OcrDrawings
from src.ocr_core.ocr_query import OcrQuery
from src.ocr_core.exceptions.ocr_query_exceptions import MatchNotFound, AlignmentNotFound
from src.ocr_core.models.relative_position import RelativePosition
from src.ocr_core.validations.validations import (
    validation_digit_count_equals, validation_ends_with, validation_equals, validation_has_letter,
    validation_has_number, validation_is_money, validation_is_number, validation_length_equals,
    validation_length_greater_than, validation_length_less_than, validation_matches_regex,
    validation_not_contains, validation_not_ends_with, validation_not_equals,
    validation_not_starts_with, validation_numeric_greater_than, validation_starts_with)
from src.utils.storage import ocr_test_files_path, pdf_test_files_path
from src.utils.logging_config import get_logger

logger = get_logger('apitools.ocr_json_query')

# ── full_text fallback ────────────────────────────────────────────────────────
# Local Tesseract emits word boxes in an order/grouping that often breaks the
# annotation-based phrase matching used by find_texts_matching_annotations /
# find_value_by_relative_position — multi-word labels ("תאריך חשבונית",
# "תעודת משלוח מספר") and the values after them fail to assemble even though the
# text is plainly present in full_text. Google Vision (production) groups reading
# order correctly, so this only bites local OCR. These helpers recover the value
# directly from full_text and run ONLY when the annotation path returns nothing,
# so production behaviour is unchanged. Toggle with APITOOLS_FULLTEXT_FALLBACK=0.
_FT_FALLBACK = os.getenv('APITOOLS_FULLTEXT_FALLBACK', '1') == '1'
_STRIP = ' :|-‎‏​ '


def _norm_ws(s):
    return re.sub(r'\s+', '', s or '')


_BIDI_RX = re.compile('[‎‏​؜‪-‮⁦-⁩]')


def _value_passes(value, validations):
    """Mirror of json_query's validation switch, for full_text fallback candidates.
    Bidi/format marks are stripped first — OCR tokens carry RLM/LRM inside them
    ("PO25013414‏"), which silently fails every fullmatch/length validation."""
    if isinstance(value, str):
        value = _BIDI_RX.sub('', value)
    for v in validations or []:
        t = v.get("validation_type"); vv = v.get("validation_value")
        if t == "equals" and not validation_equals(value, vv): return False
        elif t == "length_equals" and not validation_length_equals(value, vv): return False
        elif t == "length_greater_than" and not validation_length_greater_than(value, vv): return False
        elif t == "length_less_than" and not validation_length_less_than(value, vv): return False
        elif t == "has_letter" and not validation_has_letter(value): return False
        elif t == "has_number" and not validation_has_number(value): return False
        elif t == "not_equals" and not validation_not_equals(value, vv): return False
        elif t == "starts_with" and not validation_starts_with(value, vv): return False
        elif t == "ends_with" and not validation_ends_with(value, vv): return False
        elif t == "not_ends_with" and not validation_not_ends_with(value, vv): return False
        elif t == "is_number" and not validation_is_number(value): return False
        elif t == "numeric_greater_than" and not validation_numeric_greater_than(value, vv): return False
        elif t == "digit_count_equals" and not validation_digit_count_equals(value, vv): return False
        elif t == "not_starts_with" and not validation_not_starts_with(value, vv): return False
        elif t == "not_contains" and not validation_not_contains(value, vv): return False
        elif t == "is_money" and not validation_is_money(value): return False
        elif t == "matches_regex" and not validation_matches_regex(value, vv): return False
    return True


def _word_list(ocr_data):
    """Return (words, page_w, page_h) where each word is a small dict with its text and
    center/size in the annotation coordinate space. Powers the word-level actions
    (find regex / find near) that the spatial harness helpers used to do client-side.

    Capped via APITOOLS_ANNOTATION_MAX_SCAN (same env var / convention as the anchor-scan
    cap in ocr_query.py — a correctness bound, not a resource-profile value: "find near"
    is O(anchors * words), so an uncapped word list on a large scan/photo is quadratic in
    token count regardless of how much CPU the host has)."""
    anns = ocr_data.text_annotations
    if not anns:
        return [], 1.0, 1.0
    page = anns[0].bounding_box
    pw = float(getattr(page, 'width', 0) or 1.0)
    ph = float(getattr(page, 'height', 0) or 1.0)
    max_scan = int(os.getenv("APITOOLS_ANNOTATION_MAX_SCAN", "8000"))
    scan_anns = anns[1:]
    if max_scan > 0 and len(scan_anns) > max_scan:
        logger.warning(f"Reached max_scan limit ({max_scan}) building word list for find near/regex. Truncating.")
        scan_anns = scan_anns[:max_scan]
    words = []
    for a in scan_anns:
        bb = a.bounding_box
        c = bb.center
        words.append({'t': (a.description or '').strip(), 'cx': float(c.x), 'cy': float(c.y),
                      'w': float(getattr(bb, 'width', 0) or 0), 'h': float(getattr(bb, 'height', 0) or 0),
                      'ann': a})
    return words, pw, ph


def _nows(s):
    return re.sub(r'\s+', '', s or '')


def _nopunct(s):
    """Normalize a name for matching: keep only letters/digits (Hebrew + Latin), dropping
    whitespace and punctuation so 'א.י.ש. הכל' and 'איש הכל' normalize the same."""
    return re.sub(r'[^0-9A-Za-z֐-׿]', '', s or '')


def _anchor_points(words, anchors, exact=False):
    """Resolve anchor strings to anchor tokens for `find near`. A single-word anchor
    matches any token that contains it. A multi-word anchor (e.g. 'יתרת חוב') matches a
    run of tokens on the same line that contain each word in order — the OCR splits a
    header phrase into separate tokens, so the phrase would never match a single token.
    Phrase matches collapse to one synthetic anchor at the group's centroid.

    exact=True requires each anchor word to be a WHOLE token, not a substring — so 'עד'
    matches a standalone 'עד' (kartset 'עד תאריך …') but not 'עד31/12/29' (aging range)."""
    def hit(key, t):
        return key == _nows(t) if exact else (key in _nows(t) or key in t)
    pts = []
    for a in anchors:
        parts = str(a).split()
        if len(parts) <= 1:
            key = _nows(a)
            for wd in words:
                if key and hit(key, wd['t']):
                    pts.append(wd)
            continue
        keys = [_nows(p) for p in parts]
        for wd in words:
            if not hit(keys[0], wd['t']):
                continue
            grp, ok = [wd], True
            for k in keys[1:]:
                tol = (wd['h'] or 8) * 0.7
                nxt = None
                for wd2 in words:
                    if wd2 in grp or abs(wd2['cy'] - wd['cy']) > tol or not hit(k, wd2['t']):
                        continue
                    if nxt is None or abs(wd2['cx'] - grp[-1]['cx']) < abs(nxt['cx'] - grp[-1]['cx']):
                        nxt = wd2
                if nxt is None:
                    ok = False
                    break
                grp.append(nxt)
            if ok:
                pts.append({'t': str(a), 'ann': wd['ann'], 'h': wd['h'],
                            'cx': sum(g['cx'] for g in grp) / len(grp),
                            'cy': sum(g['cy'] for g in grp) / len(grp),
                            'w': sum(g['w'] for g in grp)})
    return pts


def _fulltext_find_after(full_text, labels, validations, window=60, from_end=False):
    """Find any label in full_text, return the first following token passing all
    validations. ``from_end`` mirrors the annotation path's ``anchor_order:"bottom"``:
    scan label OCCURRENCES last-to-first, so a grand-total label wins over the
    identically-named table-column header earlier in the text."""
    if not full_text:
        return None
    for lab in labels:
        lab = str(lab or '').strip()
        if not lab:
            continue
        pat = r'\s*'.join(re.escape(w) for w in lab.split())
        occurrences = list(re.finditer(pat, full_text))
        if from_end:
            occurrences.reverse()
        for m in occurrences:
            tail = full_text[m.end(): m.end() + window]
            for tok in re.split(r'[\s|]+', tail):
                tok = tok.strip(_STRIP)
                if tok and _value_passes(tok, validations):
                    return tok
    return None


def _excl_ft(fulltxt, markers):
    """exclude_near marker positions inside the whitespace-stripped full text.

    The name lane computes its exclusion positions over `norm` (punctuation-stripped,
    space-joined); the id lane matches over `fulltxt` (whitespace-stripped), a different
    coordinate space — so it needs its own."""
    return [m.start() for mk in (markers or [])
            for m in re.finditer(re.escape(_nows(str(mk))), fulltxt)]


def _fulltext_find_options(full_text, options, region=1.0):
    """Return options present in full_text as whitespace-normalized substrings.

    region (0..1] limits matches to the first fraction of the document — used for TYPE
    classification, whose keywords are document HEADERS at the top: this catches a header
    keyword the annotation matcher missed without false-matching a keyword that merely
    appears in the body (e.g. "מספר תעודה" lower in an invoice)."""
    if not full_text:
        return []
    ftn = _norm_ws(full_text)
    limit = len(ftn) if region >= 1.0 else int(len(ftn) * region)
    out = []
    for o in options:
        on = _norm_ws(str(o or ''))
        if not on:
            continue
        i = ftn.find(on)
        if i >= 0 and i <= limit:
            out.append(o)
    return out


class OcrJsonQuery:

    def __init__(self, ocr_query: OcrQuery):
        self.ocr_query = ocr_query

    def json_query(self, query: dict, match_index=0, _depth=0):
        """Run a query and, if it yields nothing, its ordered `fallbacks` — so a single
        call returns the value after trying the whole pipeline. Each fallback is itself a
        full query (may carry its own fallbacks). The first validated value wins; the
        response's process_context records which step matched."""
        res = self._run_single(query, match_index)
        if res.get("result") is not None:
            return res
        if _depth < 12:
            for i, fb in enumerate(query.get("fallbacks") or []):
                fbres = self.json_query(fb, _depth=_depth + 1)
                if fbres.get("result") is not None:
                    pc = fbres.setdefault("process_context", {})
                    pc["matched_step"] = i + 1
                    if fb.get("label"):
                        pc["matched_label"] = fb["label"]
                    return fbres
        # nothing matched. Word-count-aware type fallback (settings-driven): a document with
        # no type keyword isn't a known business-doc type — return `no_match_option`
        # ("unknown") rather than silently defaulting to invoice. If the page also carries
        # almost no readable words it's an unclassifiable scan (logo / blank / scrap), so
        # return `garbage_option` when the letter-word count is below `garbage_below_words`.
        nm = query.get("no_match_option")
        if nm is not None:
            pick = nm
            pc = {"default": True, "no_match": True}
            gb = query.get("garbage_option")
            below = query.get("garbage_below_words")
            if gb is not None and below is not None:
                anns = self.ocr_query.ocr_data.text_annotations or []
                wc = sum(1 for a in anns[1:]
                         if sum(c.isalpha() for c in (a.description or "")) >= 2)
                pc["word_count"] = wc
                if wc < int(below):
                    pick = gb
            return {"process_context": pc, "result": pick}
        # honor a static default on the primary query (backward compatible)
        if query.get("default") is not None:
            return {"process_context": {"default": True}, "result": query["default"]}
        return res

    def _run_single(self, query: dict, match_index=0):
        action = query.get("action")
        action_value = query.get("action_value")
        action_value_type = type(action_value)

        value_validations: List[dict] = query.get("value_validations", [])
        is_rtl = query.get("is_rtl", False)

        process_context = {}
        error = False
        error_type = ""
        error_message = ""
        action_output = None
        fulltext_validated = False  # set when a full_text-fallback value already passed validations

        # Optional vertical band restricting where this query may match, e.g.
        # {"region": {"y_min": 0.0, "y_max": 0.20}} for a supplier id in the letterhead, or
        # {"y_min": 0.45} for a grand total. Documents are strongly positional and a bare
        # keyword cannot separate a supplier from a customer, or a total from a column header.
        self.ocr_query.region = query.get("region")
        # {"anchor_order": "bottom"} anchors on the LOWEST label occurrence (grand total)
        self.ocr_query.anchor_order = query.get("anchor_order")
        # {"value_order": "bottom"} picks the LOWEST aligned value (cumulative-column totals)
        self.ocr_query.value_order = query.get("value_order")

        # {"value_regex": "..."} constrains the returned value to a shape (date, money) —
        # sugar for a matches_regex validation; a find-after that hits a wrong-shaped value
        # then walks to the next anchor match automatically.
        if query.get("value_regex"):
            value_validations = list(value_validations) + [
                {"validation_type": "matches_regex", "validation_value": query["value_regex"]}]

        # Which occurrence of the label to anchor on. Negative indexes from the end, so
        # {"match_index": -1} takes the LAST match — needed for a grand total, whose label
        # ("סה\"כ", "יתרה לתשלום") also heads a table column further up the page.
        # Only honoured on the first call; the validation-failure retry keeps walking forward.
        if match_index == 0 and query.get("match_index") is not None:
            match_index = int(query["match_index"])

        if action in ["find after", "find before", "find above", "find below"]:
            relative_position_text = action.split(" ")[1]
            relative_position = RelativePosition[relative_position_text.upper()]
            values_to_align = action_value if action_value_type == list else [action_value]

            try:
                find_results = self.ocr_query.find_value_by_relative_position(
                    texts=values_to_align,
                    relative_position=relative_position,
                    match_index=match_index
                )
                if find_results:
                    action_output = find_results.aligned_value
                    process_context["text_match"] = find_results.text_match_annotation.description
                    process_context["find_results"] = find_results.dict()

                else:
                    action_output = None
            except MatchNotFound as e:
                error = True
                error_type = "NoMatchFound"
                error_message = str(e)
            except AlignmentNotFound as e:
                error = True
                error_type = "AlignmentNotFound"
                error_message = str(e)

            # full_text fallback: annotation matching missed but the value is in the text.
            # Per-query opt-OUT ("fulltext_fallback": false): on photos the full-text
            # reading order is not spatial, so a positional query (grand total) should
            # fail here and let its SPATIAL fallback step fire instead of grabbing the
            # first token after an identically-named column header.
            if _FT_FALLBACK and query.get("fulltext_fallback", True) is not False \
                    and (error or not action_output):
                fb = _fulltext_find_after(
                    self.ocr_query.ocr_data.full_text, values_to_align, value_validations,
                    from_end=(query.get("anchor_order") == "bottom"))
                if fb is not None:
                    action_output = fb
                    error = False; error_type = ""; error_message = ""
                    process_context["fulltext_fallback"] = True
                    process_context["text_match"] = fb
                    fulltext_validated = True
                    if self.ocr_query.draw:
                        # a full_text match has no annotation of its own; box the word token
                        # that carries it so the overlay marks the real value, not the failed
                        # annotation attempts that ran before it.
                        _words, _pw, _ph = _word_list(self.ocr_query.ocr_data)
                        _key = _nows(fb)
                        for _wd in _words:
                            if _key and _key in _nows(_wd['t']):
                                self.ocr_query.ocr_drawer.draw_annotations([_wd['ann']], color="blue")
                                break

        elif action == "find option":
            # match_mode name_substring/id REPLACES action_output wholesale further down
            # (`action_output = None` then rebuilt from a normalized substring scan), so the
            # fuzzy annotation pass here is pure waste for those modes — every result it
            # computes is discarded a few lines later. It is also the single most expensive
            # thing in this call graph: n_annotations x n_options fuzzy comparisons, the
            # measured cause of the /documentJsonQuery 504 class (see ocr_query.py's
            # APITOOLS_FIND_OPTION_MAX_TEXTS note). Skipping it for those modes is what makes
            # a FULL-registry option list affordable: measured over 144 cached documents,
            # mean 1204ms -> 191ms per query with identical results.
            _mm_pre = query.get("match_mode")
            if _mm_pre in ("name_substring", "id"):
                action_output = None
            else:
                action_output = self.ocr_query.find_matching_texts(
                    action_value, as_dict=True, draw=self.ocr_query.draw)
            # full_text fallback for find option is OPT-IN per query ("fulltext_fallback": true):
            # substring matching is precise for specific targets (company tax-ids/names) but too
            # loose for ambiguous type keywords (e.g. an invoice body contains "מספר תעודה"), so it
            # must NOT be on by default for type classification.
            if _FT_FALLBACK and query.get("fulltext_fallback", False):
                # fulltext_options lets the caller supply a curated STRONG-only list for the
                # substring fallback (e.g. unambiguous TYPE headers) while annotation matching
                # still uses the full action_value — avoids generic keywords over-matching.
                fb_opts = query.get("fulltext_options")
                opts = fb_opts if fb_opts else (action_value if action_value_type == list else [action_value])
                region = float(query.get("fulltext_region", 1.0))
                present = _fulltext_find_options(self.ocr_query.ocr_data.full_text, opts, region)
                if present:
                    if not isinstance(action_output, dict):
                        action_output = {}
                    matched = {m.get("option") for m in action_output.get("matches", [])}
                    extra = [{"option": o, "match_annotations": []} for o in present if o not in matched]
                    if extra:
                        action_output.setdefault("matches", []).extend(extra)
                        action_output.pop("error", None)
                        process_context["fulltext_fallback"] = True
                        if self.ocr_query.draw:
                            # box the word token carrying each full-text-matched option so
                            # the overlay shows it (there's no annotation match to draw).
                            words_ft, _pw, _ph = _word_list(self.ocr_query.ocr_data)
                            for e in extra:
                                key = _nows(str(e["option"]))
                                for wd in words_ft:
                                    if key and key in _nows(wd['t']):
                                        self.ocr_query.ocr_drawer.draw_annotations([wd['ann']], color="blue")
                                        break

            # name_substring / id match_mode: resolve options by normalized substring over
            # the ISSUER region — REPLACES the fuzzy annotation match (which mis-matches a
            # recipient's name fragment). `region.exclude_below` cuts the recipient block;
            # `exclude_near` drops a name hit adjacent to a recipient marker (e.g. הכהנים).
            mm = query.get("match_mode")
            if mm in ("name_substring", "id"):
                action_output = None
                words, pw, ph = _word_list(self.ocr_query.ocr_data)
                reg = query.get("region") or {}
                cut_txt = reg.get("exclude_below"); y_max = float(reg.get("y_max", 1.0))
                head = []
                for wd in words:
                    if ph and wd['cy'] > y_max * ph:
                        continue
                    if cut_txt and cut_txt in wd['t']:
                        break
                    head.append(wd)
                # name matching is punctuation-insensitive: drop dots/quotes so an acronym
                # letterhead ('א.י.ש. הכל ירוק') matches its registry name ('איש הכול ירוק').
                norm = _nopunct(' '.join(wd['t'] for wd in head))
                fulltxt = _nows(' '.join(wd['t'] for wd in words))
                excl_pos = [m.start() for mk in (query.get("exclude_near") or [])
                            for m in re.finditer(re.escape(_nopunct(mk)), norm)]
                opts = action_value if action_value_type == list else [action_value]
                hits = []
                id_hits = []
                excl_ft = _excl_ft(fulltxt, query.get("exclude_near")) if mm == "id" else []
                for o in opts:
                    if mm == "id":
                        on = _nows(str(o))
                        if not on:
                            continue
                        at = fulltxt.find(on)
                        if at >= 0:
                            # POSITION, not length, orders id hits. Every company tax-id is the
                            # same width, so the old `max(hits)` on (len, option) degenerated to
                            # "the lexicographically largest id string" — arbitrary, and wrong
                            # the moment a document carries two registry ids (measured: 11/144
                            # cached documents do, the recipient's own id being the usual second
                            # one). The ISSUER's id is in the letterhead, so first-in-reading-
                            # order is the right pick; exclude_near still vetoes a hit sitting
                            # next to a recipient marker. Measured over 97 ground-truth rows,
                            # position-ordering moved id-mode from 78.4%/86.4% to
                            # 81.4%/89.8% recall/precision.
                            if not any(abs(at - ep) < 40 for ep in excl_ft):
                                id_hits.append((at, o))
                        continue
                    on = _nopunct(str(o))
                    if len(on) < 5:
                        continue
                    idx = norm.find(on)
                    if idx >= 0:
                        if not any(abs(idx - ep) < 40 for ep in excl_pos):
                            hits.append((len(on), o))
                        continue
                    # ktiv-insensitive: drop ו/י from both sides (הכול vs הכל, מטבעון vs
                    # מטבען). exclude_near must apply here too, in the ktiv-reduced space:
                    # else a name adjacent to the recipient/home marker (e.g. 'מ.ש הכהנים
                    # חומרי בנין') leaks through this path.
                    on2 = re.sub('[וי]', '', on)
                    norm2 = re.sub('[וי]', '', norm)
                    idx2 = norm2.find(on2) if len(on2) >= 5 else -1
                    if idx2 >= 0:
                        excl2 = [m.start() for mk in (query.get("exclude_near") or [])
                                 for m in re.finditer(re.escape(re.sub('[וי]', '', _nopunct(mk))), norm2)]
                        if not any(abs(idx2 - ep) < 40 for ep in excl2):
                            hits.append((len(on2), o))
                if id_hits:
                    hits = [(0, min(id_hits)[1])]
                if hits:
                    pick_name = max(hits)[1]
                    # option_map lets a name-match return the corresponding id (company id).
                    pick = (query.get("option_map") or {}).get(pick_name, pick_name)
                    action_output = {"matches": [{"option": pick, "match_annotations": []}]}
                    process_context["match_mode"] = mm
                    if self.ocr_query.draw and mm == "name_substring":
                        # box the letterhead tokens the name matched (there is no single
                        # annotation for a normalized-substring match) so the company
                        # resolution is visible on the overlay like every other field.
                        want = re.sub('[וי]', '', _nopunct(str(pick_name)))
                        for wd in head:
                            t2 = re.sub('[וי]', '', _nopunct(wd['t']))
                            if len(t2) >= 2 and t2 in want:
                                self.ocr_query.ocr_drawer.draw_annotations([wd['ann']], color="blue")

        elif action == "find regex":
            # value by regular expression over word tokens (region + order), else full_text.
            pattern = action_value[0] if action_value_type == list and action_value else action_value
            words, pw, ph = _word_list(self.ocr_query.ocr_data)
            reg = query.get("region") or {}
            y0 = float(reg.get("y_min", 0.0)) * ph
            y1 = float(reg.get("y_max", 1.0)) * ph
            order = query.get("order")   # "top" | "bottom" | None (top-most default)
            cands = []
            try:
                rx = re.compile(str(pattern))
            except re.error:
                rx = None
            if rx:
                for wd in words:
                    if ph and not (y0 <= wd['cy'] <= y1):
                        continue
                    m = rx.search(wd['t'])
                    if m and _value_passes(m.group(0), value_validations):
                        cands.append((wd['cy'], m.group(0), wd))
            if cands:
                cands.sort(key=lambda c: -c[0] if order == "bottom" else c[0])
                cy, val, wd = cands[0]
                action_output = val
                process_context["regex_match"] = val
                fulltext_validated = True
                if self.ocr_query.draw:
                    self.ocr_query.ocr_drawer.draw_annotations([wd['ann']], color="blue")
            elif rx and not reg:
                # full_text fallback ONLY when no region was given — a region means "match
                # only here", so an empty region must return no result (letting a fallback
                # fire) rather than grabbing the first matching token anywhere on the page.
                for m in re.finditer(str(pattern), self.ocr_query.ocr_data.full_text or ''):
                    if _value_passes(m.group(0), value_validations):
                        action_output = m.group(0)
                        process_context["regex_fulltext"] = True
                        fulltext_validated = True
                        break

        elif action == "find near":
            # a value spatially related to an anchor: scope row|column|below|block, and
            # select nearest|top|bottom. Absorbs linked-row, column-bottom, nearest-date.
            anchors = action_value if action_value_type == list else [action_value]
            scope = query.get("scope", "block")
            select = query.get("select", "nearest")
            words, pw, ph = _word_list(self.ocr_query.ocr_data)
            anchor_ws = _anchor_points(words, anchors, exact=bool(query.get("anchor_exact")))
            best = None
            best_clean = None      # garbage-wrapped-id fallback: used ONLY if no native match
            for aw in anchor_ws:
                for wd in words:
                    if wd is aw:
                        continue
                    t = wd['t']
                    # barcode-strip guard: a barcode decode (or a mis-OCR of the bar
                    # pattern) carries the WHOLE barcode rect as its box — thousands of
                    # px wide, overlapping every column band, so it hijacks column/row
                    # scopes with junk digits. A printed glyph is ~0.6x as wide as it is
                    # tall, so a token's plausible width/height tops out near 1.3x its
                    # length; anything wider is bar art, not text.
                    if wd['h'] > 0 and wd['w'] / wd['h'] > max(4.0, 1.3 * len(t)):
                        continue
                    tc = t; is_clean = False
                    if not _value_passes(t, value_validations):
                        # garbage-wrapped id: heb+eng OCR mangles a Latin id's prefix and
                        # wraps it in punctuation / a stray Hebrew letter ("PO26001466" ->
                        # "0(26001466)ם"), which fails a fullmatch value_regex. When the
                        # query DOES expect an id shape (has a matches_regex), retry with
                        # non-alphanumerics stripped. Recorded as a SEPARATE candidate used
                        # only if no clean native token matched (else a cleaned garbage
                        # token could beat the real value on proximity).
                        _has_rx = any(v.get('validation_type') == 'matches_regex'
                                      for v in (value_validations or []))
                        # Only rescue a token with the clear WRAPPED-id signature: a long
                        # digit run enclosed in brackets/parens ("0(26001466)ם" for
                        # PO26001466). This is the heb+eng-OCR wrapping artefact; requiring
                        # the bracket avoids cleaning arbitrary junk into a plausible id
                        # that would block a later fallback.
                        _wrapped = bool(re.search(r'[\[\](){}<>].*\d', t) and re.search(r'\d.*[\[\](){}<>]', t))
                        _clean = re.sub(r'[^A-Za-z0-9]', '', t) if _has_rx and _wrapped else t
                        if not (_has_rx and _wrapped) or _clean == t or not _clean \
                                or sum(c.isdigit() for c in _clean) < 6 \
                                or not _value_passes(_clean, value_validations):
                            continue
                        tc = _clean; is_clean = True
                    dy = wd['cy'] - aw['cy']; dx = wd['cx'] - aw['cx']
                    ah = aw['h'] or 8
                    if scope == "row" and abs(dy) > max(ah, wd['h']) * 0.8:
                        continue
                    if scope == "row" and query.get("row_side"):
                        # 'after' = the reading-direction side of the anchor (RTL: to its
                        # LEFT). A "label: value" row reads label→value; a number on the
                        # other side belongs to the PREVIOUS label ("לתעודה 220329591 |
                        # הזמנת לקוח: <empty>" must not yield 220329591 for הזמנת).
                        is_after = (dx < 0) if query.get("is_rtl") else (dx > 0)
                        if query["row_side"] == "after" and not is_after:
                            continue
                        if query["row_side"] == "before" and is_after:
                            continue
                    if scope == "column" and (wd['cy'] <= aw['cy'] + 2 or abs(dx) > max(1.5 * aw['w'], 42)):
                        continue
                    if scope == "below" and dy <= 0:
                        continue
                    if scope == "block" and not (-ah <= dy <= ah * 6 and abs(dx) < ah * 12):
                        continue
                    score = (-wd['cy'] if select == "bottom" else
                             wd['cy'] if select == "top" else abs(dy) + abs(dx) * 0.3)
                    if is_clean:
                        if best_clean is None or score < best_clean[0]:
                            best_clean = (score, tc, wd, aw)
                    elif best is None or score < best[0]:
                        best = (score, tc, wd, aw)
            if best is None and best_clean is not None:
                best = best_clean       # garbage-wrapped id only when nothing native matched
            if best:
                action_output = best[1]
                process_context["near_match"] = best[1]
                fulltext_validated = True
                if self.ocr_query.draw:
                    self.ocr_query.ocr_drawer.draw_annotations([best[3]['ann']], color="green")
                    self.ocr_query.ocr_drawer.draw_annotations([best[2]['ann']], color="blue")
        else:
            error = True
            error_type = "InvalidAction"
            error_message = "Invalid action"

        # Strip zero-width / bidi control marks that Hebrew OCR wraps around a latin value
        # ("$1266M001099‏") — they make a value_regex fullmatch fail and would otherwise
        # push a clean annotation match onto the undrawn full_text path.
        if isinstance(action_output, str):
            action_output = re.sub('[​-‏‪-‮⁦-⁩]', '', action_output).strip()

        # Validate action output. A find-option result is a dict; an EMPTY matches list is
        # "no result" so the orchestrator's fallbacks fire (was treated as a value because a
        # non-empty dict is truthy).
        empty_option = isinstance(action_output, dict) and not action_output.get("matches")
        if not error and (not action_output or empty_option):
            error = True
            error_type = "ActionOutputNone"
            error_message = "Action output is None"

        if not error and not fulltext_validated:
            for validation in value_validations:
                validation_type = validation.get("validation_type")
                validation_value = validation.get("validation_value")
                if validation_type == "equals":
                    if not validation_equals(action_output, validation_value):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} != {validation_value}"

                elif validation_type == "length_equals":
                    if not validation_length_equals(action_output, validation_value):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} length != {validation_value}"

                elif validation_type == "length_greater_than":
                    if not validation_length_greater_than(action_output, validation_value):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} length <= {validation_value}"

                elif validation_type == "length_less_than":
                    if not validation_length_less_than(action_output, validation_value):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} length >= {validation_value}"

                elif validation_type == "has_letter":
                    if not validation_has_letter(action_output):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} has no letters"

                elif validation_type == "has_number":
                    if not validation_has_number(action_output):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} has no numbers"

                elif validation_type == "not_equals":
                    if not validation_not_equals(action_output, validation_value):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} == {validation_value}"

                elif validation_type == "not_starts_with":
                    if not validation_not_starts_with(action_output, validation_value):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} starts with {validation_value}"

                elif validation_type == "not_contains":
                    if not validation_not_contains(action_output, validation_value):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} contains {validation_value}"

                elif validation_type == "digit_count_equals":
                    if not validation_digit_count_equals(action_output, validation_value):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} digit-count != {validation_value}"

                elif validation_type == "numeric_greater_than":
                    if not validation_numeric_greater_than(action_output, validation_value):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} <= {validation_value}"

                elif validation_type == "starts_with":
                    if not validation_starts_with(action_output, validation_value):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} does not start with {validation_value}"

                elif validation_type == "ends_with":
                    if not validation_ends_with(action_output, validation_value):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} does not end with {validation_value}"

                elif validation_type == "not_ends_with":
                    if not validation_not_ends_with(action_output, validation_value):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} ends with {validation_value}"

                elif validation_type == "is_number":
                    if not validation_is_number(action_output):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} is not a number"

                elif validation_type == "is_money":
                    if not validation_is_money(action_output):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} is not money-shaped"

                elif validation_type == "matches_regex":
                    if not validation_matches_regex(action_output, validation_value):
                        error = True
                        error_type = "ValidationFailed"
                        error_message = f"Validation failed: {action_output} !~ {validation_value}"

                elif validation_type is None:
                    error = True
                    error_type = "InvalidValidation"
                    error_message = "Validation type is missing"

                else:
                    error = True
                    error_type = "InvalidValidation"
                    error_message = "Invalid validation"

        # Recursive call to find next match if validation failed (stays within THIS query;
        # fallbacks only fire at the json_query() orchestration level).
        if error and error_type == "ValidationFailed":
            logger.debug(f"Validation failed: {error_message}, trying next match")
            return self._run_single(query, match_index=match_index + 1)

        # {"returns": "<label>"} — classification sugar: when the action matched, return
        # this fixed label instead of the matched token (e.g. type = "shipment").
        if not error and query.get("returns") is not None:
            has_match = ((isinstance(action_output, dict) and action_output.get("matches"))
                         or (not isinstance(action_output, dict) and action_output))
            if has_match:
                action_output = query["returns"]
            else:
                error = True; error_type = "ActionOutputNone"
                error_message = "no classification match"

        json_response = {
            "process_context": process_context,
        }
        if error:
            json_response["error"] = {
                "type": error_type,
                "message": error_message,
                "full_text": self.ocr_query.ocr_data.full_text,
            }
        else:
            json_response["result"] = action_output

        return json_response

    def query(self, query: str):
        pass


files = [
    f"{ocr_test_files_path()}/file1.jpg",
    f"{ocr_test_files_path()}/file2.jpg",
    f"{ocr_test_files_path()}/file3.jpg",
    f"{ocr_test_files_path()}/file4.jpg",
    f"{ocr_test_files_path()}/file6.jpg",
    f"{ocr_test_files_path()}/file7.jpg",
    f"{ocr_test_files_path()}/file8.jpg",
]

presets = [
    "חשבונית מס מס':",
    "תעודת משלוח מספר",
    "חשבונית מס",
]


def ocr_json_query_factory(path: str, draw=False):
    ocr_data = OcrData.from_file_path(path)
    ocr_drawings = OcrDrawings(ocr_data)
    ocr_query = OcrQuery(ocr_data, ocr_drawings, draw=draw)
    return OcrJsonQuery(ocr_query)


def ocr_query_example():
    filename = f"{pdf_test_files_path()}/test8.pdf"
    ocr_json_query = ocr_json_query_factory(filename)

    query = {
        "action": "find after",
        "action_value": ["חשבונית מס מספר"],
        "is_rtl": True,
        "value_validations":
            [
                {
                    "validation_type": "has_number"
                },
                {
                    "validation_type": "length_greater_than",
                    "validation_value": 3
                },
                {
                    "validation_type": "length_less_than",
                    "validation_value": 20
                }
            ]
    }

    result = ocr_json_query.json_query(query)
    print(result)


def ocr_all_example():
    files_res = []
    for file in files:
        file_company = None
        file_id = None
        for preset in presets:
            ocr_query = ocr_json_query_factory(file)
            query = {
                "action": "find after",
                "action_value": preset,
                "value_validations": [
                    {
                        "validation_type": "has_number"
                    }
                ],
                "is_rtl": True
            }
            result = ocr_query.json_query(query)
            if result.get("result") is not None:
                file_id = result.get("result")
                files_res.append({"file": file, "company": file_company, "id": file_id, "preset": preset})
                print("File:", file, "Company:", file_company, "ID:", file_id)
                break

    for file in files_res:
        print(file)
    # print(files_res)


if __name__ == "__main__":
    # ocr_query_example()
    ocr_all_example()
