import base64
import io
import json
import os
import tempfile
from PIL import Image
from typing import Literal, Optional
import cv2
import requests

from src.pdf_core.pdf_to_jpg import pdf_to_jpg_from_path, PDF_OCR_DPI
from src.utils.file_utils import get_mime_type_from_bytes
from src.utils.hash import md5_hash_string
from src.utils.storage import pdf_test_files_path, ocr_pdf_images_path, ocr_cache_path, \
    ocr_test_files_path
from src.utils.logging_config import get_logger
from json import JSONDecodeError

logger = get_logger('apitools.ocr_processor')

API_KEY = os.environ.get("GOOGLE_VISION_API_KEY", "")

# OCR engine toggle: "local" for Tesseract, "google" for Vision API
OCR_ENGINE = os.environ.get("OCR_ENGINE", "google")

# Google Cloud Vision rejects images above ~75 megapixels with "Bad image data"; local
# Tesseract has no such ceiling. A multi-page PDF rasterized at 300 DPI (tuned for
# Tesseract) can exceed it, so the Vision path — and only the Vision path — downscales
# an oversized raster first. Leaves Tesseract's full-res render untouched. Env-tunable.
VISION_MAX_PX = int(os.environ.get("APITOOLS_VISION_MAX_PX", str(68_000_000)))


# Ocr processor job is to perform OCR on files, it gets the file path and returns the OCR results
# It also has a cache mechanism to store the OCR results in a folder
# the cache mechanism uses hash of the filepath
# Reduce this class to do only one thing, perform OCR on files
# caching and retrival by file id should be done in ocr_object.py

