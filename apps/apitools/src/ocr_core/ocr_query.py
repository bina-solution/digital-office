from dataclasses import dataclass
from copy import copy
import os
import time
from typing import Any, List

import src.utils.fuzzy_comparison as fuzzy_c
from src.ocr_core.models.alingment_position import AlignmentPosition
from src.ocr_core.models.annotation_object import AlignedAnnotations, AnnotationObject
from src.ocr_core.exceptions.ocr_query_exceptions import MatchNotFound, AlignmentNotFound
from src.ocr_core.models.relative_position import RelativePosition
from src.ocr_core.ocr_data import OcrData
from src.ocr_core.ocr_drawings import OcrDrawings
from src.utils.image_utils import draw_annotations
from src.utils import has_index
from src.utils.storage import ocr_test_files_path, pdf_test_files_path, ocr_test_fails_path
from src.utils.logging_config import get_logger

logger = get_logger('apitools.ocr_query')



@dataclass
class RelativePositionQueryResult:
    aligned_value: str
    aligned_annotation: AnnotationObject | dict
    text_match_annotation: AnnotationObject | dict
    match_index: int
            
    
    def dict(self) -> dict[str, Any]:
        return {
            "aligned_value": self.aligned_value,
            "aligned_annotation": self.aligned_annotation.annotation_dict,
            "text_match_annotation": self.text_match_annotation.annotation_dict,
            "match_index": self.match_index
        }

    

