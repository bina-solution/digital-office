"""scrapers — how a movie is recovered from a chat.

This is the port of the Android original's whole reason for existing. Telegram is a chat protocol and
a film library is smuggled through it as ordinary messages, so "what is a movie here" is a POLICY,
not a fact about Telegram:

  * `default` — every video message is a movie. Title from the file name, description from the
    caption. Correct for a channel that posts one clean file per film (the original's
    DefaultChatScrapper).
  * `album`   — the film arrives as a run of messages: a poster photo, an info text, then the file.
    Title/description are recovered from the neighbouring messages, the poster from the photo
    (the original's AmsalemChatScrapper, generalised: it addressed neighbours by arithmetic on the
    message id, which only works inside one channel's private numbering).
  * `amsalem` — the album pattern plus the Hebrew field parsing of that particular poster format
    ("שם הסרט", "שנה -", "איכות -", "דירוג: IMDb", "ז'אנר -", "תקציר"). This is the richest scraper
    and the reason the library looks like a catalogue instead of a file listing.

Every scraper is pure: messages in, movie dicts out. Nothing here talks to Telegram or to the store,
so `python3 -c "import scrapers"` plus a handful of literals is a complete test of the parsing — the
part of this app most likely to break when a channel changes its format.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import episodes

VIDEO_EXT = (".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".ts", ".wmv", ".flv", ".mpg", ".mpeg")

#: The smallest thing that can be a FILM. Telegram delivers stickers, animated GIFs and voice-note
#: style clips as documents with a `video/` mime type, so without a floor a channel's sticker pack
#: becomes "films" in the library — observed on the real library: a 193 KB `sticker` card beside a
#: 4 GB film. A file whose size Telegram does not report is KEPT: unknown is not the same as small.
MIN_MOVIE_BYTES = int(os.environ.get("TV_MIN_MOVIE_BYTES", str(2 * 1024 * 1024)))

#: How far back a video looks for its poster and its info text. Four messages is the original's
#: window (poster, info, video, file) with one message of slack for a reposted poster.
LOOKBACK = 4


# ── the message, flattened ───────────────────────────────────────────────────────────────────

@dataclass
class Msg:
    id: int
    chat_id: int
    date: int = 0
    kind: str = "other"          # video | photo | text | other
    text: str = ""
    caption: str = ""
    file_name: str = ""
    mime: str = ""
    size: int = 0
    duration: int = 0
    width: int = 0
    height: int = 0
    doc_id: int = 0
    access_hash: int = 0
    grouped_id: int = 0
    has_thumb: bool = False
    #: Inline button labels, row by row. A BOT's whole interface is these: "עונה 5" answers with a grid
    #: of episode buttons, and the only honest way to learn a season's length is to read them back
    #: (see botfetch.py). The normalised message carried no buttons until this field existed, which is
    #: why the first fetch job reported "no menu" for a bot that had just answered with one.
    buttons: list[list[str]] = field(default_factory=list)
    out: bool = False
    tags: list[str] = field(default_factory=list)


def normalize(message) -> Msg:
    """Telethon Message → Msg. Deliberately total: an unknown message becomes `kind: other` rather
    than raising, because one exotic message type in one channel must not abort a whole scan."""
    m = Msg(id=int(getattr(message, "id", 0) or 0),
            chat_id=int(getattr(message, "chat_id", 0) or 0),
            out=bool(getattr(message, "out", False)),
            buttons=[[(getattr(b, "text", "") or "") for b in row]
                     for row in (getattr(message, "buttons", None) or [])],
            date=int(getattr(message, "date", None).timestamp()) if getattr(message, "date", None) else 0,
            grouped_id=int(getattr(message, "grouped_id", 0) or 0))
    doc = getattr(message, "document", None)
    if _is_animation(doc):
        # A sticker or an animated GIF is a `video/webm` document with a `DocumentAttributeSticker` /
        # `DocumentAttributeAnimated`. It is not a film, and calling it one is how a library fills
        # with three-second clips.
        m.kind = "other"
        return m
    if getattr(message, "video", None) is not None or (doc is not None and _is_video(doc)):
        m.kind = "video"
    elif getattr(message, "photo", None) is not None:
        m.kind = "photo"
    else:
        body = (getattr(message, "message", None) or "").strip()
        m.kind = "text" if body else "other"
        m.text = body
        return m

    m.caption = (getattr(message, "message", None) or "").strip()
    if doc is not None:
        m.mime = getattr(doc, "mime_type", "") or ""
        m.size = int(getattr(doc, "size", 0) or 0)
        m.file_name = _doc_filename(doc)
        for attr in getattr(doc, "attributes", []) or []:
            w = getattr(attr, "w", None)
            if w:                                     # DocumentAttributeVideo
                m.width, m.height = int(w), int(getattr(attr, "h", 0) or 0)
                m.duration = int(getattr(attr, "duration", 0) or 0)
        m.doc_id = int(getattr(doc, "id", 0) or 0)
        m.access_hash = int(getattr(doc, "access_hash", 0) or 0)
        m.has_thumb = bool(getattr(doc, "thumbs", None))
    else:                                             # a video sent as a photo-less media
        video = getattr(message, "video", None)
        m.has_thumb = bool(getattr(video, "thumbs", None)) if video is not None else False
    return m


def _is_animation(doc) -> bool:
    """True for the messages Telegram itself marks as stickers or animated images."""
    for attr in getattr(doc, "attributes", []) or []:
        name = type(attr).__name__
        if name in ("DocumentAttributeSticker", "DocumentAttributeAnimated"):
            return True
    return False


def _is_video(doc) -> bool:
    mime = (getattr(doc, "mime_type", "") or "").lower()
    if mime.startswith("video/"):
        return True
    return _doc_filename(doc).lower().endswith(VIDEO_EXT)


def _doc_filename(doc) -> str:
    for attr in getattr(doc, "attributes", []) or []:
        name = getattr(attr, "file_name", None)
        if name:
            return str(name)
    return ""


# ── shared text helpers ──────────────────────────────────────────────────────────────────────

QUOTED = re.compile(r"[\"„“]([^\"„“\n]{2,120})[\"“”]")
YEAR = re.compile(r"(?:שנה|שנת)\s*[-–:]\s*((?:19|20)\d{2})")
YEAR_BARE = re.compile(r"\b((?:19|20)\d{2})\b")
QUALITY = re.compile(r"איכות\s*[-–:]\s*([^\n|]{1,40})")
RATING = re.compile(r"דירוג[^\n\d]{0,40}?(\d{1,2}(?:[.,]\d)?)")
GENRES = re.compile(r"ז[\"'’׳]אנר\s*[-–:]\s*([^\n|]{2,120})")
SUMMARY = re.compile(r"תקציר\s*[👇:：]?\s*\n?(.+)", re.S)
INFO_HINT = re.compile(r"(?:שנה|שנת)\s*[-–:]\s*(?:19|20)\d{2}|איכות\s*[-–:]|דירוג[^\n]{0,30}\d")


def clean_title(name: str) -> str:
    """A file name → something a person would read. Keeps the name's own words, drops the extension
    and the dots/underscores that stand in for spaces, and trims a leading group tag like
    `[Movies] ...` only when it is bracketed (a bracket at the START is a label; one inside the name
    may be part of the title)."""
    stem = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", (name or "").strip())
    stem = re.sub(r"[._]+", " ", stem)
    stem = re.sub(r"\s{2,}", " ", stem).strip()
    stem = re.sub(r"^\[[^\]]{1,24}\]\s*", "", stem)
    return stem.strip(" -–|") or (name or "").strip()


def first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:180]
    return ""


def parse_info(text: str) -> dict:
    """The Hebrew poster format → fields. Every regex is optional: a poster that carries only a title
    and a year is a valid poster, and a film with no parseable metadata must still appear (with the
    file-name title) rather than vanish from the library."""
    t = (text or "").replace("\u200f", "").replace("\u200e", "")
    quoted = [q.strip() for q in QUOTED.findall(t) if len(q.strip()) > 1]
    out: dict = {}
    if quoted:
        out["title"] = quoted[0]
    year = YEAR.search(t)
    if not year:
        # A year inside a quoted title ("הסרט 1994") is still a year; outside one it is probably a
        # resolution or a file count, which is why the bare form is only trusted in a short text.
        year = YEAR_BARE.search(t) if len(t) < 400 else None
    if year:
        out["year"] = year.group(1)
    quality = QUALITY.search(t)
    if quality:
        out["quality"] = quality.group(1).strip()
    rating = RATING.search(t)
    if rating:
        out["rating"] = rating.group(1).replace(",", ".")
    genres = GENRES.search(t)
    if genres:
        out["tags"] = [g.strip() for g in re.split(r"[,/|]", genres.group(1)) if g.strip()][:8]
    summary = SUMMARY.search(t)
    if summary:
        out["description"] = re.sub(r"\s+\n", "\n", summary.group(1)).strip()[:1200]
    elif len(t) > 60:
        out["description"] = t.strip()[:1200]
    return out


# ── the three scrapers ───────────────────────────────────────────────────────────────────────

def _base_movie(m: Msg, chat_id: int) -> dict:
    return {
        "id": f"{chat_id}:{m.id}", "chat_id": int(chat_id), "message_id": int(m.id),
        "title": "", "year": "", "rating": "", "tags": "", "description": "", "quality": "",
        "file_name": m.file_name or "", "mime": m.mime or "video/mp4", "size": int(m.size or 0),
        "duration": int(m.duration or 0), "width": int(m.width or 0), "height": int(m.height or 0),
        "doc_id": int(m.doc_id or 0), "access_hash": int(m.access_hash or 0),
        "poster_message_id": 0, "date": int(m.date or 0),
        "series": "", "series_key": "", "season": 0, "episode": 0, "quality_label": "",
    }


def _join_tags(tags) -> str:
    return ", ".join(dict.fromkeys([t for t in (tags or []) if t]))[:300]


def extract_default(msgs: list[Msg], chat_id: int) -> list[dict]:
    out = []
    for m in msgs:
        if m.kind != "video":
            continue
        row = _base_movie(m, chat_id)
        row["title"] = first_line(m.caption) or clean_title(m.file_name)
        row["description"] = m.caption if m.caption != row["title"] else ""
        out.append(row)
    return out


def _neighbours(msgs: list[Msg], i: int) -> tuple[Msg | None, Msg | None]:
    """(poster, info) for the video at index `i`, looking BACKWARDS only.

    Backwards-only is the one thing the original got exactly right and worth stating: a channel posts
    poster → info → file, so a video's metadata always precedes it. Looking forward would let a film
    pick up the NEXT film's poster, which looks like a working feature and shows the wrong cover."""
    video = msgs[i]
    poster = info = None
    lo = max(0, i - LOOKBACK)
    for j in range(i - 1, lo - 1, -1):
        cand = msgs[j]
        same_album = bool(video.grouped_id) and cand.grouped_id == video.grouped_id
        if poster is None and cand.kind == "photo" and (same_album or not video.grouped_id):
            poster = cand
        if info is None and cand.kind == "text" and len(cand.text) >= 20:
            info = cand
        if same_album and poster is not None and info is not None:
            break
    return poster, info


