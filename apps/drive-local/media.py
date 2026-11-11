"""media — what a file IS (its type) and how its bytes may be served.

Two questions every byte-serving route asks, answered once:

  * `mime_for(name, sent)` — the type the drive records. A client's `application/octet-stream`
    (n8n sends every attachment that way) is no answer, and Python's table alone does not know
    `.m4a`, `.heic`, `.mkv` or `.dwg`; the table below is the drive's own, consulted first.

  * `serve_headers(name, mime, disposition)` — headers for bytes that are SOMEONE'S FILE served from
    the drive's own origin. A user's .html or .svg rendered inline here runs its scripts with the
    viewer's session (the drive's origin is the console's, under /a/drive/). So only types a browser
    renders without running anything are allowed inline; everything else downloads, and every
    answer carries `nosniff` and a CSP that sandboxes the document whatever it turns out to be.
"""
import mimetypes
import re
from urllib.parse import quote

# extension → type, for the types the drive is expected to hold and Python's table misses or gets
# wrong. Lower-case, without the dot.
_TYPES = {
    # documents
    "pdf": "application/pdf", "txt": "text/plain", "md": "text/markdown", "rtf": "application/rtf",
    "doc": "application/msword", "odt": "application/vnd.oasis.opendocument.text",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "epub": "application/epub+zip", "pages": "application/vnd.apple.pages", "tex": "application/x-tex",
    # sheets and slides
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "xls": "application/vnd.ms-excel", "csv": "text/csv", "tsv": "text/tab-separated-values",
    "ods": "application/vnd.oasis.opendocument.spreadsheet", "numbers": "application/vnd.apple.numbers",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/vnd.ms-powerpoint", "odp": "application/vnd.oasis.opendocument.presentation",
    "key": "application/vnd.apple.keynote",
    # images
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "webp": "image/webp", "avif": "image/avif", "heic": "image/heic", "heif": "image/heif",
    "svg": "image/svg+xml", "bmp": "image/bmp", "tif": "image/tiff", "tiff": "image/tiff",
    "ico": "image/x-icon", "psd": "image/vnd.adobe.photoshop", "ai": "application/illustrator",
    "eps": "application/postscript", "raw": "image/x-raw", "cr2": "image/x-canon-cr2",
    "nef": "image/x-nikon-nef", "dng": "image/x-adobe-dng",
    # audio
    "mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "aac": "audio/aac",
    "m4a": "audio/mp4", "ogg": "audio/ogg", "oga": "audio/ogg", "opus": "audio/ogg",
    "weba": "audio/webm", "wma": "audio/x-ms-wma", "mid": "audio/midi", "midi": "audio/midi",
    # video
    "mp4": "video/mp4", "m4v": "video/mp4", "mov": "video/quicktime", "mkv": "video/x-matroska",
    "avi": "video/x-msvideo", "webm": "video/webm", "wmv": "video/x-ms-wmv", "flv": "video/x-flv",
    "srt": "application/x-subrip", "vtt": "text/vtt",
    # archives and images of disks
    "zip": "application/zip", "rar": "application/vnd.rar", "7z": "application/x-7z-compressed",
    "tar": "application/x-tar", "gz": "application/gzip", "tgz": "application/gzip",
    "iso": "application/x-iso9660-image", "dmg": "application/x-apple-diskimage",
    # programs
    "exe": "application/vnd.microsoft.portable-executable", "msi": "application/x-msi",
    "dll": "application/vnd.microsoft.portable-executable", "bat": "text/x-msdos-batch",
    "sh": "text/x-shellscript", "apk": "application/vnd.android.package-archive",
    "deb": "application/vnd.debian.binary-package", "app": "application/octet-stream",
    # web, data and code — served as text, highlighted by the page
    "html": "text/html", "htm": "text/html", "css": "text/css", "js": "text/javascript",
    "mjs": "text/javascript", "php": "text/x-php", "json": "application/json", "xml": "application/xml",
    "py": "text/x-python", "java": "text/x-java", "c": "text/x-c", "h": "text/x-c", "cpp": "text/x-c++",
    "hpp": "text/x-c++", "cs": "text/x-csharp", "ts": "text/x-typescript", "tsx": "text/x-typescript",
    "go": "text/x-go", "rs": "text/x-rust", "swift": "text/x-swift", "kt": "text/x-kotlin",
    "rb": "text/x-ruby", "sql": "application/sql", "ipynb": "application/x-ipynb+json",
    "yaml": "application/yaml", "yml": "application/yaml", "toml": "application/toml",
    "ini": "text/plain", "env": "text/plain", "log": "text/plain", "conf": "text/plain",
    "db": "application/vnd.sqlite3", "sqlite": "application/vnd.sqlite3", "sqlite3": "application/vnd.sqlite3",
    # fonts, 3D, cad and the rest
    "ttf": "font/ttf", "otf": "font/otf", "woff": "font/woff", "woff2": "font/woff2",
    "stl": "model/stl", "obj": "model/obj", "glb": "model/gltf-binary", "gltf": "model/gltf+json",
    "3mf": "model/3mf", "ply": "model/ply", "fbx": "application/octet-stream",
    "dwg": "image/vnd.dwg", "dxf": "image/vnd.dxf", "ics": "text/calendar", "vcf": "text/vcard",
    "eml": "message/rfc822", "torrent": "application/x-bittorrent",
}


