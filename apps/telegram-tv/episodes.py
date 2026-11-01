"""episodes — is this file an EPISODE, and of what?

A film library and a series library are the same pile of video files until something reads the names.
The Friends bot in this office publishes its whole run as

    friends S6E4 1080P        friends S6E4 480P

and every other series channel invents its own dialect: `עונה 3 פרק 12`, `S03E12`, `s3 e12`,
`3x12`, `פרק 12`, `Episode 12`, sometimes with a Hebrew suffix (`מדובב`, `כתוביות`) where the
library wants the quality. Nothing about that is Telegram's or the platform's business — it is a pure
function from a file name (and a caption) to {series, season, episode, quality}, which is why it lives
in its own module with its own tests and no imports.

Two rules worth stating, because breaking either is how a TV app becomes a file browser:

  * **The same episode in two qualities is ONE episode.** `S6E4 1080P` and `S6E4 480P` are the same
    thirty minutes of television, and showing them as two cards is exactly the "list of files" the
    owner asked not to see. The variants are kept together (see `group_episodes`) so the player can
    offer a quality switch — and so the default can be the smaller file, which is what makes playback
    start in a second instead of buffering.
  * **An unknown name is a standalone film, never a guessed episode.** A file called
    `The.Matrix.1999.mkv` must not be filed as season 1 episode 1 of "The Matrix".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: `S3E12`, `s03 e12`, `S3.E12`, `S3 EP12`
RE_SE = re.compile(r"(?<![A-Za-z0-9])s\s*(\d{1,2})\s*[._\- ]?\s*e\s*[pP]?\s*(\d{1,3})(?!\d)", re.I)
#: `3x12`
RE_X = re.compile(r"(?<![A-Za-z0-9])(\d{1,2})\s*x\s*(\d{1,3})(?!\d)", re.I)
#: `עונה 3 פרק 12` — and the bare `פרק 12`
RE_HE = re.compile(r"עונה\s*(\d{1,2})\s*[,\-–]?\s*(?:פרק|אפיזודה)\s*(\d{1,3})")
RE_HE_EP = re.compile(r"(?:פרק|אפיזודה)\s*(\d{1,3})(?!\d)")
RE_EN_EP = re.compile(r"(?<![A-Za-z0-9])(?:episode|ep)\s*[._\- ]?\s*(\d{1,3})(?!\d)", re.I)

#: Quality tokens, richest first: the file name is searched in this order and the first hit wins.
QUALITY_TOKENS = (
    ("2160p", ("2160p", "4k", "uhd")),
    ("1440p", ("1440p", "2k",)),
    ("1080p", ("1080p", "fhd", "full hd")),
    ("720p", ("720p", "hd720")),
    ("480p", ("480p", "sd")),
    ("360p", ("360p",)),
)

#: Words that mark a variant of the SAME episode rather than a different one. They are dropped from
#: the series title, otherwise "friends מדובב" and "friends" become two different shows.
VARIANT_WORDS = ("מדובב", "כתוביות", "מתורגם", "dubbed", "subbed", "dual", "hebrew", "עברית",
                 "multi", "עם תרגום", "כתוביות בעברית")

#: Noise to strip before a title is used as a series name.
_NOISE = re.compile(r"[\[\](){}]")


@dataclass
class EpisodeInfo:
    series: str = ""            # "" = not an episode
    season: int = 0
    episode: int = 0
    quality: str = ""
    label: str = ""             # e.g. "עונה 6 · פרק 4"
    extra: list[str] = field(default_factory=list)

    @property
    def is_episode(self) -> bool:
        return bool(self.series) and self.episode > 0


def quality_of(text: str) -> str:
    low = (text or "").lower()
    for label, tokens in QUALITY_TOKENS:
        if any(t in low for t in tokens):
            return label
    return ""


def _strip_variants(text: str) -> str:
    out = text
    for w in VARIANT_WORDS:
        out = re.sub(re.escape(w), " ", out, flags=re.I)
    return re.sub(r"\s{2,}", " ", out).strip()


def _clean_series(text: str) -> str:
    """The show's name, from the text that carried the episode number."""
    t = _NOISE.sub(" ", text)
    t = _strip_variants(t)
    # cut everything from the season/episode marker onwards
    t = RE_SE.split(t)[0]
    t = RE_HE.split(t)[0]
    t = RE_X.split(t)[0]
    t = RE_EN_EP.split(t)[0]
    t = RE_HE_EP.split(t)[0]
    t = re.sub(r"[\-–_|.]+", " ", t)
    t = re.sub(r"\b\d{3,4}p\b", " ", t, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t).strip(" -–.|")
    return t.strip()