class OcrQuery:
    def __init__(self, ocr_data: OcrData, ocr_drawer: OcrDrawings, draw=False):
        self.ocr_data = ocr_data
        self.ocr_drawer = ocr_drawer
        self.draw = draw
        # memo for annotations_aligned_with_annotation — see its docstring comment
        self._aligned_memo: dict = {}
        # memo for find_texts_matching_annotations[_via_alignment] — see their docstrings.
        # MEASURED HOTSPOT (live profiling, 2026-08-06): a `documentJsonQuery` call retries
        # `_run_single` at incrementing match_index on ValidationFailed (up to
        # APITOOLS_MAX_MATCH_ATTEMPTS times) and walks a `fallbacks` chain (up to depth 12) —
        # BOTH re-enter find_value_by_relative_position, which re-ran the full anchor-text
        # fuzzy scan from scratch every single time even though `texts` and the document are
        # unchanged. Profiled live: single requests spending 60-90% of 3-12s in
        # fuzzy_startswith/WRatio inside this exact call, repeated with IDENTICAL arguments
        # across retries. Same anchor set + fuzzy flag + max_matches over an unchanged
        # document always yields the same match list -> safe to remember (pure function of
        # immutable per-request input, identical justification to _aligned_memo above).
        self._text_match_memo: dict = {}
        # Optional vertical band (fractions of page height) restricting where a query may
        # match. Real documents are strongly positional: a supplier's ח.פ lives in the
        # letterhead (top ~15%) while the customer's sits lower, and a grand total lives in
        # the bottom half while an identically-named column header sits above. Without this
        # a keyword query cannot tell them apart. Set via the query's "region" key.
        self.region = None
        # 'bottom' | 'top' | None — how to order anchor matches before match_index applies.
        self.anchor_order = None
        # 'bottom' | None — pick the LOWEST aligned VALUE instead of the nearest. Needed for
        # cumulative-column reports (aged receivables) where the total is the last row of a
        # column whose header is the only label: nearest-first returns the first row.
        self.value_order = None

    @property
    def text_annotations(self) -> List[AnnotationObject]:
        anns = self.ocr_data.text_annotations
        if not self.region:
            return anns
        try:
            ph = max(a.bounding_box.center_y for a in anns) or 1.0
        except Exception:
            return anns
        y0 = float(self.region.get('y_min', 0.0)) * ph
        y1 = float(self.region.get('y_max', 1.0)) * ph
        kept = [a for a in anns if y0 <= a.bounding_box.center_y <= y1]
        return kept or anns          # never strand the query with nothing to match

    @property
    def _region_key(self):
        """The region scope as a hashable memo-key part — None when unscoped. The match memos below
        read `self.text_annotations`, which `region` filters, so a cached result is valid only for the
        region it was computed under. `region` is mutable per-step request state on a shared OcrQuery
        (issue apitools-query-memo-ignores-region), so it must be in the key like fuzzy/max_matches."""
        r = self.region
        return None if not r else (r.get('y_min'), r.get('y_max'))

    def find_texts_matching_annotations(self, texts: List[str], fuzzy=False, max_matches=None) -> list[AnnotationObject]:
        """
        Looks for a annotation or multiple following annotations that there text or combined texts match one of the given texts
        supports fuzzy matching, for more info see fuzzy_c.py
        :param texts: list of texts to match
        :param fuzzy: if True, use fuzzy comparison
        :param max_matches: maximum number of matches to return (default: None, no limit)
        :return: list of matching annotations
        """
        # Per-document memo — see _text_match_memo docstring in __init__. draw=True bypasses
        # the memo like the alignment cache does: a draw run has no side effects here (this
        # function doesn't draw), but a memoized run returning stale objects mid-drawing-session
        # would be a needless behavior change for a debug path — keep it identical to the
        # established convention rather than special-casing it.
        memo_key = (tuple(texts), fuzzy, max_matches, self._region_key)
        if not self.draw:
            cached = self._text_match_memo.get(memo_key)
            if cached is not None:
                return cached

        # Correctness bound, not a resource-profile value (mirrors APITOOLS_ALIGNMENT_MAX_ANCHOR_SCAN):
        # a photo/scan can carry 10,000+ OCR tokens where a clean invoice carries ~150-2000 — this
        # anchor scan is O(len(texts) * len(annotations)) in fuzzy comparisons per attempt, so an
        # unbounded photo should be capped on every machine, not merely on small ones.
        max_scan = int(os.getenv("APITOOLS_ANNOTATION_MAX_SCAN", "8000"))

        matches: list[list[AnnotationObject]] = []
        parts: dict[str, list[AnnotationObject]] = {text: [] for text in texts}
        for _scan_index, text_annotation in enumerate(self.text_annotations):
            if max_scan > 0 and _scan_index >= max_scan:
                logger.warning(f"Reached max_scan limit ({max_scan}) for text matching. Stopping search.")
                break
            for text in texts:
                joined_text = "".join([part.description for part in parts[text]]) + text_annotation.description
                if fuzzy_c.string_startswith(text, joined_text, fuzzy):
                    parts[text].append(text_annotation)
                    if fuzzy_c.compare_strings(text, joined_text, fuzzy):
                        matches.append(parts[text])
                        # Early exit if max_matches reached
                        if max_matches and len(matches) >= max_matches:
                            logger.warning(f"Reached max_matches limit ({max_matches}) for text matching. Stopping search.")
                            break

                        # when fuzzy somtime it matches before the full text - so keep matching
                        if not fuzzy:
                            parts[text] = []

                elif len(parts[text]) > 0:
                    # Noisy OCR (esp. local Tesseract) emits junk tokens (e.g. "--.") right before
                    # the real word; fuzzy startswith over-accepts them and pollutes the accumulator,
                    # so the real word then fails (joined too long) and the match is lost. Reset AND
                    # retry the CURRENT annotation as a fresh start so the real match isn't dropped.
                    parts[text] = []
                    if fuzzy_c.string_startswith(text, text_annotation.description, fuzzy):
                        parts[text].append(text_annotation)
                        if fuzzy_c.compare_strings(text, text_annotation.description, fuzzy):
                            matches.append(parts[text])
                            if not fuzzy:
                                parts[text] = []

            # Check max_matches at text level
            if max_matches and len(matches) >= max_matches:
                break

        # combining each match annotations to single annotation
        matches = [AnnotationObject.combine_annotations(match) for match in matches]
        if not self.draw:
            self._text_match_memo[memo_key] = matches
        return matches

    def find_texts_matching_annotations_via_alignment(
        self,
        texts: List[str],
        fuzzy=False,
        max_matches=5,
        max_anchor_scan: int | None = None,
    ) -> list[AnnotationObject] | None:
        """
        Same as find_texts_matching_annotations but using alignment rather than following annotations to find a match thats devided to multiple annotations
        Looks for a annotation or multiple alinged annotations that there text or combined texts match one of the given texts
        supports fuzzy matching, for more info see fuzzy_c.py
        :param texts: list of texts to match
        :param fuzzy: if True, use fuzzy comparison
        :param max_matches: maximum number of matches to return (default: 5, prevents timeouts on complex documents)
        :return: list of matching annotations or None if no match found
        """
        # Per-document memo — same rationale and convention as find_texts_matching_annotations
        # above. This is the MORE expensive of the two (it also aligns candidates), so a retry
        # that reaches this fallback pays the full cost again on every attempt without it.
        memo_key = (tuple(texts), fuzzy, max_matches, max_anchor_scan, self._region_key)
        if not self.draw:
            cached = self._text_match_memo.get(('via_alignment', memo_key))
            if cached is not None:
                return cached

        matches: list[list[AnnotationObject]] = []
        parts: dict[str, list[AnnotationObject]] = {text: [] for text in texts}
        max_anchor_scan = max_anchor_scan or int(os.getenv("APITOOLS_ALIGNMENT_MAX_ANCHOR_SCAN", "1500"))
        # PROFILED LIVE (2026-08-06): `max_anchor_scan` bounds how far into the document's
        # token list we look for CANDIDATE anchors (position-based) — it does nothing to bound
        # how many of those candidates get promoted to the actually-expensive step, aligning
        # geometry against up to APITOOLS_ALIGNMENT_MAX_CANDIDATES others. A "find option" query
        # with many short/numeric options (company-id lists) fuzzy-matches a LOT of unrelated
        # numeric tokens on an invoice (line items, dates, amounts) — one live request aligned
        # 726 distinct anchors this way, 43k+ geometry calls, 178s, well past the 1500 scan cap
        # (the document itself was ~700 tokens). This caps the PROMOTION count instead: real
        # documents rarely have more than a handful of genuine candidates per option.
        max_anchor_attempts = int(os.getenv("APITOOLS_ALIGNMENT_MAX_ANCHOR_ATTEMPTS", "40"))
        aligned_cache: dict[int, list[AnnotationObject]] = {}
        for anchor_index, text_annotation in enumerate(self.text_annotations):
            if max_anchor_scan > 0 and anchor_index >= max_anchor_scan:
                logger.warning(f"Reached max_anchor_scan limit ({max_anchor_scan}) for alignment query. Stopping search.")
                break
            if max_anchor_attempts > 0 and len(aligned_cache) >= max_anchor_attempts:
                logger.warning(f"Reached max_anchor_attempts limit ({max_anchor_attempts}) for alignment query "
                                f"(texts={texts}); {anchor_index} of {len(self.text_annotations)} tokens scanned. Stopping search.")
                break
            for text in texts:
                if fuzzy_c.string_startswith(text, text_annotation.description, fuzzy):
                    parts[text].append(text_annotation)
                    anchor_id = id(text_annotation)
                    aligned_annotations = aligned_cache.get(anchor_id)
                    if aligned_annotations is None:
                        if max_anchor_attempts > 0 and len(aligned_cache) >= max_anchor_attempts:
                            continue  # already logged/handled at the outer-loop check next iteration
                        aligned_annotations = self.annotations_aligned_with_annotation(
                            text_annotation, relative_position=RelativePosition.AFTER, draw_overwrite=False)
                        aligned_cache[anchor_id] = aligned_annotations
                    for next_annotation in aligned_annotations:
                        parts[text].append(next_annotation)
                        joined_text = "".join([part.description for part in parts[text]])
                        if fuzzy_c.string_startswith(text, joined_text, fuzzy):
                            if fuzzy_c.compare_strings(text, joined_text, fuzzy):
                                matches.append(copy(parts[text]))
                                # Early exit if max_matches reached to prevent timeout
                                if len(matches) >= max_matches:
                                    logger.warning(f"Reached max_matches limit ({max_matches}) for alignment query. Stopping search.")
                                    break
                                if not fuzzy:
                                    break
                        else:
                            break
                    parts[text] = []
                    # Check max_matches at outer loop level too
                    if len(matches) >= max_matches:
                        break
            # Check max_matches at text level
            if len(matches) >= max_matches:
                break

        # combining each match annotations to single annotation
        matches: list[AnnotationObject] = [AnnotationObject.combine_annotations(match) for match in matches]
        result = matches if matches else None
        if not self.draw:
            self._text_match_memo[('via_alignment', memo_key)] = result
        return result


    def annotations_aligned_with_annotation(
        self, annotation: AnnotationObject,
        relative_position: RelativePosition = None, draw_overwrite=None,
        max_candidates: int | None = None) -> List[AnnotationObject]:

        # PER-DOCUMENT MEMO — measured hotspot, zero semantic change. A slow query
        # (zlmn INVOICE_ID) ran this 584 times = 31.2s: the SAME anchor annotation
        # gets its aligned-neighbour list recomputed across fallback attempts and
        # across the 12 anchor texts, while the document's annotations NEVER change
        # within an OcrQuery's lifetime. Pure geometry over immutable input → safe
        # to remember. Drawing runs have side effects, so they bypass the memo.
        memo_ok = draw_overwrite is False or (draw_overwrite is None and not self.draw)
        memo_key = (id(annotation), relative_position, max_candidates, self._region_key)
        if memo_ok:
            cached = self._aligned_memo.get(memo_key)
            if cached is not None:
                return cached

        filtered_annotations = [x for x in self.text_annotations if not (x == annotation or x.in_annotation(annotation) or annotation.in_annotation(x))]
        rtl = annotation.is_rtl()
        # Figuring Alignment Position based on the Relative Position
        # If rtl, right is before and left is after and opposite for ltr
        # ex: שם: שלומי. the value that appres to the left of "שם" is the the value after "שם:"
        # ex: name: shlomi. the value that appres to the right of "name" is the the value after "name:"
        if not relative_position:
            alingement_positon = None
        elif relative_position == RelativePosition.BEFORE:
            alingement_positon = AlignmentPosition.RIGHT if rtl else AlignmentPosition.LEFT
        elif relative_position == RelativePosition.AFTER:
            alingement_positon = AlignmentPosition.LEFT if rtl else AlignmentPosition.RIGHT
        elif relative_position == RelativePosition.ABOVE:
            alingement_positon = AlignmentPosition.ABOVE
        elif relative_position == RelativePosition.BELOW:
            alingement_positon = AlignmentPosition.BELOW
        
        max_candidates = max_candidates if max_candidates is not None else int(os.getenv("APITOOLS_ALIGNMENT_MAX_CANDIDATES", "250"))
        if alingement_positon and max_candidates > 0 and len(filtered_annotations) > max_candidates:
            anchor_center = annotation.bounding_box.center

            def candidate_sort_key(candidate: AnnotationObject):
                center = candidate.bounding_box.center
                dx = center.x - anchor_center.x
                dy = center.y - anchor_center.y
                if alingement_positon == AlignmentPosition.RIGHT and dx < -annotation.bounding_box.width:
                    return None
                if alingement_positon == AlignmentPosition.LEFT and dx > annotation.bounding_box.width:
                    return None
                if alingement_positon == AlignmentPosition.BELOW and dy < -annotation.bounding_box.height:
                    return None
                if alingement_positon == AlignmentPosition.ABOVE and dy > annotation.bounding_box.height:
                    return None
                return dx * dx + dy * dy

            ranked_candidates = []
            for candidate in filtered_annotations:
                sort_key = candidate_sort_key(candidate)
                if sort_key is not None:
                    ranked_candidates.append((sort_key, candidate))
            ranked_candidates.sort(key=lambda item: item[0])
            filtered_annotations = [candidate for _, candidate in ranked_candidates[:max_candidates]]

        alinged_annotations: AlignedAnnotations = annotation.aligned_annotations(filtered_annotations, position=alingement_positon)
        alinged_annotations_in_position = [al.annotation for al in alinged_annotations.alinged_annotations if not alingement_positon or al.btb_alignment.alignment_position == alingement_positon]
        
        if self.draw and draw_overwrite != False:
            # Draw the alignment lines
            alingments_in_position = [al.btb_alignment for al in alinged_annotations.alinged_annotations if not alingement_positon or al.btb_alignment.alignment_position == alingement_positon]
            for al in alingments_in_position:
                self.ocr_drawer.draw_alignment_check(al, draw_bboxes=False, draw_alingment_info=False, draw_alingment_guidelines=False)

        if memo_ok:
            self._aligned_memo[memo_key] = alinged_annotations_in_position
        return alinged_annotations_in_position


    def find_value_by_relative_position(self, texts: List[str], relative_position: RelativePosition, match_index=0,
                                        skip_intro=True, fuzzy=True) -> RelativePositionQueryResult:
        """
        Function to find the value that is visually aligned with the given relative position of texts (first match)
        :param texts:  List of texts to find - the first match will be used
        :param relative_position: Relative position of the value to find
        :param match_index: Index of the match to use (of the text matches)
        :param rtl: If using right to left language, before and after are flipped
        :param skip_intro: If True, skip intro annotations (e.g. ":", "-") and use the next annotation
        :param fuzzy: If True, use fuzzy matching (e.g. "Shipment ID" matches "Shipment IO:")
        :return: dictionary with the aligned value, aligned annotation, text match annotation and match index
        """

        #  Finding the matching annotations for the given texts
        max_match_attempts = int(os.getenv("APITOOLS_MAX_MATCH_ATTEMPTS", "30"))
        matching_annotations = self.find_texts_matching_annotations(texts, fuzzy=fuzzy, max_matches=max_match_attempts)

        # Order the anchor matches before indexing. A grand-total label ("סה\"כ",
        # "יתרה לתשלום") also heads a table column further up the page, so we must anchor on
        # the LOWEST occurrence. A negative match_index cannot express this: on a validation
        # failure json_query retries with match_index + 1, which wraps -1 back to 0. Sorting
        # instead makes index 0 the bottom-most match and lets the retry walk upwards.
        order = getattr(self, 'anchor_order', None)
        if order in ('bottom', 'top') and matching_annotations:
            matching_annotations = sorted(
                matching_annotations,
                key=lambda a: a.bounding_box.center_y,
                reverse=(order == 'bottom'))

        # If no match found, try to find match using alignment (more expensive) and combine the results
        if not has_index(matching_annotations, match_index):
            matches_by_alignment = self.find_texts_matching_annotations_via_alignment(texts, fuzzy=fuzzy) or []
            for match in matches_by_alignment:
                if match not in matching_annotations:
                    matching_annotations.append(match)
        
        if self.draw:
            self.ocr_drawer.draw_annotations(matching_annotations, color="green")
        logger.debug(f"Matching annotations for texts '{texts}': {matching_annotations}")

        # If no match found at index, raise exception
        if not has_index(matching_annotations, match_index):
            raise MatchNotFound(f"No match found for texts: {texts} at index {match_index}")

        # Try to find the aligned annotations for the next text match annotation, Until alignments are found or all
        # text match annotations are checked
        text_match_annotation = None
        aligned_annotations: List[AnnotationObject] = []
        aligned_annotation: AnnotationObject | None = None
        while not aligned_annotation:
            # Check if index is out of bounds (handle both positive and negative indices)
            if not has_index(matching_annotations, match_index):
                raise AlignmentNotFound(f"No alignment found {relative_position.value} texts: {texts},"
                                        f" at index {match_index}")

            text_match_annotation = matching_annotations[match_index]
            logger.debug(f"Selected text match annotation: {text_match_annotation}")

            # Getting annotations aligned with the text match annotation
            aligned_annotations = self.annotations_aligned_with_annotation(
                text_match_annotation, relative_position=relative_position)
            
            logger.debug(f"Aligned annotations: "
                         f"{relative_position}: {[x.description for x in aligned_annotations]}, "
            )

            if aligned_annotations:
                if getattr(self, 'value_order', None) == 'bottom':
                    aligned_annotations = sorted(
                        aligned_annotations, key=lambda a: a.bounding_box.center_y, reverse=True)
                aligned_annotation = aligned_annotations[0]
            else:
                match_index += 1
        
        if self.draw:
            self.ocr_drawer.draw_annotations(aligned_annotations, color="lightblue")

        # Skip intro annotations (e.g. ":", "-") if needed
        next_alignment_index = 1
        while skip_intro and aligned_annotation.is_intro() and len(aligned_annotations) > next_alignment_index:
            aligned_annotation = aligned_annotations[next_alignment_index]
            next_alignment_index += 1

        if self.draw:
            self.ocr_drawer.draw_annotations([aligned_annotation], color="blue")
            
        aligned_value = aligned_annotation.description
        return RelativePositionQueryResult(
            aligned_value=aligned_value,
            aligned_annotation=aligned_annotation,
            text_match_annotation=text_match_annotation,
            match_index=match_index,
        )

    def find_matching_texts(self, texts: List[str], fuzzy=True, as_dict=False, draw=False) -> dict:
        """ 
        Searches for the given texts in the OCR data and returns a dictionary with the matching options and their annotations.
        Basicly checks if one of the texts appers in ocr
        Args:
            texts (List[str]): List of texts to search for.
            fuzzy (bool, optional):  Should we use fuzzy matching or not. Defaults to True.
            as_dict (bool, optional): If True, return the annotations as a dictionary. Defaults to False.
            draw (bool, optional): If True, draw the annotations on the image. Defaults to False.

        Returns:
            dict: _description_
        """
        response = {

        }
        matches = []
        # PROFILED LIVE (2026-08-06): the previous fixes cap the cost of matching ONE option
        # against the document, but nothing capped the NUMBER of options. This action's caller
        # (documentJsonQuery "find option") is used for company-identification — measured live,
        # the request actually being sent for this call carries **2383** identifiers (confirmed
        # via the truncation-warning log, not an estimate), not the "~14" visible in a
        # log line truncated for readability. n_annotations(<=729) x n_options(2383) was landing
        # at 135k-158k fuzzy comparisons per request, cumulative 96-140s, and STILL hitting the
        # 180s ceiling; even truncated to 60 it measured 129s on the largest known-bad document —
        # too close to the ceiling to trust under load. 2383 candidate companies for ONE document
        # is almost certainly a call-site defect upstream (a full tenant company directory, not a
        # per-document candidate list) — see apps/apitools' owner report for the call-site this
        # traces to. Capped here regardless, low enough to leave real margin under the deadline:
        # real per-document option lists are short.
        max_options = int(os.getenv("APITOOLS_FIND_OPTION_MAX_TEXTS", "25"))
        if max_options > 0 and len(texts) > max_options:
            logger.warning(f"Reached max_options limit ({max_options}) for find option "
                            f"({len(texts)} texts supplied). Truncating.")
            texts = texts[:max_options]
        # TODO make matches return the text of each match so we can complete this with one call
        for option in texts:
            option_matches = self.find_texts_matching_annotations([option], fuzzy=fuzzy)
            if not option_matches:
                # OCR can split a multi-word phrase into tokens whose READING ORDER is
                # scrambled (a Priority letterhead reads "תעודת"/"משלוח" with other tokens
                # between them, so the following-annotation matcher misses it) even though
                # the words are visually ADJACENT on the same line. Fall back to spatial
                # alignment, which reconstructs the phrase from aligned tokens — a word break
                # never loses a match when the words are aligned.
                option_matches = self.find_texts_matching_annotations_via_alignment(
                    [option], fuzzy=fuzzy) or []

            if option_matches:
                # draw BEFORE any as_dict conversion — drawing needs the objects
                if draw:
                    self.ocr_drawer.draw_annotations(option_matches, color="blue")
                if as_dict:
                    option_matches = [option_match.annotation_dict for option_match in option_matches]
                matches.append({
                    "option": option,
                    "match_annotations": option_matches
                })

        if matches:
            response["matches"] = matches
        else:
            response["error"] = "No option found"

        # TODO: change to return model instead of dict
        return response


