# Contributing to DGO — the digital office

[עברית](CONTRIBUTING.he.md)

Thank you for wanting to help. DGO is an open, self-hosted office for small businesses: a core every office gets, and
apps an office chooses, each one a container compiled from a declaration. A contribution can be a fix, a new app, a
translation, a screen, documentation, or a well-written bug report.

## Before you start

- **Read [AGENTS.md](AGENTS.md).** It is the short entry file for people and for AI coding agents: the layout, the
  rules every change keeps, and where to read next.
- **Run an office locally.** On Debian/Ubuntu: `DGO_LOCAL=1 ./debian-install.sh`, then `./bbox run`, then open
  `http://console.localhost`. On a Mac `./bbox run` sets up its own engine; on Windows use `bbox.cmd run` (WSL).
- **Open an issue first for anything larger than a small fix**, so we can agree on the shape before you write it.

## Making a change

1. Fork the repository and create a branch.
2. Keep the change to one subject. A new app lives in its own folder under `apps/` with an `app.json`; start from
   [ai/context/build-your-first-app.md](ai/context/build-your-first-app.md) and the CLI/API standard in
   [ai/context/app-cli-api-standard.md](ai/context/app-cli-api-standard.md).
3. Prove it on real output: run the office, use the screen or the command you changed, and say in the pull request
   what you ran and what it answered.
4. Run the tests near your change (each app keeps its tests beside its code; Go tests under `packaging/dgo`:
   `go test ./...`) and the structural gates: `python3 scripts/refactor/run-gates.py --all`, before and after your
   change. A gate that was red before you started is not yours; one you turned red is. What each gate scans is in
   [scripts/refactor/GATES.md](scripts/refactor/GATES.md).
5. Open a pull request using the template. Say whether an AI tool helped write it — that is welcome; a person still
   answers for every line.

## How a pull request reaches a release

This repository is the published copy of the project's development line: each release replaces it with a fresh,
cleaned snapshot, so a pull request is never merged here directly. An accepted one is carried by a maintainer into the
development line and comes back with the next release; the pull request is then **closed, not merged**, with a note
naming that release, and the release notes credit you. Expect a review first, and possibly a request for changes.

## Style

- Code, commit messages and documentation are in English. The screens speak the office's language — Hebrew first,
  right-to-left, and English — and text a person reads goes through the office's language files
  ([ai/context/platform-language.md](ai/context/platform-language.md)).
- Only `platform-base/bina-ui/theme-tokens.css` names a colour; screens use its tokens.
- Declarations over scripts: a service, route or setting goes into an app's `app.json` or compose file and is compiled
  into `.generated/`, which is never edited by hand. Never run `docker compose` directly — use `./bbox` or
  `./scripts/dc`.
- Commit messages say what changed and why, in a sentence a reader understands without the diff.

## Reporting

- **A bug or an idea:** open an issue with the matching form.
- **A security problem:** never in public — see [.github/SECURITY.md](.github/SECURITY.md).
- **Conduct:** see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

By contributing you agree that your contribution is licensed under the project's licence, the
[GNU AGPL v3](LICENSE).
