# project-pln — Plane Community Edition, trimmed to what the office engine can carry.
#
# Upstream is the official All-In-One image (AGPL-3.0-only, makeplane/plane,
# deployments/aio/community). It already packs web + space + admin + api + worker + beat + live +
# Caddy into ONE container under supervisord, which is the only shape that fits a 5 GiB engine.
# What we change, and why — three files, nothing else:
#
#   1. supervisor.conf  — the AIO runs eight programs; the office runs four (migrator, api,
#      worker, proxy). `space` (public sharing) and `live` (real-time cursors) are two more Node
#      servers, and `beat` is a third Python process: ~400 MB of the stack's ~1 GB. `space` and
#      `live` are features this deployment does not use; their ROUTES stay in the Caddyfile, so
#      the UI is unchanged and they simply 502 if something asks for them. `beat`'s JOB is kept
#      without its process: the worker runs the scheduler (patches/worker-scheduler.py).
#   2. Caddyfile        — the AIO ships the external-S3 variant, which has no `/uploads` route.
#      With USE_MINIO=1 Plane derives both the public file URL (AWS_S3_CUSTOM_DOMAIN =
#      <WEB_URL netloc>/<bucket>) and the presigned-POST host from the request, so the BROWSER
#      talks to this host for every attachment. Without that route, uploads and avatars fail with
#      a Caddy 404 while the API reports success.
#   3. entrypoint.sh    — upstream's start.sh validates DOMAIN_NAME as a bare FQDN, so it REJECTS
#      `plane.localhost:8080` (the macOS edge is on :8080, not :80) and exits 1; and it rewrites
#      WEB_URL from DOMAIN_NAME on every boot. Ours writes plane.env from the environment and keeps
#      the two Django secrets on the data volume instead of regenerating them per container.
#   4. the frontend bundle — when PLANE_HE_WEB_URL is set (below), the Hebrew build replaces
#      upstream's static SPA. That build lives in its own repository (the AGPL `plane-he` patch)
#      because it needs a monorepo-wide Vite build this engine has no room for.
FROM makeplane/plane-aio-community:v1.4.2

COPY supervisor.conf /etc/supervisor/conf.d/supervisor.conf
# supervisorctl reads /etc/supervisord.conf by default; without this copy the documented
# `supervisorctl status` looks for an inet socket at :9001 and reports a refused connection.
RUN cp /etc/supervisor/conf.d/supervisor.conf /etc/supervisord.conf
COPY Caddyfile /app/proxy/Caddyfile

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# /app/data holds plane.env's secrets (volume-backed); /app/logs holds supervisord's program logs.
RUN mkdir -p /app/data /app/logs/access /app/logs/error

# ── it does not talk to the cloud, and this is what makes that true ─────────────────────────────
# Upstream phones home from the API entrypoint on every boot: a GitHub release check, and an
# OpenTelemetry metrics push to telemetry.plane.so gated on `Instance.is_telemetry_enabled` — whose
# model AND setup-form defaults are `True`, so a fresh self-hosted instance is opted in without
# anyone being asked. The patcher flips both defaults AND requires PLANE_TELEMETRY=1 at the two call
# sites, because a default is not a guarantee: a restored archive or a god-mode toggle would bring
# it back. Every anchor is asserted, so upstream moving a line fails the build instead of shipping
# an image that claims to be silent and is not.
COPY patches /app/patches
COPY spans.py /app/spans.py
RUN python3 /app/patches/no-phone-home.py
# The timezone half of "Hebrew defaults": every timezone field in the models defaults to UTC.
RUN python3 /app/patches/hebrew-defaults.py
RUN python3 /app/patches/redis-broker.py
RUN python3 /app/patches/hebrew-states.py
RUN python3 /app/patches/gunicorn-timeout.py
# `beat` is not one of the office's four programs, so the ONE worker runs the scheduler: without it
# none of Plane's twelve periodic jobs ran, and the API request log grew 200 MB a day for ever.
RUN python3 /app/patches/worker-scheduler.py
# …and what it logs per request is bounded too: a READ's answer (a project's whole list, 80 KB) is
# not stored a second time in the request log. A write's answer is kept.
RUN python3 /app/patches/api-log-reads.py

