#!/usr/bin/env python3
"""Export a sanitized, observable Copilot session ledger.

The VS Code transcript contains nested agent events. This exporter preserves
every public message, tool request, tool execution start, and completion while
excluding private reasoning fields and redacting credential-shaped values.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


EXPORTED_TYPES = {
    "session.start",
    "user.message",
    "assistant.message",
    "assistant.turn_start",
    "assistant.turn_end",
    "tool.execution_start",
    "tool.execution_complete",
}
PRIVATE_KEYS = {"reasoningText", "reasoning", "chainOfThought", "thought"}
SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|credential|password|passwd|secret|token|api[_-]?key)",
    re.IGNORECASE,
)
TEXT_REDACTIONS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"(?i)((?:api[_-]?key|password|passwd|secret|token)\s*[=:]\s*)"
        r"([^\s,;\"'}]{4,})"
    ),
    re.compile(
        r"(?i)([?&](?:api[_-]?key|password|passwd|secret|token)=)"
        r"([^&#\s]+)"
    ),
)


class Sanitizer:
    def __init__(self) -> None:
        self.redactions = 0
        self.private_fields_removed = 0

    def text(self, value: str) -> str:
        for pattern in TEXT_REDACTIONS:
            value, count = pattern.subn(r"\1[REDACTED]", value)
            self.redactions += count
        return value

    def value(self, value: Any, key: str | None = None) -> Any:
        if key in PRIVATE_KEYS:
            self.private_fields_removed += 1
            return None
        if key and SENSITIVE_KEY.search(key) and value not in (None, ""):
            self.redactions += 1
            return "[REDACTED]"
        if isinstance(value, dict):
            result = {}
            for child_key, child_value in value.items():
                if child_key in PRIVATE_KEYS:
                    self.private_fields_removed += 1
                    continue
                result[child_key] = self.value(child_value, child_key)
            return result
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, str):
            return self.text(value)
        return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export(source: Path, output: Path, manifest_path: Path) -> None:
    sanitizer = Sanitizer()
    source_counts: Counter[str] = Counter()
    exported_counts: Counter[str] = Counter()
    invalid_lines = 0
    output.parent.mkdir(parents=True, exist_ok=True)

    with source.open("r", encoding="utf-8") as input_handle:
        with output.open("wb") as raw_output:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=raw_output, mtime=0
            ) as compressed:
                for line_number, line in enumerate(input_handle, 1):
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        invalid_lines += 1
                        continue
                    event_type = event.get("type", "unknown")
                    source_counts[event_type] += 1
                    if event_type not in EXPORTED_TYPES:
                        continue
                    record = sanitizer.value(event)
                    record["source_line"] = line_number
                    compressed.write(
                        (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
                    )
                    exported_counts[event_type] += 1

    manifest = {
        "format": "browser42-observable-session-ledger/v1",
        "source": str(source),
        "source_sha256": sha256(source),
        "output": str(output),
        "output_sha256": sha256(output),
        "source_event_count": sum(source_counts.values()),
        "exported_event_count": sum(exported_counts.values()),
        "source_event_types": dict(sorted(source_counts.items())),
        "exported_event_types": dict(sorted(exported_counts.items())),
        "invalid_source_lines": invalid_lines,
        "redactions": sanitizer.redactions,
        "private_fields_removed": sanitizer.private_fields_removed,
        "scope": (
            "All observable transcript events. Private chain-of-thought/reasoning "
            "is excluded. Tool outputs are included only when the source transcript "
            "stored them in an observable message or tool event."
        ),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    export(args.source, args.output, args.manifest)


if __name__ == "__main__":
    main()