# syntax=docker/dockerfile:1
#
# dgo-carry — WireGuard's TCP path (main.go). Two stages, and the second one is EMPTY except for the
# binary, like platform-base/forward-auth: the module is stdlib-only, so there is no go.sum and
# nothing to fetch, and CGO_ENABLED=0 is what lets the runtime be `scratch` and lets the same source
# build for any OS (`GOOS=darwin|windows go build .`).
# The build stage runs on the BUILDING machine's own platform and cross-compiles to the image's
# (TARGETOS/TARGETARCH, BuildKit's), as forward-auth's does: an arm64 image made on an x86 machine (the
# Android guest) compiles and tests natively, not under QEMU. Built for its own platform, the same.
FROM --platform=$BUILDPLATFORM golang:1.23-alpine AS build
ARG TARGETOS TARGETARCH
WORKDIR /src
# go.mod first, sources second: an edit to a .go file does not invalidate the module layer.
COPY go.mod ./
COPY *.go ./
# The tests run HERE, on every build: they drive real sockets on loopback (a handshake, a datagram
# both ways, a dialer that comes back, a dialer that searches), so an image that exists is one whose
# path was proved on the machine that built it.
RUN CGO_ENABLED=0 GOOS="${TARGETOS}" GOARCH="${TARGETARCH}" go build -trimpath -ldflags "-s -w" -o /out/dgo-carry . \
 && CGO_ENABLED=0 go test -count=1 ./...

FROM scratch
COPY --from=build /out/dgo-carry /dgo-carry
# The roots a pair that rides another office's HTTPS door verifies that door's TLS with (ws.go). From
# the build stage's own bundle — which, built in a cloud sandbox, already holds the sandbox proxy's CA
# (scripts/lib.sh shadows every base with it); DGO_CARRY_CA adds one at run time anywhere else.
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
# ROOT on purpose, with every capability dropped in compose: the one secret it reads is the office's
# WireGuard key in the tunnel volume (`wg-private.key`, root's, 600), and the one file it writes sits
# next to it. A scratch image has no shell and no other binary to hand anybody.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["/dgo-carry", "-health"]
ENTRYPOINT ["/dgo-carry"]
