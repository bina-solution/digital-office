"""hebrew-states.py — the states a NEW project is born with, in Hebrew.

    RUN python3 /app/patches/hebrew-states.py     (Dockerfile, build time)

WHY. `plane/db/models/state.py` carries `DEFAULT_STATES` — the six states every fresh project gets:
Backlog, Todo, In Progress, Done, Cancelled, Triage. Renaming them is not a translation of the UI
(that is `plane-he`): these are DATA written into the database the first time a project is created, so
a project made in the UI, by an import, or by any tool that does not rename states itself comes up in
English — and the owner's complaint about a new project is exactly that. The declared bootstrap
(`bootstrap.yaml`) and the plan applier already name their own states in Hebrew; this closes the hole
underneath both.

The names match the ones this office uses everywhere else (`bootstrap.yaml`, `plans/dgo-dev.yaml`), so
a project created by hand looks like a project created by a plan.
"""

from __future__ import annotations

import pathlib
import sys

STATE_PY = pathlib.Path("/app/backend/plane/db/models/state.py")

# upstream name -> the office's name. The GROUP is untouched: code branches on it, people do not.
NAMES = {
    "Backlog": "מלאי",
    "Todo": "לביצוע",
    "In Progress": "בתהליך",
    "Done": "בוצע",
    "Cancelled": "בוטל",
    "Triage": "מיון",
}


def main() -> int:
    if not STATE_PY.exists():
        print(f"hebrew-states: {STATE_PY} is missing — the image layout changed, refusing to guess")
        return 1
    src = STATE_PY.read_text(encoding="utf-8")
    if not all(f'"{he}"' in src for he in NAMES.values()):
        missing = [u for u, he in NAMES.items() if f'"name": "{u}",' not in src]
        if missing and not any(f'"name": "{he}",' in src for he in NAMES.values()):
            # Every anchor must be present BEFORE we touch anything: a partial rename would leave a
            # project with some states in Hebrew and some in English, which is worse than none.
            print(f"hebrew-states: upstream DEFAULT_STATES changed — not found: {', '.join(missing)}")
            return 1
    out = src
    for up, he in NAMES.items():
        out = out.replace(f'"name": "{up}",', f'"name": "{he}",')
    if out == src:
        print("hebrew-states: already applied")
        return 0
    STATE_PY.write_text(out, encoding="utf-8")
    print("hebrew-states: DEFAULT_STATES renamed — " + ", ".join(NAMES.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
