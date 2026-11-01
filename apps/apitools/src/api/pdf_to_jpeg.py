import io
import os.path
import tempfile
from typing import List, Literal

import cv2
import numpy as np
from PIL import Image
from flask import send_file, Request, jsonify
from pdf2image import convert_from_path

from src.pdf_core.pdf_to_jpg import pdf_to_jpg_from_path
from src.utils.deskew import deskew
from src.utils.storage import pdfs_path
from src.utils.logging_config import get_logger
from src.utils import autoscale
from src.api.ocr_api import _expensive_request_slot, _busy_response

logger = get_logger('apitools.pdf_to_jpeg')

ALLOWED_EXTENSIONS = {'pdf'}

# %PDF- must appear near the start of a valid PDF (the spec allows a few bytes of
# leading junk before the header, some scanners/exports prepend a BOM or whitespace,
# so this checks the first 1KB rather than requiring an exact prefix match).
_PDF_MAGIC = b'%PDF-'
_PDF_MAGIC_SCAN_WINDOW = 1024


def _looks_like_pdf(head_bytes: bytes) -> bool:
    return _PDF_MAGIC in head_bytes[:_PDF_MAGIC_SCAN_WINDOW]


def resize_to_width(image, target_width):
    """
    Resizes an image to a specified width while maintaining the aspect ratio.

    Args:
        image: The input image (numpy array).
        target_width: The desired width of the resized image.

    Returns:
        The resized image (numpy array).
    """
    original_height, original_width = image.shape[:2]
    aspect_ratio = original_width / original_height

    new_width = target_width
    new_height = int(new_width / aspect_ratio)  # Maintain aspect ratio

    resized_image = cv2.resize(image, (new_width, new_height),
                               interpolation=cv2.INTER_AREA)  # High-quality interpolation for downscaling

    return resized_image


def optimized_pdf_to_jpeg(request: Request):
    logger.debug(f"PDF to JPEG request, files: {list(request.files.keys())}")
    if 'file' not in request.files:
        return "No file part", 400

    pdf_file = request.files['file']
    if pdf_file.filename == '':
        return "No selected file", 400
    filename = pdf_file.filename

    if not allowed_file(pdf_file.filename):
        return "File type not allowed", 400

    # Cheap sanity check BEFORE the expensive poppler round-trip: a `.pdf`-named
    # upload that is actually corrupt/truncated or not a PDF at all (wrong file,
    # a renamed image, an HTML error page saved with a .pdf extension, ...) makes
    # convert_from_path() throw PDFPageCountError deep inside poppler after doing
    # real work. Measured in production: 18 of 25 /pdfToJpeg calls in one 90-minute
    # window failed this way, each still burning 120ms-6s of CPU before failing,
    # and surfacing as a client-facing 500 (server fault) for what is actually a
    # 400 (bad input). Reading the header is ~free — check it first.
    head_bytes = pdf_file.stream.read(_PDF_MAGIC_SCAN_WINDOW)
    pdf_file.stream.seek(0)
    if not _looks_like_pdf(head_bytes):
        logger.warning(f"Rejected non-PDF upload: {filename}")
        return jsonify({'error': 'not_a_pdf',
                        'message': 'File does not look like a valid PDF (no %PDF- header found)'}), 400

    # CPU/memory-heavy rasterization (poppler + cv2) had no admission control at
    # all — unlike /documentOcr and /documentJsonQuery, which are each bounded by
    # their own _expensive_request_slot pool, /pdfToJpeg could run fully unbounded
    # concurrently, competing for the same CPU the OCR/JSON-query bulkheads are
    # sized against (see autoscale.py) and inflating their queueing/latency under
    # load. Same bulkhead pattern as OCR: its own slot pool so it cannot starve,
    # or be starved by, the other two.
    max_pdf_slots = int(os.getenv("APITOOLS_MAX_CONCURRENT_PDF") or autoscale.ocr_slots_default())
    with _expensive_request_slot("pdf_to_jpeg", max_pdf_slots) as acquired:
        if not acquired:
            return _busy_response("PDF to JPEG", max_pdf_slots)

        with tempfile.TemporaryDirectory() as temp_dir:
            # Save PDF temporarily
            pdf_file_path = tempfile.NamedTemporaryFile(dir=temp_dir, delete=False).name
            pdf_file.save(pdf_file_path)
            pdf_file.close()

            jpeg_image_bytes = pdf_to_jpg_from_path(pdf_file_path)

            new_filename = os.path.splitext(filename)[0] + ".jpg"
            return send_file(jpeg_image_bytes, as_attachment=True, download_name=new_filename)


