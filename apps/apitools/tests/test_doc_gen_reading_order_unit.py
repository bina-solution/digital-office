"""A generated document reads right to left — to the eye, and to the reader the pipeline uses.

The owner opened a synthetic test document on 2026-08-25 and its Hebrew was backwards. That one
came from a throwaway generator in an agent's scratch directory (it drew the text without bidi
and rasterised the page); the generator in this tree was never the cause — but nothing asserted
that it could not become it. These tests do, for every document type and for both render paths
(the WeasyPrint template, and the fitz renderer `render()` drops to when WeasyPrint is missing):

  * the page HAS a text layer — a rasterised page forces OCR on a document we wrote ourselves;
  * the model's words READ as written. PyMuPDF hands a line's Hebrew back in the order it is
    seen, right to left, so a page drawn without bidi, or from strings somebody reversed, comes
    back reversed — which is also exactly what the keyword anchors would be matched against;
  * in the app's own image, the primary path is the one that ran.

What is NOT asserted, because it is the reader's side and not the generator's: on a line that
mixes Hebrew with a number in parentheses, an extractor returns the runs left to right
(`get_text()` gives «) בע"מ1988( אגן מפעלי הנדסה»). `ocr_core/pdf_textlayer.py` walks a Hebrew
line's spans right to left for that reason.
"""
import dataclasses
import re
import unittest

import fitz  # pymupdf

from src.doc_gen.render import _render_legacy, render
from src.doc_models import DOC_TYPES, sample

_HEB_WORD = re.compile("[א-ת]{3,}")


def _model_words(obj):
    """The Hebrew words (three letters or more) anywhere in a document model."""
    if dataclasses.is_dataclass(obj):
        obj = dataclasses.asdict(obj)
    if isinstance(obj, dict):
        obj = list(obj.values())
    if isinstance(obj, (list, tuple)):
        return {w for v in obj for w in _model_words(v)}
    return set(_HEB_WORD.findall(obj)) if isinstance(obj, str) else set()


class TestGeneratedDocumentsReadRightToLeft(unittest.TestCase):
    def test_every_type_on_both_paths_reads_as_written(self):
        for doc_type in sorted(DOC_TYPES):
            model = sample(doc_type, 1)
            words = _model_words(model)
            for path, pdf in (("weasyprint", render(model, "pdf")),
                              ("fitz fallback", _render_legacy(model, "pdf", 200, ""))):
                with self.subTest(doc_type=doc_type, path=path):
                    doc = fitz.open(stream=pdf, filetype="pdf")
                    layer = re.sub(r"\s+", "", "".join(page.get_text() for page in doc))
                    self.assertGreater(len(layer), 200, "no text layer: the page was rasterised")
                    backwards = {w for w in words if w not in layer and w[::-1] in layer}
                    self.assertEqual(backwards, set(), "Hebrew reads backwards")
                    self.assertGreaterEqual(len({w for w in words if w in layer}), 10,
                                            "the model's words are not on the page")

    def test_the_primary_path_is_the_one_that_ran(self):
        # render() drops to the fitz renderer when WeasyPrint cannot be imported. In this image
        # WeasyPrint is a requirement, so a document that is not its work means it broke.
        pdf = render(sample("INVOICE", 1), "pdf")
        producer = fitz.open(stream=pdf, filetype="pdf").metadata.get("producer") or ""
        self.assertIn("WeasyPrint", producer)


if __name__ == "__main__":
    unittest.main()