def ocr_query_factory(file_path: str, draw=True) -> OcrQuery:
    ocr = OcrData.from_file_path(file_path)
    ocr_drawer = OcrDrawings(ocr)
    return OcrQuery(ocr, ocr_drawer, draw)


def ocr_find_by_relative_position_example_pdf():
    filename = f"{pdf_test_files_path()}/test2.pdf"
    ocr_query = ocr_query_factory(filename)

    try:
        find_results = ocr_query.find_value_by_relative_position(
            texts=["תאריך:"],
            relative_position=RelativePosition.AFTER,
            fuzzy=True)

        if find_results.aligned_value is None:
            print("No annotation found")
        else:
            print("Aligned value: ", find_results.aligned_value)
            print(f"Find results: {find_results}")

    except MatchNotFound as e:
        print(e)


def ocr_find_by_relative_position_example():
    filename = f"{ocr_test_fails_path()}/rotated.jpg"
    # filename = f"{ocr_test_files_path()}/s-test.jpg"
    # filename = f"{ocr_test_files_path()}/file9.jpg"
    ocr_query = ocr_query_factory(filename)

    try:
        find_results = ocr_query.find_value_by_relative_position(
            texts=["תעודת משלוח"],
            # texts=["חשבונית מס מספר"],
            # texts=["טקסט"],
            relative_position=RelativePosition.AFTER,
            fuzzy=True)
        
        if  find_results.aligned_value is None:
            print("No annotation found")
        else:
            print("Aligned value: ", find_results.aligned_value)
            print(f"Find results: {find_results}")
    except MatchNotFound as e:
        print(e)
    except AlignmentNotFound as e:
        print(e)
        
    ocr_query.ocr_drawer.show()


