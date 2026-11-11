# docs/ — the DGO documentation (docs.digital-office.co.il)

The documentation site of הלשכה הדיגיטלית DGO, Hebrew first (DGO-1788). [Starlight](https://starlight.astro.build)
on Astro; the pages are Markdown under `src/content/docs/he/`, one file per page, and the sidebar is the map in
`astro.config.mjs`. Agents read it too: every page has a Markdown twin (`<page>.md`), and the build writes
`llms.txt`.

## Layout

| Path | What it is |
|---|---|
| `src/content/docs/he/` | the pages (Hebrew). English falls back to Hebrew until an English page exists. |
| `astro.config.mjs` | the site: its name, locales, sidebar, and two Markdown plugins: `withBase` (the preview's path prefix) and `shotPlaceholders` (a `![…](TODO-shot: …)` still to be made shows as a marked box) |
| `src/styles/olive.css` | Starlight's colours mapped onto the office's one palette. `scripts/docs/pack.sh` copies `platform-base/bina-ui/theme-tokens.css` in at build time; no colour is written here. |
| `src/routeData.ts`, `src/pages/` | the Markdown twins and their `<link rel="alternate">`; the root redirects to `he/` |
| `public/diagrams/` | the diagrams, made by `diagrams/make.py` with the palette read from `theme-tokens.css` (`python3 diagrams/make.py`) |
| `public/shots/` | screenshots. They come from a fresh DEMO office only (`shots.yaml`: what each one shows, its size and state), never from a client's office and never with a real person's name, mail or address. A PNG goes public only when `scripts/release/public/binaries.txt` names it, in the same commit (the export holds every other binary back); an SVG is text and goes out as is. |
| `scripts/docs/` (outside this folder) | the build — `pack.sh` (an allow-list) → `build-on-vps1.sh` (node 24, `npm ci` from the lockfile, under vps1's heavy lock) → `build-and-check.sh` (the `sites` app serves it, every link is checked) — and `shots.sh` (review screenshots of a built tree). They name the office's servers, so they stay out of the documentation's own folder. |

## Build and preview

The Mac never builds (AGENTS.md: the Mac is the command centre). From the repository root:

```bash
bash scripts/docs/build-and-check.sh <n>      # in the background; 3–6 minutes
```

It builds on vps1 for the preview behind the office's sign-in, at
`https://console.staging.digital-office.co.il/a/sites/public/dgo-docs/he/`, and prints
`<pages>; <links>; 0 bad; placeholder boxes: <n>`. `DOCS_BASE=/` builds for docs.digital-office.co.il itself.

## Before it is public

- Every `TODO-shot` box is a picture still to be made (`shots.yaml`); a public build carries none.
- Three `TODO-product` notes mark what the product has no written answer for yet (a Linux or Windows office with no
  domain has no address). They belong to the release line, and the pages do not paper over them.
- The name: always «הלשכה הדיגיטלית DGO» — the Hebrew name with its mark, since a government service has the same
  name (the owner, DGO-1802).
- Facts are checked against the code before a page changes. The first twelve pages were checked claim by claim
  (227 claims, 38 wrong, all corrected); the second twelve carry a source `path:line` per claim.