def extract_album(msgs: list[Msg], chat_id: int) -> list[dict]:
    out = []
    for i, m in enumerate(msgs):
        if m.kind != "video":
            continue
        poster, info = _neighbours(msgs, i)
        row = _base_movie(m, chat_id)
        row["poster_message_id"] = int(poster.id) if poster else 0
        info_text = (info.text if info else "") or m.caption
        quoted = QUOTED.search(info_text)
        row["title"] = first_line(m.caption) or (quoted.group(1).strip() if quoted else clean_title(m.file_name))
        row["description"] = info_text if info_text and info_text != row["title"] else ""
        out.append(row)
    return out


def extract_amsalem(msgs: list[Msg], chat_id: int) -> list[dict]:
    out = []
    for i, m in enumerate(msgs):
        if m.kind != "video":
            continue
        poster, info = _neighbours(msgs, i)
        row = _base_movie(m, chat_id)
        row["poster_message_id"] = int(poster.id) if poster else 0
        parsed = parse_info(info.text) if info and INFO_HINT.search(info.text) else {}
        row.update({k: v for k, v in parsed.items() if k in ("title", "year", "rating", "description", "quality")})
        row["tags"] = _join_tags(parsed.get("tags"))
        if not row["title"]:
            row["title"] = first_line(m.caption) or clean_title(m.file_name)
        return_tags = [t for t in [row["tags"], f"ערוץ:{chat_id}"] if t]
        row["tags"] = _join_tags(", ".join(return_tags).split(", "))
        out.append(row)
    return out


