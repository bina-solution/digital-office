# syntax=docker/dockerfile:1
#
# forward-auth — two stages, and the second one is EMPTY except for the binary.
#
# There is no `go mod download` step on purpose: the module is stdlib-only, so there is no go.sum
# and nothing to fetch. That is not a style choice — it is what makes the build work on a machine
# with no registry credentials, and what makes `GOOS=darwin go build` possible at all (see below).
FROM golang:1.23-alpine AS build
WORKDIR /src
# go.mod first, sources second: an edit to a .go file does not invalidate the module layer.
COPY go.mod ./
COPY *.go ./
# CGO_ENABLED=0 is what lets the runtime stage be `scratch` AND what lets this same source
# cross-compile to any OS from one host:
#     GOOS=darwin  GOARCH=arm64 CGO_ENABLED=0 go build -o forward-auth .
#     GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -o forward-auth.exe .
# -trimpath keeps build-host paths out of a binary that is copied into a production image.
RUN CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /out/forward-auth . \
 && CGO_ENABLED=0 go test ./...

FROM scratch
COPY --from=build /out/forward-auth /forward-auth
# By NUMBER, not by name: scratch has no /etc/passwd to name a user in, and a service whose whole
# job is deciding who may enter must not run as root. 65534 is `nobody`, the uid the kernel reserves.
USER 65534:65534
EXPOSE 9000
# A scratch image has no shell and no wget, so the healthcheck is the binary asking itself. This is
# why `-health` exists at all rather than a `wget -qO-` line.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["/forward-auth", "-health", "http://127.0.0.1:9000/healthz"]
ENTRYPOINT ["/forward-auth"]