# ── Hebrew by default, at the SOURCE of the setting ─────────────────────────────────────────────
# The UI language is a per-USER field stored server-side (`Profile.language`, default "en"), and the
# app writes the profile's value into localStorage on every load. So a client-side default is not
# enough: the server's answer overwrites it. Measured — with the Hebrew bundle installed and
# `localStorage.userLanguage || "he"` compiled in, the app still rendered English and localStorage
# read back "en", because the profile said so. Patching the model default makes Hebrew what a NEW
# account opens in; a user who picks English in Profile settings keeps English.
#
# Guarded, not blind: if upstream moves the line, the build FAILS here rather than shipping an image
# labelled Hebrew that opens in English.
RUN grep -q 'language = models.CharField(max_length=255, default="en")' /app/backend/plane/db/models/user.py \
 && sed -i 's/language = models.CharField(max_length=255, default="en")/language = models.CharField(max_length=255, default="he")/' /app/backend/plane/db/models/user.py \
 && grep -q 'language = models.CharField(max_length=255, default="he")' /app/backend/plane/db/models/user.py \
 && echo "Profile.language default: en -> he" \
 || { echo "REFUSING: Profile.language default not found in plane/db/models/user.py — upstream moved it, and an image that claims Hebrew but opens in English is worse than no image." >&2; exit 1; }

# The Hebrew interface is a REBUILT frontend, not a setting: upstream ships the SPA as a prebuilt
# static bundle with no locale that can be added at runtime (see README.md and the `plane-he`
# repository). The two ARGs below are that build, as a release asset — public, anonymous, no
# registry login, so a private image package can never break this deploy. With them empty the
# container serves upstream's English build, which is what a fresh clone gets.
ARG PLANE_HE_WEB_URL=""
ARG PLANE_HE_WEB_SHA256=""
RUN if [ -n "$PLANE_HE_WEB_URL" ]; then \
      : "${PLANE_HE_WEB_SHA256:?PLANE_HE_WEB_SHA256 is required when PLANE_HE_WEB_URL is set}" && \
      curl -fsSL "$PLANE_HE_WEB_URL" -o /tmp/plane-web.tgz && \
      echo "${PLANE_HE_WEB_SHA256}  /tmp/plane-web.tgz" | sha256sum -c - && \
      rm -rf /app/web && mkdir -p /app/web && tar -xzf /tmp/plane-web.tgz -C /app/web && \
      rm /tmp/plane-web.tgz && echo "Hebrew bundle installed from $PLANE_HE_WEB_URL"; \
    else \
      echo "PLANE_HE_WEB_URL is empty — serving upstream's English build"; \
    fi

# ── the English that no catalogue can reach ────────────────────────────────────────────────────
# `plane-he` translates Plane through i18n, and on this deployment that catalogue is COMPLETE (0 of
# 3035 keys missing, measured against v1.4.2). What the owner still read in English — `Work Items`
# in the sidebar, `Search commands...` in the palette, `Community` on the edition badge,
# `Not started`/`Backlog` over the workload cards — are literals INSIDE the app's JavaScript, never
# passed through `t()`. Until the same edit lands in `plane-he`'s own sources (needs a push to that
# repository), it is applied to the BUILT bundle here: 641 strings, each replaced only where the code
# in front of it proves it is copy a person reads, and the build FAILS if an entry stops matching —
# a table that quietly stops applying is an office that quietly goes back to English.
RUN python3 /app/patches/hebrew-strings.py

# ── …and the patched bundle gets an address made of its own bytes ──────────────────────────────
# A patched chunk keeps the name Vite gave the source it was built from, so a browser that already
# holds that name has no reason to ask for it again — measured 2026-10-08, the owner refreshed after
# the patch above and read the same English screens. This step renames the directory to
# `assets-<hash of its contents>` and rewrites every reference to it, refusing to finish unless the
# result is consistent; the Caddyfile then serves that directory `immutable` and everything else
# `no-cache`. Last step of the build, because the hash must be of the bytes that ship.
RUN python3 /app/patches/bundle-version.py

EXPOSE 80

ENTRYPOINT ["/app/entrypoint.sh"]
CMD []
