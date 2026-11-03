"""Hebrew text normalisation for ASR scoring (shared by score.py and the LLM layer).

normalize(text) -> list of tokens:
  * niqqud / cantillation removed (U+0591-U+05BD, U+05BF, U+05C1-U+05C2, U+05C4-U+05C5, U+05C7)
  * maqaf (U+05BE) and dashes become spaces
  * geresh / gershayim and ASCII quotes inside words are removed (צה"ל -> צהל)
  * all other punctuation removed; Latin letters lower-cased; digits kept
  * bidi control characters removed
"""
import re
import unicodedata

_NIQQUD = re.compile(r"[֑-ׇֽֿׁׂׅׄ]")
_BIDI = re.compile(r"[‎‏‪-‮⁦-⁩﻿]")
_DASH = re.compile(r"[־\-‐-―_/]")
_QUOTE = re.compile(r"[׳״'\"`‘’“”]")
_KEEP = re.compile(r"[^א-תa-z0-9 ]")


def normalize(text):
    if not text:
        return []
    t = unicodedata.normalize("NFKC", text)
    t = _BIDI.sub("", t)
    t = _NIQQUD.sub("", t)
    t = _DASH.sub(" ", t)
    t = _QUOTE.sub("", t)
    t = t.lower()
    t = _KEEP.sub(" ", t)
    return t.split()


def norm_str(text):
    return " ".join(normalize(text))
