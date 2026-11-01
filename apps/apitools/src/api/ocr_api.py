import hashlib
import contextlib
import fcntl
from io import BytesIO
import signal
import threading
import time
from typing import Literal

import flask
from flask import Request, jsonify
from flask.testing import EnvironBuilder
from werkzeug.exceptions import ClientDisconnected

from src.ocr_core.ocr_object import OcrObject
from src.ocr_core.ocr_cache import OcrCacheUnavailable
from src.utils.storage import save_file, pdf_test_files_path, files_path
from src.utils.logging_config import get_logger, set_request_context
from src.version import APITOOLS_VERSION
from src.utils import autoscale
import os

logger = get_logger('apitools.ocr_api')


class QuerySoftTimeout(TimeoutError):
    pass


@contextlib.contextmanager
def _request_deadline(seconds: int):
    if seconds <= 0:
        yield
        return

    if threading.current_thread() is not threading.main_thread():
        logger.warning("Soft deadline disabled outside main thread")
        yield
        return

    def _handle_timeout(signum, frame):
        raise QuerySoftTimeout(f"request exceeded {seconds}s soft deadline")

    old_handler = signal.signal(signal.SIGALRM, _handle_timeout)
    old_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, old_timer[0], old_timer[1])


def _lockout_path(lock_dir: str, kind: str) -> str:
    return os.path.join(lock_dir, f"{kind}.drain_wait.marker")


def _lockout_active(lock_dir: str, kind: str, ttl_s: float) -> bool:
    """True if a heavy request has announced it's draining the pool and the
    announcement is still fresh (a stale one — e.g. its holder crashed — is ignored,
    so a dead process can never wedge admission shut)."""
    try:
        mtime = os.stat(_lockout_path(lock_dir, kind)).st_mtime
    except FileNotFoundError:
        return False
    return (time.time() - mtime) < ttl_s


