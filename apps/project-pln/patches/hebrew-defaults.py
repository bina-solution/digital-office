#!/usr/bin/env python3
"""hebrew-defaults.py — nothing in this deployment should default to UTC or to English dates.

    RUN python3 /app/patches/hebrew-defaults.py     (from the image build)

Plane's models default every timezone field to `"UTC"`:

    Workspace.timezone      Project.timezone      Cycle.timezone      User.user_timezone

which is right for a product sold worldwide and wrong for this office: a workspace is created with
UTC, the owner then has to find the setting, and until he does every cycle boundary, reminder and
"overdue" is computed three hours off. The default is the only thing this changes; each field is
still a per-record choice, and `TIMEZONE_CHOICES` already contains Asia/Jerusalem.

The other half of "Hebrew dates" — the LANGUAGE of a date — is not here. It is split in two:

  * dates formatted through `@plane/utils/datetime.ts` (date-fns) became locale-aware in the
    `plane-he` patch, which shadows those helpers with Hebrew-aware wrappers;
  * the home widget's date line is formatted by **luxon**, whose locale comes from the RUNTIME
    (`Settings.defaultLocale`) — and luxon is not a declared dependency of any workspace package
    (it arrives transitively, and pnpm runs with `node-linker = isolated`), so no file we override
    may import it, and adding it would need a lockfile change that the build's
    `--frozen-lockfile` forbids. That one line is left for a change with its own lockfile update,
    and it is recorded in the app README rather than half-done here.

Same contract as the sibling patcher: every anchor is asserted, and upstream moving a line FAILS the
build instead of shipping an image that silently keeps UTC.
"""

from __future__ import annotations

import pathlib
import sys

TZ = "Asia/Jerusalem"

FILES = [
    "/app/backend/plane/db/models/workspace.py",
    "/app/backend/plane/db/models/project.py",
    "/app/backend/plane/db/models/cycle.py",
    "/app/backend/plane/db/models/user.py",
]

OLD = 'timezone = models.CharField(max_length=255, default="UTC"'
NEW = f'timezone = models.CharField(max_length=255, default="{TZ}"'
OLD_USER = 'user_timezone = models.CharField(max_length=255, default="UTC"'
NEW_USER = f'user_timezone = models.CharField(max_length=255, default="{TZ}"'


def main() -> int:
    failures, patched = [], 0
    for path in FILES:
        p = pathlib.Path(path)
        if not p.is_file():
            failures.append(f"{path} does not exist")
            continue
        text = p.read_text(encoding="utf-8")
        if NEW in text or NEW_USER in text:
            print(f"  already applied: {path}")
            continue
        if OLD not in text and OLD_USER not in text:
            failures.append(f"no timezone default to patch in {path}")
            continue
        text = text.replace(OLD, NEW, 1).replace(OLD_USER, NEW_USER, 1)
        p.write_text(text, encoding="utf-8")
        patched += 1
        print(f"  patched: {path} -> default {TZ}")

    if failures:
        print("REFUSING to build:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        print("Upstream moved a timezone default. Re-derive this patch before building.", file=sys.stderr)
        return 1
    print(f"{patched} file(s) patched; timezone default is {TZ}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