def ext_of(name):
    """`report.final.PDF` → `pdf`; '' when there is none."""
    base = str(name or "").rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base.strip(".") else ""


def mime_for(name, sent=None):
    """The type to record: a meaningful type the client sent wins, then the drive's table, then
    Python's, then octet-stream."""
    sent = (sent or "").split(";")[0].strip().lower()
    if sent and sent not in ("application/octet-stream", "binary/octet-stream", "application/unknown"):
        return sent
    return _TYPES.get(ext_of(name)) or mimetypes.guess_type(str(name or ""))[0] or "application/octet-stream"


# Inline is a browser drawing pixels or sound — never a document that can run something.
_INLINE = re.compile(r"^(image/(png|jpeg|gif|webp|avif|bmp|x-icon|vnd\.microsoft\.icon)|"
                     r"audio/.+|video/.+|application/pdf|text/plain)$")
_TEXTUAL = re.compile(r"^(text/.+|application/(json|xml|yaml|toml|sql|x-tex|x-ipynb\+json|x-subrip))$")

#: The page around a file's bytes can do nothing at all: no script, no form, no frame of ours.
CSP = ("default-src 'none'; img-src 'self' data: blob:; media-src 'self' blob:; "
       "style-src 'unsafe-inline'; font-src 'self' data:; sandbox")


def content_disposition(kind, name):
    """`inline|attachment` with BOTH an ASCII `filename=` and the RFC 5987 `filename*` — names are
    Hebrew, and a bare UTF-8 filename= is not parseable."""
    name = str(name or "file")
    ascii_name = re.sub(r"[^\x20-\x7e]", "_", name).replace('"', "'").replace("\\", "_") or "file"
    return f'{kind}; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(name, safe="")}'


def serve_headers(name, mime, want="inline", etag=None):
    """Headers for a user's file served from this origin. `want` is what the caller asked for;
    inline is granted only to types that render without running anything, and a textual type is
    served as text/plain so that code, markup and data are SHOWN, never executed or parsed.

    A PDF is the one inline type without `sandbox`: Chrome refuses to start its PDF viewer in a
    sandboxed document, and a shared link to a PDF must open as a PDF."""
    mime = (mime or "application/octet-stream").split(";")[0].strip().lower()
    served = "text/plain; charset=utf-8" if _TEXTUAL.match(mime) else mime
    inline = want == "inline" and bool(_INLINE.match(served.split(";")[0]))
    hdrs = {"Content-Type": served,
            "Content-Disposition": content_disposition("inline" if inline else "attachment", name),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": CSP.replace("; sandbox", "") if served == "application/pdf" else CSP,
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, max-age=0, must-revalidate"}
    if etag:
        hdrs["ETag"] = f'"{etag}"'
    return hdrs