def ocr_find_option_example():
    filename = f"{ocr_test_files_path()}/file10.jpg"
    ocr_query = ocr_query_factory(filename)
    options_res = ocr_query.find_matching_texts(["משימה משימה", "חוליות זרימה", "nahnv sdkj", "046946011", "google"])
    if "error" in options_res:
        print(options_res["error"])
    else:
        for match in options_res["matches"]:
            print("Option:", match["option"])
            for match_annotation in match["match_annotations"]:
                print("Match:", match_annotation.annotation_dict)


def text_matching_using_alignment_example():
    filename = f"{ocr_test_files_path()}/file105.jpg"
    ocr_query = ocr_query_factory(filename)
    matches = ocr_query.find_texts_matching_annotations_via_alignment(["תעודת משלוח"], fuzzy=True)

    if matches is None:
        print("No matches found")
    else:
        draw_annotations(filename, matches)
        for match in matches:
            print("Match:", match)


def compare_matching_algo_time():
    filename = f"{ocr_test_files_path()}/file73.jpg"
    ocr_query = ocr_query_factory(filename)

    text = "חשבונית מס"

    # Warm-up runs
    for _ in range(5):
        ocr_query.find_texts_matching_annotations([text])
        ocr_query.find_texts_matching_annotations_via_alignment([text])

    # Measure simple text matching
    simple_times = []
    for _ in range(100):  # Run multiple times for better accuracy
        start = time.perf_counter_ns()
        matches = ocr_query.find_texts_matching_annotations([text])
        end = time.perf_counter_ns()
        simple_times.append(end - start)
    average_simple_time = sum(simple_times) / len(simple_times)
    print(f"Average simple text matching time: {average_simple_time} ns.")
    print("Matches:", matches)

    # Measure text matching using alignment
    alignment_times = []
    for _ in range(100):  # Run multiple times for better accuracy
        start = time.perf_counter_ns()
        matches = ocr_query.find_texts_matching_annotations_via_alignment([text])
        end = time.perf_counter_ns()
        alignment_times.append(end - start)
    average_alignment_time = sum(alignment_times) / len(alignment_times)
    print(f"Average text matching using alignment time: {average_alignment_time} ns.")
    print("Matches:", matches)


