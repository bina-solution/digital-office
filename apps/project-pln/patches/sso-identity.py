#!/usr/bin/env python3
"""sso-identity.py — wire the office's own sign-in into Plane's middleware chain (DGO-371).

    RUN python3 /app/patches/sso-identity.py      (Dockerfile, build time)

The module itself is a file of this app (`office_identity.py`, COPYed to
`/app/backend/plane/middleware/office_identity.py`); this patch is the ONE line that makes Django
call it — inserted directly after `AuthenticationMiddleware`, because `request.user` has to have been
filled from the session before the middleware may decide to fill it itself.

Upstream moving that line must FAIL THE BUILD. Silently shipping an image whose middleware list no
longer carries this entry would look exactly like success — a healthy container, a served SPA, and
the office's sign-in asked for a second time — which is the state this change exists to end.
"""
import pathlib
import sys

SETTINGS = pathlib.Path("/app/backend/plane/settings/common.py")
MODULE = pathlib.Path("/app/backend/plane/middleware/office_identity.py")
ANCHOR = '    "django.contrib.auth.middleware.AuthenticationMiddleware",\n'
ENTRY = '    "plane.middleware.office_identity.OfficeIdentityMiddleware",\n'


def main() -> int:
    if not MODULE.exists():
        print(f"sso-identity: {MODULE} is missing — the image layout changed, refusing to guess")
        return 1
    if not SETTINGS.exists():
        print(f"sso-identity: {SETTINGS} is missing — the image layout changed, refusing to guess")
        return 1
    source = SETTINGS.read_text(encoding="utf-8")
    if ENTRY in source:
        print("sso-identity: already wired (idempotent)")
        return 0
    if source.count(ANCHOR) != 1:
        print(f"sso-identity: expected exactly one {ANCHOR.strip()} in {SETTINGS}, "
              f"found {source.count(ANCHOR)} — upstream moved it, and an image that asks the owner "
              f"to sign in twice is worse than no image")
        return 1
    SETTINGS.write_text(source.replace(ANCHOR, ANCHOR + ENTRY, 1), encoding="utf-8")
    print("sso-identity: OfficeIdentityMiddleware wired into MIDDLEWARE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
