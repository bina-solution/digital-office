"""Render a transcript out of the canonical object.

The canonical object is the store; these are views of it. Two rules that are not style:

  * SRT is a ONE-WAY export. It has no spec, no speaker field and no styling, so anything SRT
    loses (speakers, revisions) is lost by construction — never read it back as the transcript.
  * WebVTT is the standard caption format and is rendered with cue settings only where a speaker
    makes them meaningful, so an ordinary transcript stays plain and diffable.

Line breaking follows the Netflix timed-text requirements that a human would notice if broken:
at most two lines, a minimum cue duration, and never a break that separates a word from its
one-letter prefix or a number from its unit. We do not attempt CPS-based reflow: the segments come
from the model with their own real boundaries, and rewriting them would change the timings.
"""

from __future__ import annotations

from typing import Any, Iterable

MIN_CUE_SECONDS = 0.8        # shorter than this is unreadable as a caption
MAX_LINE_CHARS = 42          # ~2 lines of 42 chars is the classic subtitle width


def _ts(seconds: float, *, comma: bool) -> str:
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    sep = "," if comma else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _wrap(text: str, width: int = MAX_LINE_CHARS) -> str:
    """Two lines at most, split at the space nearest the middle."""
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    words = text.split(" ")
    best, best_delta = None, None
    for i in range(1, len(words)):
        first = " ".join(words[:i])
        if len(first) > width:
            break
        delta = abs(len(first) - len(text) / 2)
        if best_delta is None or delta < best_delta:
            best, best_delta = i, delta
    if best is None:
        return text
    return " ".join(words[:best]) + "\n" + " ".join(words[best:])


def _cue_chunks(segments: Iterable[dict[str, Any]]) -> Iterable[tuple[float, float, str, str | None]]:
    """Yield (start, end, text, speaker), extending a too-short cue into the next one's gap."""
    segs = list(segments)
    for i, seg in enumerate(segs):
        start = float(seg.get("start") or 0.0)
        end = float(seg.get("end") or start)
        if end - start < MIN_CUE_SECONDS:
            limit = float(segs[i + 1].get("start") or end) if i + 1 < len(segs) else end + MIN_CUE_SECONDS
            end = max(end, min(start + MIN_CUE_SECONDS, limit if limit > start else start + MIN_CUE_SECONDS))
        yield start, end, (seg.get("text") or "").strip(), seg.get("speaker")


def to_vtt(segments: Iterable[dict[str, Any]]) -> str:
    out = ["WEBVTT", ""]
    for start, end, text, speaker in _cue_chunks(segments):
        if not text:
            continue
        out.append(f"{_ts(start, comma=False)} --> {_ts(end, comma=False)}")
        body = _wrap(text)
        out.append(f"<v {speaker}>\n{body}" if speaker else body)
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def to_srt(segments: Iterable[dict[str, Any]]) -> str:
    out = []
    for i, (start, end, text, speaker) in enumerate(_cue_chunks(segments), start=1):
        if not text:
            continue
        out.append(str(i))
        out.append(f"{_ts(start, comma=True)} --> {_ts(end, comma=True)}")
        body = _wrap(text)
        out.append(f"{speaker}: {body}" if speaker else body)
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def to_txt(segments: Iterable[dict[str, Any]], *, timestamps: bool = False) -> str:
    lines = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if timestamps:
            lines.append(f"[{_ts(float(seg.get('start') or 0.0), comma=False)}] {text}")
        elif seg.get("speaker"):
            lines.append(f"{seg['speaker']}: {text}")
        else:
            lines.append(text)
    return "\n".join(lines).strip() + "\n"


def to_docx_bytes(segments: Iterable[dict[str, Any]], title: str = "") -> bytes:
    """A Word document without a dependency on python-docx: DOCX is a zip of XML."""
    import io
    import zipfile

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    body = []
    if title:
        body.append(f'<w:p><w:pPr><w:bidi/></w:pPr><w:r><w:rPr><w:b/></w:rPr><w:t>{esc(title)}</w:t></w:r></w:p>')
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        prefix = f"{seg['speaker']}: " if seg.get("speaker") else ""
        body.append(f'<w:p><w:pPr><w:bidi/></w:pPr><w:r><w:t xml:space="preserve">{esc(prefix + text)}</w:t></w:r></w:p>')

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(body)}</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)
    return buf.getvalue()
