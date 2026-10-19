import io
import os
import tempfile
from typing import List

import cv2
from pdf2image import convert_from_path

from src.image_core.image_utils import resize_to_width
from src.utils.deskew import deskew
from src.utils.storage import pdfs_path, pdf_test_files_path
from src.utils.logging_config import get_logger

logger = get_logger('apitools.pdf_to_jpg')


# DPI at which PDFs are rasterized before OCR. 96 DPI was far too low for reliable
# text recognition — small Hebrew glyphs and digits turn to mush (e.g. tax-id
# 510564693 was misread as 510564699, and multi-word phrases like "חשבונית זיכוי"
# fragmented), causing UNKNOWN types / missing company-id / failed amount extraction.
# Empirical dataset sweep (96/120/150/200/250/300): tax-id digits become correct from
# 120 DPI; type/amount accuracy plateaus at 150 (amount 50%→100%, type 66%→~80%);
# 200+ adds no measurable gain. 200 is the chosen default — fixes all the above while
# staying lighter than 300 on memory/CPU. Image preprocessing (upscale+threshold) made
# NO difference at this DPI (it only helps low-res phone photos). Override via APITOOLS_PDF_DPI.
PDF_OCR_DPI = int(os.getenv('APITOOLS_PDF_DPI', '300'))


class PdfToJpgException(Exception):
    pass


# OpenCV's hard ceiling (imencode/imwrite): "Maximum supported image dimension is 65500
# pixels". A page at 300 DPI is ~3300-3900px tall in portrait; 17+ pages vertically
# concatenated crosses it (measured live 2026-08-06: a 17-page PDF's joined canvas hit
# 66,300px and crashed `documentOcr` outright — 2 of 4 concurrent calls on it failed with
# this exact error, a ~50% failure rate on large documents independent of load). OCR no
# longer depends on this joined canvas at all (see pdf_pages_to_jpeg_bytes below, used by
# ocr_processor for the actual recognition) — this function now exists ONLY to produce the
# optional drawing/visualization base image, so exceeding the limit degrades a debug
# feature, not extraction. Downscale rather than crash.
CV2_MAX_DIM = 65500


