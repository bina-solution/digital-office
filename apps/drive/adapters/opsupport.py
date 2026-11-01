"""adapters.opsupport — the bits every adapter's canonical ops (§3) need, and neither owns.

`extract_file_id` and `download_headers` encode driveApi01's wire conventions, not any one
provider's: a `fileId` may arrive as an id or a Drive URL, and a download's filename has to survive
the trip into n8n's binary manager. Both adapters answer the same ops, so they share these rather
than each keeping a copy that can drift.
"""
import re
from urllib.parse import quote


class AdapterError(Exception):
    """A resolution/op failure the UI can act on. `status` is what the route returns."""

    def __init__(self, message, status=502):
        super().__init__(message)
        self.message = message
        self.status = status


# n8n's resourceLocator url-mode regex for a Drive file (nodes/Google/constants.js), so a `LINK`
# that resolved before resolves to the same id now.
_URL_RE = re.compile(r"https://(?:drive|docs)\.google\.com(?:/.*|)/d/([0-9a-zA-Z\-_]+)(?:/.*|)")
# Lenient fallback (the retired driveApiLocal01 used it): only ever turns a hard failure into a
# resolution, never changes an id the strict regex already matched.
_ID_RE = re.compile(r"[-\w]{20,}")


def extract_file_id(value, mode="id"):
    """A fileId as driveApi01 passes it: `id`/`list` are literal, `url` is parsed (§3 params)."""
    v = str(value or "")
    if mode != "url":
        return v
    m = _URL_RE.search(v)
    if m:
        return m.group(1)
    m = _ID_RE.search(v)
    return m.group(0) if m else v


def download_headers(filename, mime, content_length=None):
    """Headers for a canonical `download`. The filename is the payload here, not decoration: n8n's
    HTTP Request node derives `binary.data.fileName` from Content-Disposition, and callers upload
    under `$binary.data.fileName`. Names are Hebrew, so send BOTH a sanitised ASCII `filename=` and
    the RFC 5987 `filename*=UTF-8''…` that carries the real one — a bare UTF-8 filename= is not
    parseable and would silently degrade the name to the file id.
    """
    name = str(filename or "")
    ascii_name = re.sub(r"[^\x20-\x7e]", "_", name).replace('"', "'") or "download"
    hdrs = {"Content-Type": mime or "application/octet-stream",
            "Content-Disposition": (f'attachment; filename="{ascii_name}"; '
                                    f"filename*=UTF-8''{quote(name, safe='')}")}
    if content_length:
        hdrs["Content-Length"] = content_length
    return hdrs