@dataclass(frozen=True)
class Scraper:
    id: str
    label_he: str
    hint_he: str
    extract: object


SCRAPERS: dict[str, Scraper] = {
    "default": Scraper(
        "default", "קובץ אחד = סרט",
        "כל הודעת וידאו היא סרט. הכותרת משם הקובץ, התיאור מהכיתוב. מתאים לערוץ שמעלה קובץ נקי לכל סרט.",
        extract_default),
    "album": Scraper(
        "album", "פוסטר + מידע + קובץ",
        "הסרט מגיע כרצף הודעות: תמונת פוסטר, טקסט מידע ואז הקובץ. הפוסטר והתיאור נלקחים מההודעות שלפני.",
        extract_album),
    "amsalem": Scraper(
        "amsalem", "פורמט עברי מלא (אמסלם)",
        "כמו הרצף, ובנוסף מחלץ כותרת, שנה, איכות, דירוג IMDb וז׳אנרים מהטקסט בפורמט העברי.",
        extract_amsalem),
}


def score(scraper_id: str, msgs: list[Msg]) -> int:
    """How well a scraper fits this chat, from the messages themselves (no network, no heuristics
    about channel names — the original keyed on the channel being titled "amsalem", which stops
    working the moment the same format appears anywhere else)."""
    videos = [i for i, m in enumerate(msgs) if m.kind == "video"]
    if not videos:
        return 0
    if scraper_id == "default":
        return len(videos)
    patterned = posters = infos = 0
    for i in videos:
        poster, info = _neighbours(msgs, i)
        if poster:
            posters += 1
        if info:
            infos += 1
            if INFO_HINT.search(info.text):
                patterned += 1
    if scraper_id == "album":
        return posters + infos
    return patterned * 3                                   # amsalem must beat album only on real hits