class OcrProcessor:
    def __init__(self, api_key=API_KEY, ocr_engine=None):
        self.api_key = api_key
        self.api_url = f"https://vision.googleapis.com/v1/images:annotate?key={self.api_key}"
        self.ocr_engine = ocr_engine or OCR_ENGINE

        self.cache_folder = ocr_cache_path()
        self.pdf_images_folder = ocr_pdf_images_path()

        logger.info(f"OcrProcessor initialized with engine: {self.ocr_engine}")

    def _save_file_ocr(self, file_hash, file_ocr):
        """Persist OCR results into the OCR cache (Postgres by default, keyed by
        file_hash; transparent local-file fallback). See src.ocr_core.ocr_cache."""
        from src.ocr_core import ocr_cache
        ocr_cache.save(file_hash, file_ocr, self.cache_folder)

    def _load_file_ocr(self, file_hash):
        """Load OCR results from the OCR cache (Postgres by default, keyed by
        file_hash; transparent local-file fallback). See src.ocr_core.ocr_cache."""
        from src.ocr_core import ocr_cache
        return ocr_cache.load(file_hash, self.cache_folder)

    def pdf_path_to_jpg_path(self, file_hash):
        return f"{self.pdf_images_folder}/{file_hash}.jpg"

    
    def _fit_for_engine(self, raw: bytes) -> bytes:
        """Downscale an oversized raster so Google Vision accepts it (>~75 MP => "Bad image
        data"). No-op for the local Tesseract engine and for rasters already under the cap.
        Position/relative-query logic is scale-invariant, so extraction is unaffected."""
        if self.ocr_engine == "local":
            return raw
        try:
            im = Image.open(io.BytesIO(raw))
            w, h = im.size
            if w * h <= VISION_MAX_PX:
                return raw
            scale = (VISION_MAX_PX / float(w * h)) ** 0.5
            im = im.convert("RGB").resize((max(1, int(w * scale)), max(1, int(h * scale))))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=90)
            logger.info(f"Vision raster {w}x{h} ({w*h/1e6:.1f}MP) > cap; downscaled to {im.size}")
            return buf.getvalue()
        except Exception as e:
            logger.warning(f"_fit_for_engine downscale skipped: {e}")
            return raw

    def _encode_image_content(self, file_path, file_bytes: bytes, file_hash: str):
        """Produce base64 image content for the OCR request. The Vision engine caps the
        raster at its pixel ceiling; Tesseract keeps the full 300-DPI render."""
        mime_type = get_mime_type_from_bytes(file_bytes)

        if mime_type in ["image/heif"]:
            raise NotImplementedError("HEIF image type is not yet supported.")

        if mime_type in ["image/jpeg", "image/png"]:
            image_path = file_path
            raw = file_bytes
        elif mime_type == "application/pdf":
            image_path = self.pdf_path_to_jpg_path(file_hash)
            image_bytes = pdf_to_jpg_from_path(file_path, output_file_path=image_path)
            if not image_bytes:
                raise NotImplementedError("PDF to JPG conversion is not implemented.")
            raw = image_bytes.read()
        else:
            raise ValueError("Unsupported file type for OCR: " + mime_type)

        image_content = base64.b64encode(self._fit_for_engine(raw)).decode('utf-8')
        return image_content, image_path

    def _ocr_request_vision_api(self, image_content):
        """Prepare request for Vision API."""
        request_payload = {
            "requests": [
                {
                    "image": {
                        "content": image_content
                    },
                    "features": [
                        {
                            "type": "DOCUMENT_TEXT_DETECTION"
                        }
                    ],
                }
            ]
        }

        timeout = int(os.getenv("APITOOLS_GOOGLE_VISION_TIMEOUT", "120"))
        response = requests.post(self.api_url, json=request_payload, timeout=timeout)
        response_data = response.json()

        # Check for errors in the response
        if response.status_code != 200 or "error" in response_data:
            error_message = response_data.get("error", {}).get("message", "Unknown error")
            raise Exception(f"Vision API error: {error_message}")

        return response

    def _ocr_request_local(self, image_content):
        """Run OCR locally using Tesseract via local_ocr_engine."""
        from src.ocr_core.local_ocr_engine import ocr_from_base64
        return ocr_from_base64(image_content)

    def _ocr_engine_on_bytes(self, raw: bytes) -> dict:
        """Run the configured engine on one already-rendered raster and return its
        Vision-shaped dict — the same per-image call the old single-raster path made,
        just callable once per page instead of once for a whole joined document."""
        image_content = base64.b64encode(self._fit_for_engine(raw)).decode('utf-8')
        if self.ocr_engine == "local":
            return self._ocr_request_local(image_content)
        response = self._ocr_request_vision_api(image_content)
        return response.json()['responses'][0]

    def _ocr_pdf_paged(self, file_path: str, file_hash: str) -> dict:
        """OCR a scanned (non-text-layer) PDF one page at a time and merge the results
        into one document-space dict — replaces rasterising every page into a single
        vertically-joined canvas before OCR.

        WHY: that joined canvas (a) hit OpenCV's hard 65500px encode ceiling on large
        multi-page documents — measured live 2026-08-06, a 17-page PDF crashed
        `documentOcr` outright, 2 of 4 concurrent calls failed with this exact error, a
        ~50% failure rate on large documents independent of load — and (b) meant one
        OCR-slot's peak memory scaled with the WHOLE document instead of one page, which
        is what let 4 concurrent large documents OOM-kill gunicorn workers (measured the
        same day: 3 kernel OOM-kills, workers at 1.2-2.35 GiB resident each). Per-page
        OCR bounds both: no raster is ever taller than one page, and peak memory per
        slot is now one page's footprint, not the document's.

        The merge mirrors pdf_textlayer.ocr_from_pdf_textlayer's EXACT pattern (cumulative
        Y-offset per page, word annotations only, a synthesized page-0 bounding-box
        annotation) so every downstream consumer (OcrQuery region filtering, alignment,
        drawing) sees the identical coordinate space it always has — this is a cost/
        correctness fix, not a behavior change for callers.
        """
        from src.pdf_core.pdf_to_jpg import pdf_pages_to_jpeg_bytes
        pages = pdf_pages_to_jpeg_bytes(file_path)
        if not pages:
            raise NotImplementedError("PDF to JPG conversion produced no pages.")

        combined_words = []
        texts = []
        y_off = 0.0
        max_w = 0.0
        for raw, w, h in pages:
            page_dict = self._ocr_engine_on_bytes(raw)
            anns = page_dict.get('textAnnotations') or []
            page_text = (page_dict.get('fullTextAnnotation', {}) or {}).get('text') \
                or (anns[0].get('description', '') if anns else '')
            texts.append(page_text)
            max_w = max(max_w, w)
            for a in anns[1:]:  # skip this page's own page-level annotation (index 0)
                verts = (a.get('boundingPoly') or {}).get('vertices', [])
                new_a = dict(a)
                new_a['boundingPoly'] = {'vertices': [
                    {**v, 'y': v.get('y', 0) + y_off} for v in verts
                ]}
                combined_words.append(new_a)
            y_off += h

        full_text = '\n'.join(texts)
        page_ann = {
            "locale": "iw",
            "description": full_text,
            "boundingPoly": {"vertices": [
                {"x": 0, "y": 0}, {"x": int(max_w), "y": 0},
                {"x": int(max_w), "y": int(y_off)}, {"x": 0, "y": int(y_off)},
            ]},
        }
        return {"textAnnotations": [page_ann] + combined_words,
                "fullTextAnnotation": {"text": full_text}}

    def get_ocr(self, file_path, cache=True) -> dict:
        """Perform OCR using Google Cloud Vision API via HTTP request.
        It accepts a file path supporting PDF, JPG, and PNG files.
        If its a PDF file, it will convert it to JPG first.
        it returns the OCR results as a dictionary, along with the original file path and image path.
        """
        # Check if OCR result is cached

        # open file check if we have ocr cache for this file
        with open(file_path, "rb") as f:
            file_bytes = f.read()
            file_hash = md5_hash_string(file_bytes)

        if cache:
            cached_ocr = self._load_file_ocr(file_hash)
            if cached_ocr is not None:
                cached_ocr["original_file_path"] = file_path
                return cached_ocr

        import time as _time
        from datetime import datetime, timezone
        _ocr_t0 = _time.perf_counter()

        # OBSERVABILITY (2026-08-06): without this, nobody outside the process can tell a
        # large-document failure from a memory failure from a routing decision after the
        # fact — that ambiguity cost a full round this session. Logged for EVERY OCR call,
        # not just slow ones, so any request can be correlated with its document shape.
        mime_type = get_mime_type_from_bytes(file_bytes)
        is_pdf = mime_type == "application/pdf"
        page_count = None
        if is_pdf:
            try:
                import fitz
                with fitz.open(file_path) as _d:
                    page_count = _d.page_count
            except Exception:
                page_count = None

        # Born-digital PDFs already carry a perfect embedded text layer — read it
        # directly (PyMuPDF) instead of rasterising + OCR, which only injects OCR
        # error (mangled Hebrew, ₪→1, dropped digits). Scanned images (no text
        # layer) fall through to the OCR engine. Toggle with APITOOLS_BORN_DIGITAL=0.
        from src.ocr_core import pdf_textlayer
        text_layer_found = is_pdf and os.getenv("APITOOLS_BORN_DIGITAL", "1") == "1" \
            and pdf_textlayer.has_text_layer(file_path)
        logger.info(
            f"documentOcr routing: file_hash={file_hash} mime={mime_type} "
            f"page_count={page_count} dpi={PDF_OCR_DPI if is_pdf else None} "
            f"text_layer_found={text_layer_found} route="
            f"{'text_layer' if text_layer_found else ('paged_ocr' if is_pdf else 'image_ocr')}"
        )

        if text_layer_found:
            ocr_dict = pdf_textlayer.ocr_from_pdf_textlayer(file_path)
            # textlayer renders a coordinate-aligned raster for the query-overlay drawing
            image_path = ocr_dict.get("image_path")
        elif is_pdf:
            # Scanned (non-text-layer) PDF: OCR page-by-page — see _ocr_pdf_paged's
            # docstring for why (correctness AND memory, not just style).
            ocr_dict = self._ocr_pdf_paged(file_path, file_hash)
            # The joined raster is now drawing-only, built separately and best-effort:
            # a failure here (or an oversized-document downscale — see CV2_MAX_DIM in
            # pdf_to_jpg.py) must never take down the extraction that already succeeded.
            image_path = self.pdf_path_to_jpg_path(file_hash)
            try:
                pdf_to_jpg_from_path(file_path, output_file_path=image_path)
            except Exception as e:  # noqa: BLE001 — drawing base is optional
                logger.warning(f"documentOcr: drawing raster build failed (extraction unaffected): {e}")
                image_path = None
        else:
            # Prepare the image content for the Vision API (base64-encoded image)
            image_content, image_path = self._encode_image_content(file_path, file_bytes, file_hash)
            if self.ocr_engine == "local":
                ocr_dict = self._ocr_request_local(image_content)
            else:
                response = self._ocr_request_vision_api(image_content)
                response_data = response.json()
                ocr_dict = response_data['responses'][0]

        #  add original file path, image path and save to cache
        ocr_dict["original_file_path"] = file_path
        ocr_dict["image_path"] = image_path
        ocr_dict["file_id"] = file_hash
        ocr_dict.setdefault("ocr_engine", self.ocr_engine)
        # Provenance travels WITH the OCR (persisted to ocr_cache): which engine
        # produced it, on which apitools build, when, and how long the actual OCR
        # computation took. A cache hit months later still states the truth about
        # its origin — without this, a cached result is anonymous and a stale
        # engine/build is undetectable from the outside.
        from src.version import APITOOLS_VERSION
        ocr_dict["ocr_ms"] = int((_time.perf_counter() - _ocr_t0) * 1000)
        ocr_dict["apitools_version"] = APITOOLS_VERSION
        ocr_dict["ocr_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

        self._save_file_ocr(file_hash, ocr_dict)

        return ocr_dict

    def load_file_ocr_by_id(self, file_id):
        """Load OCR results from cache if available."""
        ocr_json = self._load_file_ocr(file_id)
        if ocr_json:
            return ocr_json
        raise FileNotFoundError(f"OCR results for file ID {file_id} not found")


def ocr_example():
    # file_path = f"{pdf_test_files_path()}/test1.pdf"
    file_path = f"{pdf_test_files_path()}/centerlized_invoce-1.pdf"
    file_path = f"{pdf_test_files_path()}/deskewed.jpg"

    ocr_processor = OcrProcessor()
    ocr_result = ocr_processor.get_ocr(file_path)
    full_text = ocr_result.get("fullTextAnnotation", {}).get("text", "")
    print(ocr_result.keys())
    input("Press Enter to continue...")

    im = cv2.imread(file_path)
    # draw all the annotations on the image
    for annotation in ocr_result.get('textAnnotations', []):
        print(annotation['description'])
        vertices = annotation['boundingPoly']['vertices']
        print(vertices)
        print("----")
        for i in range(len(vertices)):
            cv2.line(im, (vertices[i - 1]['x'], vertices[i - 1]['y']), (vertices[i]['x'], vertices[i]['y']),
                     (0, 255, 0), 2)
    cv2.imshow("Image", im)
    cv2.waitKey(0)

    print(full_text)


def ocr_pdf_example():
    pdf_filepath = f"{pdf_test_files_path()}/test1.pdf"
    ocr_processor = OcrProcessor()
    ocr_result = ocr_processor.get_ocr(pdf_filepath, cache=False)
    full_text = ocr_result.get("fullTextAnnotation", {}).get("text", "")
    print(full_text)

    original_file_path = ocr_result.get("original_file_path")
    original_image_path = ocr_result.get("image_path")
    print("Original File Path:", original_file_path)
    print("Original Image Path:", original_image_path)


def ocr_jpg_example():
    jpg_filepath = f"{ocr_test_files_path()}/file.png"
    ocr_processor = OcrProcessor()
    ocr_result = ocr_processor.get_ocr(jpg_filepath, cache=False)
    full_text = ocr_result.get("fullTextAnnotation", {}).get("text", "")
    print(full_text)

    original_file_path = ocr_result.get("original_file_path")
    original_image_path = ocr_result.get("image_path")
    print("Original File Path:", original_file_path)
    print("Original Image Path:", original_image_path)


if __name__ == "__main__":
    ocr_jpg_example()

    input("Press Enter to continue...")
    ocr_pdf_example()
