# platform/profiles — optional compose overlays

Not apps and not services: cross-cutting *modes* layered onto the generated compose with `-f`.

* `ci-images.yml`      — pin prebuilt GHCR images instead of building from source (CI)
* `connections-mode.yml` — boot consumers through the credential plane's injector
* `perf-profiles.yml`  — host-size profiles (applied by scripts/perf-profile-apply)

They live under platform/ rather than in an app because no single app owns them.