def pdf_to_jpg_from_path(pdf_file_path: str, output_file_path=None):
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # RENDER AT THE CLAMPED DPI, NOT PDF_OCR_DPI (fixed 2026-08-11).
            #
            # THIS FUNCTION WAS THE MEMORY INCIDENT. _effective_dpi_for_page existed and was
            # applied by pdf_pages_to_jpeg_bytes — the path that does the actual OCR — but NOT
            # here, and this is the larger allocation of the two. `convert_from_path` applied
            # PDF_OCR_DPI (300) unconditionally against whatever the MediaBox claimed, so the
            # 66.8x95.1in pages in this corpus rendered at 572 MP EACH (~1.7 GB decoded), and
            # the very next line loads EVERY page at once into a list, then deskew() takes a
            # full .copy() and warpAffine allocates another. A 2-page document of that shape
            # is >3.4 GB before the vconcat. Measured live on a 9.95 GiB host: apitools went
            # 0.53 -> 3.6 -> 4.17 GiB, swap hit 6144/6144 = 100%, free RAM 118 MB, load 29.5,
            # n8n execution throughput collapsed 359/min -> 9/min, and `drive` and
            # `incoming-documents` were both OOM-killed. incoming-documents serves the Render
            # Thumbnail call in the same upload path, so the raster took out its own pipeline.
            #
            # The bitter part: by the time this runs the OCR has ALREADY SUCCEEDED. Per the
            # comment on CV2_MAX_DIM above and the call site in ocr_processor.get_ocr, this
            # raster is the optional drawing/visualisation base — "a failure here must never
            # take down the extraction that already succeeded". It was spending gigabytes,
            # after the fact, on a debug image.
            #
            # Clamping from the LARGEST page mirrors _ocr_admission_weight's probe and is the
            # conservative choice: convert_from_path takes ONE dpi for the whole document, so
            # sizing off the biggest page guarantees no page exceeds MAX_MP_PER_PAGE. Normal
            # documents are untouched — A4 at 300 dpi is 8.7 MP, nowhere near the 24 MP
            # ceiling, so _effective_dpi_for_page returns PDF_OCR_DPI unchanged for them and
            # this is a no-op for the overwhelming majority.
            eff_dpi = PDF_OCR_DPI
            try:
                import fitz
                with fitz.open(pdf_file_path) as _d:
                    max_w_pt = max((p.rect.width for p in _d), default=595.0)
                    max_h_pt = max((p.rect.height for p in _d), default=842.0)
                eff_dpi = _effective_dpi_for_page(max_w_pt, max_h_pt, PDF_OCR_DPI)
                if eff_dpi != PDF_OCR_DPI:
                    logger.warning(
                        f"pdf_to_jpg_from_path: drawing raster for {max_w_pt:.0f}x{max_h_pt:.0f}pt "
                        f"would render to "
                        f"{(max_w_pt/72*PDF_OCR_DPI)*(max_h_pt/72*PDF_OCR_DPI)/1e6:.1f}MP/page at "
                        f"{PDF_OCR_DPI}dpi — clamped to {eff_dpi}dpi "
                        f"({MAX_MP_PER_PAGE:.1f}MP ceiling). file={pdf_file_path}")
            except Exception as e:  # noqa: BLE001 — a probe failure must not block the render
                logger.warning(f"pdf_to_jpg_from_path: dpi probe failed, using {PDF_OCR_DPI}dpi: {e}")

            image_paths: List[str] = convert_from_path(
                pdf_file_path, output_folder=temp_dir, dpi=eff_dpi, paths_only=True)

            # Auto align images. Read-deskew-release ONE page at a time: the previous
            # `[cv2.imread(p) for p in image_paths]` held every decoded page resident
            # simultaneously *and* deskew's internal copy on top, so peak was ~2x the whole
            # document rather than ~2x its largest page.
            aligned_images = []
            for image_path in image_paths:
                _img = cv2.imread(image_path, 1)
                aligned_images.append(deskew(_img))
                del _img

            # Make all images the same size
            max_width = max(image.shape[1] for image in aligned_images)
            resized_images = [resize_to_width(image, max_width) for image in aligned_images]
            del aligned_images

            # Join images to one long image
            joined = cv2.vconcat(resized_images)
            del resized_images

            # Guard the encoder's hard pixel-dimension ceiling — see CV2_MAX_DIM above.
            # This raster is drawing-only now, so shrinking it to fit costs nothing but
            # on-screen resolution for a pathologically long document.
            jh, jw = joined.shape[:2]
            if max(jh, jw) > CV2_MAX_DIM:
                scale = CV2_MAX_DIM / float(max(jh, jw)) * 0.98  # margin under the exact ceiling
                joined = cv2.resize(joined, (max(1, int(jw * scale)), max(1, int(jh * scale))),
                                    interpolation=cv2.INTER_AREA)

            if output_file_path:
                print(f"Saving image to {output_file_path}")
                cv2.imwrite(output_file_path, joined)

            _, encoded_image = cv2.imencode('.jpg', joined)
            del joined

            image_bytes = io.BytesIO(encoded_image)
            image_bytes.seek(0)
            return image_bytes
    except Exception as e:
        raise PdfToJpgException(f"Error converting PDF to JPG: {e} .\n"
                                f"filepath: {pdf_file_path}")


# RENDERED-PIXEL CEILING (2026-08-06): found live, from a production OOM episode — the
# class of bug, not just this instance. Two reproducer PDFs (2 and 3 pages, "ordinary
# scans" per how they were filed) have a page MediaBox of 2479x3506pt = 34.4x48.7in — not
# A4 (8.27x11.69in), ~17x the area. `convert_from_path` applies PDF_OCR_DPI (300)
# UNCONDITIONALLY against whatever the page rect claims, so each page rendered to
# 10329x14608px = 150.9 MP — ~453 MB for one decoded page before any derived copy (the
# preprocessing/recovery passes in local_ocr_engine.py each hold further copies at that
# same size). That is the actual RSS predictor for paged OCR: rendered megapixels
# (page-rect-area x dpi^2), not page count and not file bytes — a 3-page document at a
# sane page size can cost far less than a 1-page document with a bad MediaBox. Whether
# the oversized rect reflects genuine large-format content or (far more likely for a
# "scan") a scanner/producer metadata bug, capping RENDERED pixels is the general fix
# either way: a 150 MP render of a scanned page buys no OCR accuracy over a sane ceiling,
# it only buys OOM risk. Clamps the EFFECTIVE dpi down for oversized pages instead of
# rejecting them — normal-sized pages (the overwhelming majority) are completely
# unaffected, since their rect at PDF_OCR_DPI never approaches the ceiling.
MAX_MP_PER_PAGE = float(os.getenv("APITOOLS_MAX_MP_PER_PAGE", "24"))
MIN_EFFECTIVE_DPI = int(os.getenv("APITOOLS_MIN_EFFECTIVE_DPI", "100"))