def detect(msgs: list[Msg]) -> str:
    """The scraper this chat's messages call for. Ties go to the RICHER scraper: a chat that satisfies
    the Hebrew format is parsed by it, and one that merely has posters is an album."""
    best, best_score = "default", 0
    for sid in ("amsalem", "album", "default"):
        s = score(sid, msgs)
        if s > best_score:
            best, best_score = sid, s
    return best


def extract(scraper_id: str, msgs: list[Msg], chat_id: int, chat_title: str = "") -> list[dict]:
    """Run a scraper, apply the film floor, and read the episode coordinates out of each name.

    Both post-processing steps live here rather than inside each scraper, because neither is a policy
    about a chat's FORMAT: the floor is the same rule everywhere (a sticker is not a film), and being
    an episode is a property of the NAME, not of the channel that posted it. A scraper that forgot
    either would silently refill the library with stickers, or turn a whole series into loose cards.
    """
    scraper = SCRAPERS.get(scraper_id) or SCRAPERS["default"]
    rows = [r for r in scraper.extract(msgs, chat_id)
            if not r.get("size") or int(r["size"]) >= MIN_MOVIE_BYTES]
    for row in rows:
        info = episodes.parse(row.get("title", ""), row.get("file_name", ""),
                              row.get("description", "")[:200], fallback_series=chat_title)
        if info.is_episode:
            row["series"] = info.series
            row["series_key"] = episodes.series_key(chat_id, info.series)
            row["season"] = info.season
            row["episode"] = info.episode
            row["quality_label"] = info.quality or row.get("quality") or ""
            # The episode label replaces the file name as the card's title: "עונה 6 · פרק 4" is what a
            # person is looking for, and "friends S6E4 1080P" is what the bot called it.
            row["title"] = info.label
    return rows


def choices() -> list[dict]:
    return [{"id": s.id, "label": s.label_he, "hint": s.hint_he} for s in SCRAPERS.values()]