def parse(*texts: str, fallback_series: str = "") -> EpisodeInfo:
    """File name(s) and caption(s) → {series, season, episode, quality}. Total: never raises, and an
    unparseable name is simply not an episode.

    `fallback_series` is the CHAT's own title, used when the name carries an episode number but no
    show name at all — `S01E01.mp4`, `פרק 12.mp4`, `עונה 2 פרק 5`. In a channel that publishes one
    show, the publisher IS the show, and refusing those files would leave a series channel's episodes
    as loose cards."""
    for raw in texts:
        text = (raw or "").strip()
        if not text:
            continue
        info = EpisodeInfo(quality=quality_of(text))
        m = RE_SE.search(text)
        if m:
            info.season, info.episode = int(m.group(1)), int(m.group(2))
        else:
            m = RE_X.search(text)
            if m:
                info.season, info.episode = int(m.group(1)), int(m.group(2))
            else:
                m = RE_HE.search(text)
                if m:
                    info.season, info.episode = int(m.group(1)), int(m.group(2))
                else:
                    m = RE_HE_EP.search(text) or RE_EN_EP.search(text)
                    if m:
                        info.episode = int(m.group(1))
        if info.episode <= 0:
            continue
        info.series = _clean_series(text) or _clean_series(fallback_series)
        if not info.series:
            continue
        info.label = (f"עונה {info.season} · פרק {info.episode}" if info.season
                      else f"פרק {info.episode}")
        if info.quality:
            info.extra.append(info.quality)
        return info
    return EpisodeInfo()


def series_key(chat_id: int, series: str) -> str:
    """The identity of a show INSIDE a chat. A chat is the publisher, and two channels publishing
    "Friends" are two libraries — merging them across chats would mix prints, languages and quality."""
    slug = re.sub(r"[^0-9A-Za-zא-ת]+", "-", (series or "").strip().lower()).strip("-")
    return f"{chat_id}:{slug}" if slug else ""


def group_episodes(rows: list[dict]) -> list[dict]:
    """Movie rows → one entry per EPISODE, with its quality variants listed.

    Input order is preserved for the variants (so the richest file stays first), and the episodes come
    out sorted by season then episode — the order a person watches them in, which is the one thing a
    file listing never gives you.
    """
    by_episode: dict[tuple[int, int], dict] = {}
    for row in rows:
        if not row.get("series") or not row.get("episode"):
            continue
        key = (int(row.get("season") or 0), int(row["episode"]))
        entry = by_episode.setdefault(key, {
            "season": key[0], "episode": key[1],
            "title": row.get("title") or "", "description": row.get("description") or "",
            "variants": [],
        })
        entry["variants"].append(row)
    ordered = [by_episode[k] for k in sorted(by_episode)]
    for entry in ordered:
        # biggest file first: "best quality" is the meaningful default for a switch, and the player
        # decides on its own which one to actually open (see /api/play).
        entry["variants"].sort(key=lambda v: -int(v.get("size") or 0))
        entry["label"] = (f"עונה {entry['season']} · פרק {entry['episode']}" if entry["season"]
                          else f"פרק {entry['episode']}")
    return ordered
