#!/usr/bin/env python3
"""api-door-identity.py — the office's PROVED link identity is a way into Plane's token API (DGO-545).

    RUN python3 /app/patches/api-door-identity.py     (Dockerfile, build time)

Plane's external API (`/api/v1/…`, the one `apps/project-pln/tasks.py` and any agent reads) is
`authentication_classes = [APIKeyAuthentication]` (`plane/api/views/base.py`) — a token in a header,
and nothing else. That is the right rule for a stranger holding a token, and the wrong one for a
member of the office: an agent of a LINKED office has no token of ours and never will, and the way it
reaches this instance is the link's door — which has already replaced the peer's claims with the
identity this office declared for it and SIGNED that (`apps/dgo-extend/link-proxy.py`, verified by
`plane/middleware/office_identity.py`, DGO-545).

So `APIKeyAuthentication.authenticate` gains exactly one fallback: a request that a link's door signed
AND this office verified — the flag `office_identity.py` sets on the Django request, together with the
user it signed in — is answered with that user, as a valid key would be.

Deliberately not "any authenticated session": a browser's cookie does NOT open the token API (only the
app's own endpoints), because the flag is set on no other request. One link, one identity, and the
identity is a declaration of THIS office — never the peer's claim about itself.

Upstream moving that line must FAIL THE BUILD (the anchor is asserted). A silently unpatched image
answers a linked office's agent `401 {"detail":"Authentication credentials were not provided."}` with
nothing anywhere saying why — which is the state this patch exists to end (measured on vps1,
2026-10-13: the app was reachable through the link and the work items were not).
"""
import pathlib
import sys

TARGET = pathlib.Path("/app/backend/plane/api/middleware/api_authentication.py")
ANCHOR = """    def authenticate(self, request):
        token = self.get_api_token(request=request)
        if not token:
            return None
"""
PATCHED = """    def authenticate(self, request):
        token = self.get_api_token(request=request)
        if not token:
            # The office's own sign-in, for the one caller that has no token: a request that arrived
            # through a LINK, whose identity this office verified and signed in
            # (plane/middleware/office_identity.py). A browser session is not enough — that flag is
            # set on no other request — and a peer cannot forge it: the door signs with the pair's
            # own secret.
            django_request = getattr(request, "_request", None)
            user = getattr(django_request, "user", None)
            if (user is not None and getattr(django_request, "_dgo_link_identity", None)
                    and user.is_authenticated):
                return (user, None)
            return None
"""


def main() -> int:
    if not TARGET.exists():
        print(f"api-door-identity: {TARGET} is missing — the image layout changed, refusing to guess")
        return 1
    source = TARGET.read_text(encoding="utf-8")
    if "_dgo_link_identity" in source:
        print("api-door-identity: already applied (idempotent)")
        return 0
    if source.count(ANCHOR) != 1:
        print(f"api-door-identity: expected exactly one token-less return in {TARGET}, found "
              f"{source.count(ANCHOR)} — upstream moved it, and a linked office's agent must not be "
              f"left with an unexplained 401")
        return 1
    TARGET.write_text(source.replace(ANCHOR, PATCHED, 1), encoding="utf-8")
    print("api-door-identity: APIKeyAuthentication accepts the office's proved link identity")
    return 0


if __name__ == "__main__":
    sys.exit(main())