def _effective_dpi_for_page(page_width_pt: float, page_height_pt: float, requested_dpi: int) -> int:
    """Return the DPI to actually render this page at: `requested_dpi`, unless that would
    exceed MAX_MP_PER_PAGE, in which case scaled down (never below MIN_EFFECTIVE_DPI)."""
    w_in = max(page_width_pt, 1.0) / 72.0
    h_in = max(page_height_pt, 1.0) / 72.0
    mp_at_requested = (w_in * requested_dpi) * (h_in * requested_dpi) / 1_000_000.0
    if mp_at_requested <= MAX_MP_PER_PAGE:
        return requested_dpi
    scale = (MAX_MP_PER_PAGE / mp_at_requested) ** 0.5
    return max(MIN_EFFECTIVE_DPI, int(requested_dpi * scale))


def pdf_pages_to_jpeg_bytes(pdf_file_path: str, dpi: int = None) -> List[bytes]:
    """Render each page of a PDF to its OWN deskewed JPEG, independently — no resize-to-
    common-width, no vconcat. Each page stays well under any single-raster size ceiling
    (a single 300-DPI portrait page is ~3300-3900px tall; the crash this replaces needed
    17+ pages joined to reach OpenCV's 65500px limit), and per-page OCR then costs one
    page's worth of peak memory per slot instead of the whole document's — UNLESS the
    page's own declared size is itself oversized, which MAX_MP_PER_PAGE above now catches.

    Returns [(jpeg_bytes, width, height), ...] in page order — width/height are the
    DESKEWED page's pixel size, needed by the caller to compute cumulative Y offsets when
    merging per-page OCR results back into one document-space coordinate system.
    """
    dpi = dpi or PDF_OCR_DPI
    try:
        # Probe page geometry (points, not pixels — cheap, no rendering) so a per-document
        # effective DPI can be chosen BEFORE any raster is produced. One effective DPI for
        # the whole document (not per-page) keeps the Y-offset merge in ocr_processor.py
        # simple — real multi-page scans are page-size-uniform, so this doesn't cost
        # anything real for the normal case, only for the oversized-MediaBox one.
        import fitz
        with fitz.open(pdf_file_path) as _d:
            # [zero-page verdict 2026-08-17, owner order] Say the truth at the component that
            # measures it. A structurally valid PDF whose page tree is empty (/Count 0,
            # /Kids []) reaches convert_from_path and dies there with poppler's cryptic
            # "the first page (1) can not be after the last page (0)" — which is pdftoppm's
            # phrasing of "there are zero pages to render". Verified byte-level on the live
            # corpus (235-byte scanner-produced shells). The producer of the count states it
            # plainly instead, BEFORE any rendering is attempted.
            if _d.page_count == 0:
                raise PdfToJpgException(
                    "PDF contains 0 pages — the file is a valid PDF shell with an empty page "
                    "tree (/Count 0); it was created empty by whatever produced it and nothing "
                    f"can be extracted. filepath: {pdf_file_path}")
            max_w_pt = max((p.rect.width for p in _d), default=595.0)
            max_h_pt = max((p.rect.height for p in _d), default=842.0)
        effective_dpi = _effective_dpi_for_page(max_w_pt, max_h_pt, dpi)
        if effective_dpi != dpi:
            logger.warning(
                f"pdf_pages_to_jpeg_bytes: page rect {max_w_pt:.0f}x{max_h_pt:.0f}pt "
                f"({max_w_pt/72:.1f}x{max_h_pt/72:.1f}in) would render to "
                f"{(max_w_pt/72*dpi)*(max_h_pt/72*dpi)/1e6:.1f}MP at {dpi}dpi — "
                f"clamped to {effective_dpi}dpi ({MAX_MP_PER_PAGE}MP ceiling). file={pdf_file_path}"
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            image_paths: List[str] = convert_from_path(
                pdf_file_path, output_folder=temp_dir, dpi=effective_dpi, paths_only=True)
            out = []
            for image_path in image_paths:
                im = cv2.imread(image_path, 1)
                im = deskew(im)
                h, w = im.shape[:2]
                ok, encoded = cv2.imencode('.jpg', im)
                if not ok:
                    raise PdfToJpgException(f"Failed to encode page as JPEG: {image_path}")
                out.append((encoded.tobytes(), w, h))
            return out
    except Exception as e:
        raise PdfToJpgException(f"Error converting PDF pages to JPEG: {e} .\n"
                                f"filepath: {pdf_file_path}")


def check_pdf_to_jpg_from_path():
    print(pdf_test_files_path())
    pdf_file_path = f"{pdf_test_files_path()}/test1.pdf"
    output_file = f"{pdf_test_files_path()}/test1.jpg"
    image = pdf_to_jpg_from_path(pdf_file_path, output_file_path=output_file)

    print("Done")


if __name__ == "__main__":
    check_pdf_to_jpg_from_path()
