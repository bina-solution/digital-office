#!/usr/bin/env python3
"""digital-assets/content/render.py — the content library on disk, as one JSON document on stdout.

    python3 apps/digital-assets/content/render.py <content-dir> [<type>/<slug> …]

Reads every `<type>/<slug>.<lang>.md` under the directory (or only the pieces named), splits the YAML
front matter from the Markdown body, and prints {"pieces": [...], "problems": [...]} for the importer
(content/importer.py), which runs inside the app's container where there is no YAML library and no
repository. A file that does not parse, or whose front matter disagrees with its own path, is a
problem — reported, never imported.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

TYPES = ("article", "project", "tutorial", "comparison", "directory", "news", "report", "post", "glossary")
NAME = re.compile(r"(?P<slug>[a-z0-9][a-z0-9-]*)\.(?P<lang>he|en)\.md")


def split(text: str) -> tuple[dict, str]:
    """(front matter, body) of a file that starts with a `---` line."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("no front matter: the file must start with a --- line")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            front = yaml.safe_load("".join(lines[1:i])) or {}
            if not isinstance(front, dict):
                raise ValueError("the front matter is not a mapping")
            return front, "".join(lines[i + 1:]).lstrip("\n")
    raise ValueError("the front matter has no closing --- line")


def piece(path: Path, root: Path) -> dict:
    rel = path.relative_to(root).as_posix()
    kind = path.parent.name
    m = NAME.fullmatch(path.name)
    if kind not in TYPES or not m:
        raise ValueError(f"{rel}: not <type>/<slug>.<lang>.md with type in {', '.join(TYPES)}")
    raw = path.read_text(encoding="utf-8")
    front, body = split(raw)
    for field, want in (("type", kind), ("slug", m["slug"]), ("lang", m["lang"])):
        if str(front.get(field) or want) != want:
            raise ValueError(f"{rel}: front matter says {field}: {front.get(field)!r}, the path says {want!r}")
    if not str(front.get("title") or "").strip():
        raise ValueError(f"{rel}: no title")
    if not body.strip():
        raise ValueError(f"{rel}: empty body")
    # dates and the like come out of YAML as objects; the importer speaks JSON
    front = json.loads(json.dumps(front, ensure_ascii=False, default=str))
    return {"type": kind, "slug": m["slug"], "lang": m["lang"], "path": rel, "front": front,
            "body": body, "words": len(body.split()),
            "sha": hashlib.sha256(raw.encode("utf-8")).hexdigest()}


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve()
    only = {a.strip("/").removesuffix(".md") for a in argv[2:]}
    pieces, problems = [], []
    for path in sorted(root.glob("*/*.md")):
        rel = path.relative_to(root).as_posix().removesuffix(".md")
        if only and rel not in only and rel.rsplit(".", 1)[0] not in only:
            continue
        try:
            pieces.append(piece(path, root))
        except (ValueError, yaml.YAMLError, UnicodeDecodeError) as e:
            problems.append(str(e).splitlines()[0][:300])
    json.dump({"pieces": pieces, "problems": problems}, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