def simple_match_example():
    filename = f"{ocr_test_files_path()}/file68.jpg"
    ocr_query = ocr_query_factory(filename)
    matches = ocr_query.find_texts_matching_annotations(["חשבונית מס זיכוי מס"], fuzzy=True)
    if matches is None:
        print("No matches found")
    else:
        for match in matches:
            print("Match:", match)


def check_simple_texts_matching_annotations_v2():
    filename = f"{ocr_test_files_path()}/file68.jpg"
    ocr_query = ocr_query_factory(filename)
    matches = ocr_query.find_texts_matching_annotations(["חשבונית מס", "וורקר בע\"מ", "www.worker.co.il"], fuzzy=True)
    if matches is None:
        print("No matches found")
    else:
        print("Ocr:", ocr_query.ocr_data.full_text)

        draw_annotations(filename, matches)
        for match in matches:
            print("Match:", match)


if __name__ == "__main__":
    ocr_find_by_relative_position_example()
    input("Press Enter to continue...")

    ocr_find_option_example()
    input("Press Enter to continue...")

    ocr_find_by_relative_position_example_pdf()
    input("Press Enter to continue...")

    check_simple_texts_matching_annotations_v2()
    input("Press Enter to continue...")

    ocr_find_option_example()
    input("Press Enter to continue...")

    simple_match_example()
    input("Press Enter to continue...")

    text_matching_using_alignment_example()
    input("Press Enter to continue...")

    compare_matching_algo_time()
    input("Press Enter to continue...")
