#!/usr/bin/env python3
"""no-phone-home.py — make this deployment's "it does not talk to the cloud" claim TRUE.

    RUN python3 /app/patches/no-phone-home.py        (from the image build)

Plane Community Edition phones home on its own behalf, and the manifest for this app says it does
not. Both facts were true at the same time, which is the bug: `apps/project-pln/app.json` describes
the cloud API token as something read once for an import, while the running instance reported
`is_telemetry_enabled = t` and made 24 outbound requests to `telemetry.plane.so`.

Two calls, both from the API entrypoint on EVERY boot (`register_instance`):

  1. `GET https://api.github.com/repos/makeplane/plane/releases/latest` — a version check.
     Exception-swallowed (it falls back to the current version), but still an outbound request.
  2. `push_instance_metrics.delay()` — the Celery task that builds an OpenTelemetry exporter and
     ships workspace/project/issue counts, the machine signature and the instance id to
     `telemetry.plane.so`. Gated on `Instance.is_telemetry_enabled`, whose model default is `True`
     and whose god-mode form default is `True` when the field is absent — so a fresh self-hosted
     instance is opted IN by default and the operator never answered a question.

WHAT THIS DOES, in two layers, because either alone is leaky:

  * the DEFAULTS become off (model + god-mode form), so a fresh install reads `false` in the
    database and the setup screen does not pre-tick telemetry;
  * BOTH call sites additionally require `PLANE_TELEMETRY=1` in the environment. This is the layer
    that makes the claim hold no matter what the database says later: a god-mode toggle, a restored
    archive from another instance, or a future migrate that re-enables it still cannot make this
    container open a socket to a third party. `PLANE_TELEMETRY` lives in the deployment's own
    `.env`, which is the operator's file.

The trade is deliberate and documented in the app README: the god-mode telemetry switch becomes
inert unless the operator sets `PLANE_TELEMETRY=1`. A switch that quietly did nothing would be
dishonest; a switch whose default is "off, and off means off" is the platform's own reading of
"this app never talks to the cloud".

Every edit asserts its anchor first. Upstream moving one of these lines must FAIL THE BUILD — an
image that claims to be silenced while shipping telemetry is worse than no image.
"""

from __future__ import annotations

import pathlib
import sys

EDITS = [
    # ── the defaults ────────────────────────────────────────────────────────────────────────────
    (
        "/app/backend/plane/license/models/instance.py",
        "    is_telemetry_enabled = models.BooleanField(default=True)",
        "    # BINA: self-hosted means self-contained; opt IN, never out.\n"
        "    is_telemetry_enabled = models.BooleanField(default=False)",
        "Instance telemetry default",
    ),
    (
        "/app/backend/plane/license/api/views/admin.py",
        '        is_telemetry_enabled = request.POST.get("is_telemetry_enabled", True)',
        '        # BINA: a form that omits the field must not be read as consent.\n'
        '        is_telemetry_enabled = request.POST.get("is_telemetry_enabled", False)',
        "god-mode setup form default",
    ),
    # ── the two call sites ──────────────────────────────────────────────────────────────────────
    (
        "/app/backend/plane/license/bgtasks/telemetry_metrics.py",
        """    if not instance.is_telemetry_enabled:
        logger.debug("Telemetry disabled, skipping metrics push")
        return""",
        """    # BINA: the database flag is not enough — see /app/patches/no-phone-home.py. BOTH the
    # operator's environment and the instance flag must say yes.
    if os.environ.get("PLANE_TELEMETRY", "0") != "1":
        logger.info("Telemetry is off for this deployment (PLANE_TELEMETRY != 1), skipping metrics push")
        return

    if not instance.is_telemetry_enabled:
        logger.debug("Telemetry disabled, skipping metrics push")
        return""",
        "metrics export gate",
    ),
    (
        "/app/backend/plane/license/management/commands/register_instance.py",
        "        latest_version = self.check_for_latest_version(current_version)",
        "        # BINA: the update check is an outbound request too, and this deployment does not\n"
        "        # make them unless the operator opted in. Without it the instance simply reports\n"
        '        # its own version as the latest.\n'
        '        if os.environ.get("PLANE_TELEMETRY", "0") == "1":\n'
        "            latest_version = self.check_for_latest_version(current_version)\n"
        "        else:\n"
        "            latest_version = current_version",
        "github version check",
    ),
]


def main() -> int:
    failures = []
    for path, old, new, why in EDITS:
        p = pathlib.Path(path)
        if not p.is_file():
            failures.append(f"{why}: {path} does not exist")
            continue
        text = p.read_text(encoding="utf-8")
        if old not in text:
            failures.append(f"{why}: anchor not found in {path}")
            continue
        if new in text:
            print(f"  already applied: {why}")
            continue
        p.write_text(text.replace(old, new, 1), encoding="utf-8")
        print(f"  patched: {why} ({path})")

    if failures:
        print("REFUSING to build:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        print("Upstream moved something this patch depends on. Re-derive it before building an",
              file=sys.stderr)
        print("image that claims to be silent and is not.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