@contextlib.contextmanager
def _expensive_request_slot(kind: str, max_slots: int, weight: int = 1,
                            wait_timeout: float = None):
    """Acquire ``weight`` of ``max_slots`` exclusive per-process file locks for *kind*,
    atomically — either all ``weight`` are held or none are (a partial acquire is
    released and retried as a whole, so two large documents can never each grab half
    the pool and deadlock waiting for the other half).

    When enough slots aren't free the caller blocks (polling every 100 ms) until they
    are, rather than immediately returning 429.  The maximum wait before giving up is
    ``APITOOLS_SLOT_WAIT_TIMEOUT`` seconds (default 600 s, 0 = wait forever bounded only
    by the gunicorn worker timeout).  Each ``kind`` has its own independent slot pool,
    so a queue of JSON-query requests cannot starve OCR uploads and vice-versa.

    ``weight`` is how page-count-aware OCR admission (see get_document_ocr) keeps four
    large documents from ever running concurrently while four small ones still can:
    a large document requests a bigger weight (up to the full pool), so admitting it
    leaves too little free weight for another large one until it finishes.

    FAIRNESS (2026-08-06): a whole-pool request (weight == max_slots) needs every slot
    free AT THE SAME INSTANT — the atomic all-or-nothing retry above can never see that
    if smaller requests keep re-filling slots as they free up. Predicted, then observed
    live: a real weight-4 repro request sat queued through several minutes of continuous
    weight-1/2 traffic, never once seeing all 4 free simultaneously. A bounded wait that
    can end in starvation is a correctness bug, not a queue — "retry the 429" just
    re-enters the same losing race, forever, for exactly the large-document population
    the backlog needs drained.
    Fix is a two-phase DRAIN, not a priority queue (no ticket bookkeeping needed — one
    marker file does it): once a whole-pool request has failed the normal atomic attempt
    for APITOOLS_SLOT_FAIRNESS_GRACE_S, it (a) becomes the exclusive drain holder for
    *kind* (an flock — if another whole-pool request got there first, this one queues
    FIFO-ish on the kernel's own wait list, so at most one drain is ever in flight), then
    (b) writes a lockout marker every callers of ANY weight check before attempting a
    slot. Small requests that see a fresh marker back off without touching a slot — they
    are not evicted, only new admissions stop — so the pool can only monotonically drain
    as already-running requests finish, each bounded by GUNICORN_TIMEOUT. Once it drains
    to `weight` free slots the holder acquires them (the same atomic routine, now
    uncontested) and immediately clears the marker + releases the drain lock, so normal
    four-wide admission resumes right away — the lockout's duration is only the drain
    itself, not the large document's full processing time.

    ── WAITING IS THE EXPENSIVE PART (2026-08-06/07, two live failures, both measured) ──────

    ``worker_class = "sync"``: one request owns one gunicorn worker for its whole lifetime,
    *including* every second it spends asleep in the poll loop below. So the wait, not the
    work, is what decides whether unrelated endpoints stay answerable.

    FAILURE 1 — unbounded waiting starved the cheap path. With GUNICORN_WORKERS=6 and 4 slots,
    peak concurrent served requests pegged at 6, of which 5 were /documentOcr (4 computing +
    >=1 asleep here). /documentOcr took 89.9 % of all worker-seconds (51 505 s of 57 309 s over
    4.75 h); /docExists took 0.2 % (114 s) yet sat unaccepted in gunicorn's FIFO backlog for a
    p50 of 13.9 s — a 33 ms lookup — and n8n's 15 s node timeout aborted it 375 times with
    "The connection was aborted, perhaps the server is offline". Nothing was offline and
    nothing was slow to serve; those requests never reached a worker.

    FAILURE 2 — my first fix added a SECOND pool ("worker budget", N requests) in front of this
    one, and that regressed throughput badly enough to look like a new bug. The two pools count
    different currencies: budget counts REQUESTS, slots count WEIGHT. With budget 4 and real
    traffic at weight 2, four requests took all four budget tokens but only two could hold
    slots — the other two sat here for up to APITOOLS_SLOT_WAIT_TIMEOUT (600 s) holding a
    budget token and doing nothing, so every later request was shed instantly on a server that
    was half idle. Caught live at 02:06: /proc showed pid 5376 and 5478 holding 2 slots each and
    working, while pids 4571 and 5526 held the remaining budget tokens with NO slots at all —
    4 385 429s against 694 successes, and only 226 real OCRs in 187 minutes (1.2/min).

    The lesson from both: do not add a second gate, remove the waiting. The weighted slot pool
    ALREADY bounds worker occupancy — a running OCR holds >=1 weight unit, so at most
    ``max_slots`` requests can be running — and it is the only correct accounting because it is
    the one that knows about weight. Callers therefore pass ``wait_timeout=0`` (one atomic
    attempt, then 429) and only whole-pool requests keep the long wait plus the drain.

    ``wait_timeout``: None -> APITOOLS_SLOT_WAIT_TIMEOUT (env, default 600 s, 0 = forever);
    a number -> exactly that many seconds, where 0 means a single non-blocking attempt.
    """
    weight = max(1, min(weight, max(1, max_slots)))
    if max_slots <= 0:
        yield True
        return

    lock_dir = os.getenv("APITOOLS_CONCURRENCY_LOCK_DIR", "/tmp/apitools-locks")
    os.makedirs(lock_dir, exist_ok=True)

    if wait_timeout is None:
        wait_timeout = float(os.getenv("APITOOLS_SLOT_WAIT_TIMEOUT", "600"))
        # env semantics, preserved: 0 means "wait forever (bounded by the worker timeout)"
        deadline = (time.monotonic() + wait_timeout) if wait_timeout > 0 else None
    else:
        # explicit caller budget, including 0 == exactly one non-blocking attempt
        deadline = time.monotonic() + max(0.0, float(wait_timeout))
    poll_s = 0.1  # poll interval in seconds

    fairness_grace_s = float(os.getenv("APITOOLS_SLOT_FAIRNESS_GRACE_S", "20"))
    lockout_ttl_s = float(os.getenv("APITOOLS_SLOT_LOCKOUT_TTL_S", "120"))
    is_whole_pool = weight >= max_slots
    wait_start = time.monotonic()
    drain_fd = None  # held only by whichever request is actively draining, if any

    def _try_attempt() -> list:
        """One non-blocking pass: try to grab `weight` slots; return what was acquired
        (possibly fewer than weight — caller decides whether to keep or release them)."""
        got = []
        for slot_index in range(max_slots):
            if len(got) >= weight:
                break
            lock_path = os.path.join(lock_dir, f"{kind}.{slot_index}.lock")
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o666)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                got.append(fd)
            except BlockingIOError:
                os.close(fd)
        return got

    acquired_fds = []
    waited = False
    try:
        while len(acquired_fds) < weight:
            # A small request defers entirely while another request is draining the
            # pool — it never even attempts a slot, so it can't keep re-winning the
            # race against the draining large one.
            if not is_whole_pool and _lockout_active(lock_dir, kind, lockout_ttl_s):
                if deadline is not None and time.monotonic() >= deadline:
                    break
                if not waited:
                    logger.info(f"{kind}: deferring to an in-progress whole-pool drain")
                    waited = True
                time.sleep(poll_s)
                continue

            acquired_fds = _try_attempt()
            if len(acquired_fds) >= weight:
                break

            for fd in acquired_fds:  # partial acquire — release and retry as a whole
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            acquired_fds = []

            if deadline is not None and time.monotonic() >= deadline:
                break  # timed out — yield False so caller returns 429

            if not waited:
                logger.info(f"Not enough {kind} slot(s) free for weight={weight} "
                            f"(of {max_slots} total); queuing request")
                waited = True

            # Past the grace period, a whole-pool request stops retry-and-release and
            # starts draining: become the exclusive drain holder and announce it so small
            # requests stop being admitted.
            #
            # NON-BLOCKING (changed 2026-08-07). This used to be a blocking LOCK_EX with the
            # comment "at most one drain in flight" — true of drains, but NOT of workers: a
            # second whole-pool request blocked here on the kernel's wait list while still
            # owning its gunicorn worker, for as long as the first drain took. That is the
            # same "asleep but holding a worker" shape that caused both of today's incidents.
            # Now a loser simply does not drain: it keeps retrying normally and times out into
            # a 429, so whole-pool requests borrow at most ONE worker between them.
            if is_whole_pool and drain_fd is None \
                    and (time.monotonic() - wait_start) >= fairness_grace_s:
                drain_path = os.path.join(lock_dir, f"{kind}.drain_holder.lock")
                candidate = os.open(drain_path, os.O_CREAT | os.O_RDWR, 0o666)
                try:
                    fcntl.flock(candidate, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(candidate)  # another drain owns the pool; don't queue behind it
                else:
                    drain_fd = candidate
                    logger.warning(f"{kind}: weight={weight} waited {fairness_grace_s:.0f}s+, "
                                   f"draining the pool for fair acquisition")
            if drain_fd is not None:
                marker = _lockout_path(lock_dir, kind)
                with open(marker, 'w') as _f:
                    _f.write(str(time.time()))
                os.utime(marker, None)  # refresh mtime each pass so the TTL never lapses mid-drain

            time.sleep(poll_s)

        yield len(acquired_fds) >= weight
    finally:
        for fd in acquired_fds:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        if drain_fd is not None:
            try:
                os.remove(_lockout_path(lock_dir, kind))
            except FileNotFoundError:
                pass
            fcntl.flock(drain_fd, fcntl.LOCK_UN)
            os.close(drain_fd)


def _busy_response(kind: str, max_slots: int):
    return {
        "error": "server_busy",
        "message": f"Too many concurrent {kind} requests; try again shortly",
        "max_concurrent": max_slots,
    }, 429


#  Get file from request, save it, process OCR, return file_hash, ocr_json if requested
def get_document_ocr(request: Request):
    """Parse the upload BEFORE contending for an OCR slot, then guard only the expensive
    OCR call itself.

    Previously the multipart body was read (`request.files`) *inside* the slot-guarded
    section, so a client that gave up while queued (queue wait doesn't count against any
    deadline — see documentJsonQuery's soft-timeout finding, same shape here) would have
    its abandoned socket read attempted only once a slot finally freed, deep inside
    werkzeug's form parser: `ConnectionResetError` -> `ClientDisconnected`, logged as an
    unhandled 500 with a full traceback for what is actually a client that left. Splitting
    the read out means: (1) a disconnect is caught once, cleanly, at low log severity,
    before any slot is touched, and (2) an abandoned upload never occupies a bulkhead slot
    waiting to be read — the slot is only held for the OCR computation itself.
    """
    try:
        parsed = _parse_document_ocr_upload(request)
    except ClientDisconnected as e:
        # The client is gone; nothing we return will be received. Log it as what it is
        # (an abandoned request, not a server fault) and stop — no slot was ever touched.
        logger.warning(f"documentOcr: client disconnected during upload: {e}")
        return jsonify({"error": "client_disconnected",
                        "message": "Client closed the connection while uploading"}), 499
    # A 2-tuple is a validation failure (error_body, status) to return as-is; the success
    # shape is a distinct 4-tuple, so length (not just `isinstance(..., tuple)`, which both
    # shapes satisfy) is what disambiguates them.
    if len(parsed) == 2:
        return parsed
    file_content, filename, file_type, file_extension = parsed

    # CACHE-HIT FAST PATH — admission control exists to ration OCR *computation*, and a
    # document whose OCR is already cached performs none. Measured over 4.75 h live:
    # 1 164 of 1 633 successful /documentOcr responses came back in under 1 s, i.e. ~71 % of
    # this endpoint's traffic is cache hits that hold an OCR slot for a few hundred
    # milliseconds while contributing nothing to the load the slots exist to bound. Once
    # admission started shedding rather than queueing, that became actively harmful: a
    # document that needed no OCR at all was being refused because slow strangers held the pool.
    # `from_file_id` is the same pure cache read /docExists uses — it raises on a miss and can
    # never trigger OCR — so a hit is safe to serve outside admission control entirely.
    # A hit that is evicted between this probe and the read below would fall through to a real
    # OCR outside the bulkhead; there is no eviction path in this codebase today, and the
    # window is microseconds, so that is accepted rather than double-locked.
    use_cache = str(request.args.get("cache", "true")).lower() not in ("0", "false", "no", "n")
    if use_cache and not request.args.get("ocr_engine"):
        try:
            OcrObject.from_file_id(hashlib.md5(file_content).hexdigest())
        except OcrCacheUnavailable:
            # NOT a cache miss — the SHARED cache is unreachable. "Take the normal path"
            # here would burn an admission slot and a Google Vision call on a result that
            # cannot be persisted anywhere the rest of the estate can see. Fail fast; the
            # API layer turns this into a 503 and haproxy retries the peer instance.
            raise
        except Exception:  # noqa: BLE001 — any miss/error just means "take the normal path"
            pass
        else:
            logger.debug("documentOcr: OCR already cached; bypassing admission control")
            return _get_document_ocr(request, file_content, filename, file_type, file_extension)

    # default derives from the machine (cores-1, memory-clamped) — see autoscale.py
    max_ocr_slots = int(os.getenv("APITOOLS_MAX_CONCURRENT_OCR") or autoscale.ocr_slots_default())
    weight = _ocr_admission_weight(file_content, file_type, max_ocr_slots)

    # HOW LONG THIS REQUEST MAY OCCUPY A WORKER BEFORE IT HAS A SLOT. This is the whole
    # admission story, and it is the number that has been wrong twice today — see the
    # "WAITING IS THE EXPENSIVE PART" section of _expensive_request_slot for both failures.
    #
    # Slots are WEIGHTED and the pool is the same size as the worker headroom, so the slot
    # pool alone already bounds worker occupancy: every *running* OCR holds at least one of
    # max_ocr_slots weight units, so at most max_ocr_slots requests can be running, leaving
    # GUNICORN_WORKERS - max_ocr_slots workers free for the cheap endpoints. The only thing
    # that ever broke that bound was a request sleeping in the queue while holding a worker.
    # So: normal requests do not wait at all — one atomic attempt, then shed.
    #
    # A WHOLE-POOL request (weight == max_slots, a very large document) is the one exception:
    # it can never win a single uncontested attempt while any other OCR runs, so refusing to
    # let it wait would shed exactly the population the drain mechanism below exists to
    # rescue. It keeps the full wait, and at most one of them can be in flight (the drain
    # holder lock is now non-blocking), so it borrows at most one worker.
    if weight >= max_ocr_slots:
        ocr_slot_wait_s = None  # whole-pool: keep APITOOLS_SLOT_WAIT_TIMEOUT + the drain
    else:
        ocr_slot_wait_s = float(os.getenv("APITOOLS_OCR_SLOT_WAIT_S") or 0)

    with _expensive_request_slot("document_ocr", max_ocr_slots, weight=weight,
                                 wait_timeout=ocr_slot_wait_s) as acquired:
        if not acquired:
            return _busy_response("document OCR", max_ocr_slots)
        return _get_document_ocr(request, file_content, filename, file_type, file_extension)


# RENDERED-MEGAPIXEL-AWARE ADMISSION (2026-08-06, revised same day). History matters here:
#
# v1 weighted PDFs by PAGE COUNT. Checked against a live OOM episode's actual reproducers
# (two "ordinary 2-3 page scans" per how they were filed) and found page count is a bad
# proxy: their MediaBox is 2479x3506pt (34.4x48.7in, not A4) — at 300dpi that is
# 10329x14608px = 150.9MP PER PAGE, ~453MB decoded before any derived copy. A 3-page
# document at a sane page size can cost far less than this 1-page-equivalent. The real
# predictor is RENDERED megapixels (page-rect-area x dpi^2), not page count and not file
# bytes — confirmed by pdf_to_jpg.py's MAX_MP_PER_PAGE clamp, added alongside this, which
# caps the render itself at the source.
#
# v1 also only weighted PDFs ("non-PDFs are always weight 1"), on the assumption that one
# image is one raster, not N independently-recovered pages — true but incomplete: a live
# routing-log census during the SAME OOM episode showed traffic was 100% `image_ocr`
# (WhatsApp JPEGs) in one window and the actual kill-correlated calls were `paged_ocr` in
# another — both routes needed covering, and both are now scored the SAME way: rendered
# megapixels, whether that comes from one image's native pixels or a PDF page's
# (rect x dpi^2). One scale, one set of tiers, for both routes.
#
# <= MEDIUM_MP: weight 1 (four such documents run four-wide). <= LARGE_MP: weight 2 (at
# most two concurrent). Beyond that: the WHOLE pool — runs alone. APITOOLS_MAX_CONCURRENT_OCR
# stays exactly as tuned; this only decides how many of its slots one request must hold.
_OCR_WEIGHT_MEDIUM_MP = float(os.getenv("APITOOLS_OCR_WEIGHT_MEDIUM_MP", "6"))
_OCR_WEIGHT_LARGE_MP = float(os.getenv("APITOOLS_OCR_WEIGHT_LARGE_MP", "16"))


def _ocr_admission_weight(file_content: bytes, file_type: str, max_slots: int) -> int:
    """Return how many of the OCR bulkhead's slots this upload must hold at once, scored
    on RENDERED megapixels for both routes — an image's native pixel count, or a PDF
    page's (rect-area-in-inches x effective-dpi^2), whichever this document will actually
    ask the OCR engine to decode. <= _OCR_WEIGHT_MEDIUM_MP: weight 1. <= _OCR_WEIGHT_LARGE_MP:
    weight 2. Beyond: the whole pool."""
    if file_type != 'application/pdf':
        try:
            from PIL import Image
            import io as _io
            with Image.open(_io.BytesIO(file_content)) as im:
                mp = (im.width * im.height) / 1_000_000.0
        except Exception as e:  # noqa: BLE001 — never let a size probe block admission
            logger.warning(f"documentOcr: image-size probe failed, admitting at weight 1: {e}")
            return 1
    else:
        try:
            import fitz
            from src.pdf_core.pdf_to_jpg import PDF_OCR_DPI, _effective_dpi_for_page
            with fitz.open(stream=file_content, filetype='pdf') as d:
                # Born-digital PDFs skip the OCR raster path entirely (pdf_textlayer.py)
                # and read fast regardless of page size — weighting them like a scanned
                # document would waste pool capacity on requests that never hold it long.
                # Mirrors the exact check ocr_processor.get_ocr() makes; cheap (text len).
                if os.getenv("APITOOLS_BORN_DIGITAL", "1") == "1":
                    has_text = sum(len((p.get_text() or '').strip()) for p in d) >= 40
                    if has_text:
                        return 1
                max_w_pt = max((p.rect.width for p in d), default=595.0)
                max_h_pt = max((p.rect.height for p in d), default=842.0)
            # Use the SAME clamp pdf_pages_to_jpeg_bytes will actually render at — an
            # oversized MediaBox is now capped at the source (MAX_MP_PER_PAGE), so weight
            # reflects what will really be decoded, not the pre-clamp nominal figure.
            eff_dpi = _effective_dpi_for_page(max_w_pt, max_h_pt, PDF_OCR_DPI)
            mp = (max_w_pt / 72.0 * eff_dpi) * (max_h_pt / 72.0 * eff_dpi) / 1_000_000.0
        except Exception as e:  # noqa: BLE001 — never let a size probe block admission
            logger.warning(f"documentOcr: page-size probe failed, admitting at weight 1: {e}")
            return 1
    if mp <= _OCR_WEIGHT_MEDIUM_MP:
        return 1
    if mp <= _OCR_WEIGHT_LARGE_MP:
        return 2
    return max(1, max_slots)


def _parse_document_ocr_upload(request: Request):
    """Read and validate the multipart upload. Returns either
    (file_content, filename, file_type, file_extension) on success, or a (body, status)
    tuple to return as-is on a validation failure. Raises ClientDisconnected if the
    client goes away mid-upload (werkzeug's own exception for exactly this)."""
    logger.debug(f"Files in request: {list(request.files.keys())}")
    if 'file' not in request.files:
        return "No file part", 400

    file = request.files['file']
    file_type = file.content_type

    if "." in (file.filename or ""):
        file_extension = file.filename.rsplit(".", 1)[-1]
    else:
        mime_to_ext = {
            "image/jpeg": "jpeg",
            "image/png": "png",
            "application/pdf": "pdf",
        }
        file_extension = mime_to_ext.get(file_type, "bin")

    # SNIFF THE BYTES, DON'T TRUST THE DECLARED MIME (2026-08-10). This gate used to reject
    # on `file.content_type` alone. The uploader is n8n forwarding whatever Content-Type the
    # drive service put on the download, and for a large share of real documents that is the
    # generic `application/octet-stream` -- so perfectly good PDFs were refused. MEASURED: in
    # one hour, 190 of 230 `Upload Doc To API TOOLS` failures were this message, and they came
    # from only 16 distinct documents, each re-dispatched up to 67 times (RETRY_COUNT reached
    # 657 on one) -- a permanent rejection that the pipeline retried forever, burning an OCR
    # call, a worker slot and an errorHandler01 run every time. The bytes are already in hand
    # and are authoritative, so read them and decide on content.
    #
    # Only the DECLARED type was ever unreliable; the set of things we can actually OCR is
    # unchanged (PDF/JPEG/PNG). A genuine spreadsheet still gets refused -- it just gets
    # refused because its bytes are not a document we can read, not because a proxy relabelled it.
    file_content = file.read()
    sniffed = _sniff_document_type(file_content)

    if file_type not in ('image/jpeg', 'image/png', 'application/pdf'):
        if sniffed is None:
            # Genuinely unsupported. Say so in a way the caller can act on WITHOUT retrying:
            # this is a property of the file and will never change on a later attempt.
            return {
                "error": f"File type not allowed: {file_type} "
                         f"(sniffed content is not PDF/JPEG/PNG either)",
                "reason": "unsupported_file_type",
                "retryable": False,
            }, 200
        sniffed_type, sniffed_ext = sniffed
        logger.info(
            "documentOcr: declared type %s is not supported, but content sniffs as %s; "
            "accepting on content (filename=%s)", file_type, sniffed_type, file.filename)
        file_type = sniffed_type
        file_extension = sniffed_ext

    return file_content, file.filename, file_type, file_extension


# Magic-number prefixes for exactly the three formats the OCR path can read. Kept tiny and
# dependency-free on purpose: this runs on every upload, before admission control.
_DOCUMENT_MAGIC = (
    (b"%PDF", "application/pdf", "pdf"),
    (b"\xff\xd8\xff", "image/jpeg", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
)


def _sniff_document_type(file_content: bytes):
    """Return (mime, extension) if the bytes are a PDF/JPEG/PNG, else None."""
    for magic, mime, ext in _DOCUMENT_MAGIC:
        if file_content.startswith(magic):
            return mime, ext
    return None


# RECONSTRUCTED 2026-08-06, FLAGGED FOR VERIFICATION BY THE OWNING LANE — full account:
# this field was reported live (by the coordinator relaying the A5/garbage-detection lane)
# as added to this file at 16:26:46Z, rebuilt and CONFIRMED WORKING TWICE this session
# (grep count 3 in the built image, and a live /documentJsonQuery call returning a real
# int). It was then found ABSENT — grep count 0, source and build both — after further
# edits to THIS file (the admission-weight unification and the fairness/drain mechanism
# below). I cannot confirm which edit removed it: both were surgical Edit-tool string
# replacements scoped to unrelated functions (_ocr_admission_weight, _expensive_request_
# slot), which should not have touched this code, and this feature was never committed
# (no git diff exists to compare against) — so I can't rule out a concurrent write from
# another lane either. Rather than leave it silently absent (an A5 garbage-detection rule
# depends on it existing at all — "unknown count never garbages a document" is the safe
# default, but SILENTLY missing is not the same as DELIBERATELY absent) I reconstructed it
# from the coordinator's own description: "word count computed from OCR text already in
# memory (no extra OCR call)". Uses fullTextAnnotation.text.split() — the plainest reading
# of "word count from OCR text". THE OWNING LANE MUST VERIFY this matches their original
# semantics (e.g. whether punctuation-only tokens, bidi marks, or specific engines' output
# should be filtered before counting) before trusting it for a TERMINAL, never-re-OCR'd
# classification — a wrong count here doesn't fail loud, it silently misfiles a document.
def _ocr_n_words(ocr_json: dict):
    try:
        text = (ocr_json.get('fullTextAnnotation') or {}).get('text') or ''
        return len(text.split())
    except Exception:  # noqa: BLE001 — never let this field break the response
        return None


def _get_document_ocr(request: Request, file_content: bytes, filename: str, file_type: str, file_extension: str):
    response = {}
    response["file_name"] = filename
    response["file_type"] = file_type
    response["file_extension"] = file_extension
    logger.debug(f"Processing file: {filename}")

    file_hash = hashlib.md5(file_content).hexdigest()
    filepath = save_file(f"{file_hash}.{file_extension}", file_content)
    response["filepath"] = filepath
    response["file_hash"] = file_hash

    # Allow bypassing OCR cache via ?cache=false
    use_cache = str(request.args.get("cache", "true")).lower() not in ("0", "false", "no", "n")

    # Allow overriding OCR engine per request via ?ocr_engine=local|google
    # When engine is explicitly selected, disable cache to force re-OCR
    ocr_engine = request.args.get("ocr_engine") or None
    if ocr_engine:
        use_cache = False

    try:
        ocr = OcrObject.from_file_path(filepath, cache=use_cache, ocr_engine=ocr_engine)
        ocr_json = ocr.ocr_data.ocr_dict
        # Provenance comes FROM the ocr_json itself (stamped at OCR time and
        # persisted in ocr_cache) — a cache hit reports the engine/build/duration
        # that ORIGINALLY produced this OCR, not whatever runs now. Only
        # apitools_version reflects the build answering this request.
        response["ocr_ms"] = ocr_json.get("ocr_ms")
        response["ocr_at"] = ocr_json.get("ocr_at")
        response["ocr_engine"] = ocr_json.get("ocr_engine", "unknown")
        response["ocr_apitools_version"] = ocr_json.get("apitools_version")
        response["apitools_version"] = APITOOLS_VERSION
        # RESTORED 2026-08-06 (see ocr_n_words note further down near _perform_ocr_json_query
        # for the full account — found MISSING from this file mid-session, could not confirm
        # cause, reconstructed rather than left absent).
        response["ocr_n_words"] = _ocr_n_words(ocr_json)

        if not request.args.get("dont_return_ocr"):
            response["ocr_json"] = ocr_json

    except ValueError as e:
        response["error"] = f"Error processing OCR: {e}"
        return response

    return response


#  Get file hash from request, get ocr_json_query from request, return result of ocr_json_query
def perform_ocr_json_query(request: Request):
    response = {}
    # default derives from the machine (cores+2) — see autoscale.py
    max_query_slots = int(os.getenv("APITOOLS_MAX_CONCURRENT_JSON_QUERY") or autoscale.json_slots_default())
    with _expensive_request_slot("document_json_query", max_query_slots) as acquired:
        if not acquired:
            return _busy_response("document JSON query", max_query_slots)
        # BATCH FORM (`ocr_json_queries`) vs SINGLE (`ocr_json_query`) — see
        # _perform_ocr_json_query_batch. Both take exactly ONE slot; the batch simply
        # does more useful work inside it.
        body = request.get_json(silent=True) or {}
        if body.get("ocr_json_queries") is not None:
            return _perform_ocr_json_query_batch(request, response, body)
        return _perform_ocr_json_query(request, response)


# ── BATCHED EXTRACTION (2026-08-10) ──────────────────────────────────────────────
#
# WHY THIS EXISTS, MEASURED — the extractor workflows (`DocBase JQ Ex V3` and its
# per-type siblings) fan out ONE HTTP call per (document, field): 3 for `base`, 5 for
# `invoice`, 4 for `shipment`, 2 for `bs`, 1 for `order`. Every one of those calls
# re-entered `OcrObject.from_file_id`, which builds a FRESH OcrQuery — and OcrQuery
# carries the two per-document memos that make this engine affordable:
# `_text_match_memo` and the `annotations_aligned_with_annotation` geometry memo.
# Rebuilding the object per field threw both away between fields.
#
# That geometry memo is not a micro-optimisation. In-process cProfile over 6 real
# documents put 82 % of a `q_v3_type` call inside
# `find_texts_matching_annotations_via_alignment` (59.6 s of 72.3 s), which is 50 063
# `BoundingBox.check_alingment` calls — pure geometry over annotations that never
# change for the life of a document. Sharing one OcrObject across a document's fields
# lets every field after the first reuse that work.
#
# A/B MEASURED IN THIS CONTAINER, same queries, same documents, alternating order:
#   base    (3 fields): 9.36 s/doc -> 6.12 s/doc  = 34.6 % less CPU, 3 calls -> 1
#   invoice (5 fields): 9.43 s/doc -> 5.95 s/doc  = 36.9 % less CPU, 5 calls -> 1
#   results byte-identical on 16/16 documents (0 mismatches).
#
# DEADLINE SEMANTICS ARE DELIBERATELY UNCHANGED PER QUERY. Each query in the batch
# gets its own APITOOLS_QUERY_SOFT_TIMEOUT, exactly as it would have as a standalone
# request — collapsing N requests into one must not silently tighten any query's
# budget to 1/N. What IS new is a whole-batch ceiling
# (APITOOLS_BATCH_SOFT_TIMEOUT, default 240 s) kept safely under both GUNICORN_TIMEOUT
# (300 s) and the callers' own 300 s node timeout, so a pathological document cannot
# turn N bounded requests into one unbounded one. Queries not reached before the
# ceiling return `batch_budget_exhausted` rather than running.
#
# ONE SLOW/FAILING FIELD MUST NOT VOID THE DOCUMENT. Each query is isolated: a
# timeout or exception is recorded against that field and the batch continues, so a
# batch degrades exactly like the independent calls it replaces (per-field errors)
# instead of failing all-or-nothing.
def _perform_ocr_json_query_batch(request: Request, response: dict, request_json: dict):
    file_id = request_json.get("file_id")
    response["file_id"] = file_id
    if not file_id:
        response["error"] = "missing_file_id"
        response["message"] = "File ID is required"
        return response, 400
    set_request_context(file_id=file_id)

    batch = request_json.get("ocr_json_queries")
    if not isinstance(batch, list) or not batch:
        response["error"] = "missing_ocr_json_queries"
        response["message"] = "ocr_json_queries must be a non-empty array"
        return response, 400

    ocr_engine = request.args.get("ocr_engine") or request_json.get("ocr_engine") or None
    try:
        # THE POINT OF THE WHOLE ENDPOINT: built once, reused by every query below.
        ocr_object = OcrObject.from_file_id(file_id, ocr_engine=ocr_engine)
    except FileNotFoundError:
        response["error"] = "file_not_found"
        response["message"] = f"OCR results for file ID {file_id} not found"
        return response, 404

    draw_flag = str(request.args.get("draw", "false")).lower() in ("1", "true", "yes", "y")
    if draw_flag:
        ocr_object.query.draw = True

    query_timeout = int(os.getenv("APITOOLS_QUERY_SOFT_TIMEOUT", "180"))
    batch_budget = float(os.getenv("APITOOLS_BATCH_SOFT_TIMEOUT", "240"))
    _t_batch = time.perf_counter()

    results = []
    for entry in batch:
        # Accept both {"field": ..., "ocr_json_query": {...}} and a bare query object,
        # so a caller with no field labels still works.
        if isinstance(entry, dict) and "ocr_json_query" in entry:
            spec = entry.get("ocr_json_query")
            field = entry.get("field")
            match_index = entry.get("match_index", 0)
        else:
            spec = entry
            field = (entry or {}).get("field") if isinstance(entry, dict) else None
            match_index = (entry or {}).get("match_index", 0) if isinstance(entry, dict) else 0

        item = {"field": field}
        if not spec:
            item["error"] = "missing_ocr_json_query"
            results.append(item)
            continue

        spent = time.perf_counter() - _t_batch
        if batch_budget > 0 and spent >= batch_budget:
            item["error"] = "batch_budget_exhausted"
            item["message"] = f"batch exceeded {batch_budget:.0f}s before this query ran"
            results.append(item)
            continue

        # Per-query deadline, clamped by whatever remains of the batch ceiling so the
        # LAST query can never push the response past the worker timeout.
        per_query = query_timeout
        if batch_budget > 0:
            per_query = int(min(query_timeout, max(1, batch_budget - spent)))

        _t0 = time.perf_counter()
        try:
            with _request_deadline(per_query):
                item["result"] = ocr_object.json_query.json_query(spec, match_index=match_index)
        except QuerySoftTimeout as e:
            logger.warning(f"batch json query soft-timeout file_id={file_id} field={field}: {e}")
            item["error"] = "query_timeout"
            item["message"] = str(e)
        except Exception as e:  # noqa: BLE001 — one bad field must not void the document
            logger.error(f"batch json query failed file_id={file_id} field={field}: {e}", exc_info=True)
            item["error"] = "query_failed"
            item["message"] = str(e)[:300]
        item["elapsed_ms"] = int((time.perf_counter() - _t0) * 1000)
        results.append(item)

    response["results"] = results
    # Document-level provenance, reported ONCE instead of repeated per field. Same
    # fields the single-query response carries, read from the same ocr_json.
    _od = ocr_object.ocr_data.ocr_dict
    response["ocr_engine"] = _od.get("ocr_engine", "unknown")
    response["ocr_ms"] = _od.get("ocr_ms")
    response["ocr_at"] = _od.get("ocr_at")
    response["ocr_apitools_version"] = _od.get("apitools_version")
    response["ocr_n_words"] = _ocr_n_words(_od)
    response["elapsed_ms"] = int((time.perf_counter() - _t_batch) * 1000)
    response["apitools_version"] = APITOOLS_VERSION
    response["n_queries"] = len(results)

    if draw_flag:
        try:
            ocr_object.drawing.save_drawing_image()
            response["drawing_path"] = os.path.abspath(ocr_object.drawing.drawing_image_path)
        except Exception as e:  # noqa: BLE001 — drawing is a debug aid, never fatal
            response["drawing_error"] = f"Failed to save drawing: {e}"
    return response


def _perform_ocr_json_query(request: Request, response: dict):

    # request type should be POST, json
    request_json = request.json
    logger.debug(f"JSON query request received")
    if not request_json:
        response["error"] = "missing_json_request"
        response["message"] = "Request should be JSON"
        return response, 400

    #  get filehash from request
    file_id = request_json.get("file_id")
    response["file_id"] = file_id
    if file_id:
        set_request_context(file_id=file_id)
        logger.debug(f"Processing query for file_id: {file_id}")

    if not file_id:
        response["error"] = "missing_file_id"
        response["message"] = "File ID is required"
        return response, 400

    ocr_json_query: dict = request_json.get("ocr_json_query")
    response["ocr_json_query"] = ocr_json_query
    logger.debug(f"OCR query action: {ocr_json_query.get('action') if ocr_json_query else 'N/A'}")

    if not ocr_json_query:
        response["error"] = "missing_ocr_json_query"
        response["message"] = "OCR JSON query is required e.g: ocr_json_query"
        return response, 400

    # Allow overriding OCR engine per request via query param or JSON body
    ocr_engine = request.args.get("ocr_engine") or request_json.get("ocr_engine") or None

    try:
        ocr_object = OcrObject.from_file_id(file_id, ocr_engine=ocr_engine)
    except FileNotFoundError:
        response["error"] = "file_not_found"
        response["message"] = f"OCR results for file ID {file_id} not found"
        return response, 404

    match_index = request_json.get("match_index", 0)
    # Enable drawing overlay when requested via query args (?draw=true)
    draw_flag = str(request.args.get("draw", "false")).lower() in ("1", "true", "yes", "y")
    if draw_flag:
        # Turn on drawing in the underlying query engine
        ocr_object.query.draw = True

    # Default aligned with docker-compose.yml (180). These two were 75 vs 45 -- two sources of truth
    # for the same deadline, so the effective value depended on whether compose supplied the env.
    query_timeout = int(os.getenv("APITOOLS_QUERY_SOFT_TIMEOUT", "180"))
    _t0 = time.perf_counter()

    # DIAGNOSTIC, OFF BY DEFAULT: this is what root-caused the documentJsonQuery 504 class
    # (2026-08-06 — found the "find option" call sending 2,383 identifiers per query; see
    # ocr_query.py). Left in place rather than deleted because the same instrument will be
    # needed the next time something in this call graph goes quiet-slow, but it must not cost
    # anything on a healthy box: 0 (default) skips cProfile entirely, not even instantiated.
    # Set APITOOLS_PROFILE_SLOW_MS=3000 (or any ms threshold) to re-arm it; calls under the
    # threshold still pay nothing (the check happens after enable(), but enable() itself has
    # measurable per-call overhead — that's the cost of turning this on, not of leaving it off).
    _profile_slow_ms = int(os.getenv("APITOOLS_PROFILE_SLOW_MS", "0"))
    _prof = None
    if _profile_slow_ms > 0:
        import cProfile
        _prof = cProfile.Profile()
        _prof.enable()

    def _log_slow_profile(tag: str, elapsed_s: float):
        if _prof is None:
            return
        _prof.disable()
        if elapsed_s * 1000 < _profile_slow_ms:
            return
        import pstats, io as _io
        buf = _io.StringIO()
        try:
            ps = pstats.Stats(_prof, stream=buf).sort_stats('cumulative')
            ps.print_stats(15)
        except Exception as pe:  # noqa: BLE001 — diagnostics must never break the request
            buf.write(f"(profile dump failed: {pe})")
        anns = ocr_object.ocr_data.ocr_dict.get('textAnnotations', [])
        ft_len = len(ocr_object.ocr_data.full_text or '')
        logger.warning(
            f"SLOW json_query profile [{tag}] file_id={file_id} elapsed={elapsed_s:.1f}s "
            f"n_annotations={len(anns)} fulltext_len={ft_len} "
            f"action={ocr_json_query.get('action')} action_value={str(ocr_json_query.get('action_value'))[:200]} "
            f"value_validations={ocr_json_query.get('value_validations')} "
            f"n_fallbacks={len(ocr_json_query.get('fallbacks') or [])}\n{buf.getvalue()}"
        )

    try:
        with _request_deadline(query_timeout):
            result = ocr_object.json_query.json_query(ocr_json_query, match_index=match_index)
    except QuerySoftTimeout as e:
        _log_slow_profile("TIMED_OUT", time.perf_counter() - _t0)
        logger.warning(f"JSON query soft-timeout for file_id={file_id}: {e}")
        response["error"] = "query_timeout"
        response["message"] = str(e)
        return response, 504
    _log_slow_profile("COMPLETED", time.perf_counter() - _t0)

    response["result"] = result
    # OCR provenance from the ocr_json itself (stamped at OCR time, survives the
    # cache) + per-call provenance: duration of THIS query and the build running it.
    # The extractor forwards these per field, so the UI can show where each value's
    # time went and which engine/build read the document.
    _od = ocr_object.ocr_data.ocr_dict
    response["ocr_engine"] = _od.get("ocr_engine", "unknown")
    response["ocr_ms"] = _od.get("ocr_ms")
    response["ocr_at"] = _od.get("ocr_at")
    response["ocr_apitools_version"] = _od.get("apitools_version")
    response["ocr_n_words"] = _ocr_n_words(_od)  # see _ocr_n_words docstring — reconstructed
    response["elapsed_ms"] = int((time.perf_counter() - _t0) * 1000)
    response["apitools_version"] = APITOOLS_VERSION
    logger.debug(f"Query completed, result type: {type(result).__name__}")

    # If drawing requested, persist and expose drawing path
    if draw_flag:
        try:
            # ensure latest buffer is written and return absolute path for serving
            ocr_object.drawing.save_drawing_image()
            response["drawing_path"] = os.path.abspath(ocr_object.drawing.drawing_image_path)
        except Exception as e:
            # Non-fatal: still return JSON result
            response["drawing_error"] = f"Failed to save drawing: {e}"
    return response


def document_exists(request: Request):
    """Check if a document already exists by file hash.

    Expected JSON body: {"file_id": "<md5 hash>"}
    Returns: {"file_id": str, "exists": bool, "file_path": str|None}
    """
    resp = {}
    request_json = request.get_json(silent=True) or {}
    file_id = request_json.get("file_id") or request.args.get("file_id")
    resp["file_id"] = file_id
    if not file_id:
        resp["error"] = "file_id is required"
        return resp, 400

    # Look for any file whose name starts with the hash and a dot (hash.ext)
    existing_path = None
    try:
        ocr_file = OcrObject.from_file_id(file_id)
        logger.debug(f"OCR file found for file_id: {file_id}")
        existing_path = ocr_file.ocr_data.original_filepath
    except FileNotFoundError as e:
        # If storage not initialized yet
        logger.debug(f"File not found, file_id: {file_id}")
        pass

    logger.debug(f"Document exists check: {existing_path is not None}")
    resp["exists"] = existing_path is not None
    if existing_path:
        resp["file_path"] = existing_path
    return resp, 200


def check_document_ocr():
    filename = f"{pdf_test_files_path()}/a-kalkal.pdf"
    # filename = f"{ocr_test_files_path()}/file68.jpg"
    with open(filename, "rb") as f:
        file_content = f.read()
        file_binary = BytesIO(file_content)
    app = flask.Flask(__name__)
    envbuilder = EnvironBuilder(
        app=app,
        path='/hello',
        method='POST',
        data={'file': (file_binary, filename)},
        content_type='multipart/form-data'
    )
    request = Request(envbuilder.get_environ())

    response = get_document_ocr(request)
    print(f"Response keys: {list(response.keys())}")
    print(f"File Name: {response.get('file_name')}")
    print(f"File Type: {response.get('file_type')}")
    print(f"File Extension: {response.get('file_extension')}")
    print(f"File Path: {response.get('filepath')}")
    print(f"File Hash: {response.get('file_hash')}")
    print(f"OCR JSON: {response.get('ocr_json')}")

    return response.get('file_hash')


def check_ocr_json_query(file_id):
    app = flask.Flask(__name__)
    envbuilder = EnvironBuilder(
        app=app,
        path='/',
        method='POST',
        json={
            "file_id": file_id,
            # "match_index": -1,
            "ocr_json_query": {
                "action": "find after",
                "action_value": "תעודה",
                "value_validations": [
                    {
                        "validation_type": "length_greater_than",
                        "validation_value": 2
                    },
                    {
                        "validation_type": "length_less_than",
                        "validation_value": 20
                    },
                    {
                        "validation_type": "has_number"
                    },
                    {
                        "validation_type": "not_ends_with",
                        "validation_value": "256005542"
                    }
                    
                ],
                "is_rtl": True
            }
        }
    )
    request = Request(envbuilder.get_environ())

    response = perform_ocr_json_query(request)
    print(f"Response keys: {list(response.keys())}")
    print(f"File ID: {response.get('file_id')}")
    print(f"OCR JSON Query: {response.get('ocr_json_query')}")
    print(f"Result: {response.get('result')}")


if __name__ == '__main__':
    file_id = check_document_ocr()
    input("Press Enter to continue...")

    check_ocr_json_query(file_id)
    input("Press Enter to continue...")