def pdf_path_to_jpeg_path(pdf_file_path: str):
    pdf_storage_path = pdfs_path()
    images = convert_from_path(pdf_file_path, dpi=50, output_folder=pdf_storage_path, paths_only=True)
    logger.debug(f"PDF converted, pages: {len(images)}")

    # save first image
    first_image = cv2.imread(images[0])
    cv2.imwrite("first.jpg", first_image)
    images = [cv2.imread(image_path, 1) for image_path in images]
    rotated_images = [deskew(image) for image in images]
    del images

    # make all images the same size
    max_width = max(image.shape[1] for image in rotated_images)
    resized_images = [resize_to_width(image, max_width) for image in rotated_images]
    del rotated_images

    joined = cv2.vconcat(resized_images)
    del resized_images

    cv2.imwrite("joined.jpg", joined)
    _, encoded_image = cv2.imencode('.jpg', joined)
    del joined
    image_bytes = io.BytesIO(encoded_image)
    image_bytes.seek(0)
    return image_bytes


def pdf_to_jpeg(request: Request):
    logger.debug(f"PDF to JPEG legacy request, files: {list(request.files.keys())}")
    if 'file' not in request.files:
        return "No file part", 400

    pdf_file = request.files['file']
    if pdf_file.filename == '':
        return "No selected file", 400

    if not allowed_file(pdf_file.filename):
        return "File type not allowed", 400

    with tempfile.TemporaryDirectory() as temp_dir:
        # Save PDF temporarily
        pdf_file_path = tempfile.NamedTemporaryFile(dir=temp_dir, delete=False).name
        pdf_file.save(pdf_file_path)

        # Convert PDF to images
        images = convert_pdf_to_jpegs(pdf_file_path, temp_dir)
        images = autorotate_images(images)

        joined_image = join_images(images, vertical=True)

        # Prepare response
        response = prepare_response(joined_image)

        return response


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def convert_pdf_to_jpegs(pdf_file_path, output_dir):
    images = convert_from_path(pdf_file_path, dpi=300, output_folder=output_dir)
    return images


def autorotate_images(images: List[Image.Image]):
    cv_images = [np.array(image.convert("RGB")) for image in images]
    rotated_images = [deskew(image) for image in cv_images]
    images = [Image.fromarray(image) for image in rotated_images]
    return images


def join_images(images: List[Image.Image], vertical=False):
    # combine images horizontally or vertically
    widths, heights = zip(*(i.size for i in images))
    if vertical:
        total_width = max(widths)
        total_height = sum(heights)
    else:
        total_width = sum(widths)
        total_height = max(heights)

    new_image = Image.new('RGB', (total_width, total_height))

    offset = 0
    for image in images:
        if vertical:
            new_image.paste(image, (0, offset))
            offset += image.height
        else:
            new_image.paste(image, (offset, 0))
            offset += image.width

    return new_image


def prepare_response(image):
    image_bytes = io.BytesIO()
    image.save(image_bytes, format="JPEG")
    image_bytes.seek(0)
    return send_file(image_bytes, as_attachment=True, download_name="converted_images.jpg")


def prepare_response_big_image(images):
    # prepare response to one big image horizontally
    # combine images horizontally
    widths, heights = zip(*(i.size for i in images))
    total_width = max(widths)
    max_height = sum(heights)

    new_image = Image.new('RGB', (total_width, max_height))

    y_offset = 0
    for image in images:
        new_image.paste(image, (0, y_offset))
        y_offset += image.height

    image_bytes = io.BytesIO()
    new_image.save(image_bytes, format="JPEG")
    image_bytes.seek(0)
    return send_file(image_bytes, as_attachment=True, download_name="converted_images.jpg")


def check_pdf_path_to_jpeg():
    pdf_file_path = "sample.pdf"
    image_bytes = pdf_path_to_jpeg_path(pdf_file_path)
    return image_bytes
