# The office's language

One variable decides the language of everything a person reads in the office: the console's rail,
every tile, and every app's own screens. This file is the contract for it — what declares it, who
writes it, how a UI reads it, and the four traps that make a half-translated screen.

> **What is in this tree today (DGO-971, 2026-11-10).** This file and its runtime were built on the EXW
> tablet office's line (`exw-wtablet-dgo`, tip fdfa8b23). They come to the release by PATH, one slice at a
> time, because the console and the app pages have moved on since then, so a cherry-pick is not clean.
> - **Landed:**
>   - the runtime's source, `platform-base/bina-ui/bina-lang.js`, byte-identical to the branch's;
>   - the report `scripts/refactor/lang-coverage.py` (not a gate: run-gates.py `NOT_A_GATE`);
>   - the fact (slice 2): `language:` in platform.state.yaml, `reconcile.LANGUAGES`, `state_language()`,
>     `language_errors()` (a code no dictionary has is refused by name, first among validate's lines),
>     and the compiled `.generated/registry/locale.json`, by reconcile.py and its Go twin alike
>     (packaging/dgo/internal/compiler/language.go, held byte for byte by the parity tests);
>   - its first reader (slice 3): the console's `_locale()` (re-read when the file changes),
>     `GET /api/language`, and `<meta name="bina-lang">` at the start of every page it frames
>     (`_inject_lang`: never before a doctype). Nothing in this tree sets a per-browser language, so the
>     meta changes nothing a person sees today;
>   - its writer (slice 4): `reconcile.set_language()` (under the state's lock, every comment kept),
>     `reconcile.py lang [--lang CODE --by WHO]`, `bbox lang [he|en]`, app-management's
>     `POST /api/language` (a linked caller refused, G85) and the console's POST, which carries a switch
>     to it.
> - **Already here before it:** «קבצים» (apps/drive) carries the same runtime as a copy
>   (`apps/drive/static/bina-lang.js`, byte-identical; ab702545). It loads it from its page, and `L()`
>   appears on about 460 lines of its `static/js/` (through a wrapper in `core.js`). Gate G27 keeps that
>   copy byte-identical to the source now (`VENDORED_COPIES` in theme-token-lint.py: a whole-file copy,
>   the branch's `LANG_TARGETS` in the form this tree already has). No page in this tree has a
>   `data-lang-*` pair.
> - **Not yet here:**
>   - the shell's own `<html lang dir>` (`_apply_html_lang`; the Go console serves the shell too, so both)
>     and a framed page's direction: display changes, so they come as a mock first. The branch's
>     version replaced the whole `<html>` tag, which drops a page's other attributes;
>   - the console's `modName` / `modDesc` / `officeLabel` / `GROUP_EN`, and the compiled `desc_en` (the
>     console reads `m.desc_en` today, and it is empty);
>   - the switcher (its mock is on DGO-971, waiting for the owner's pick);
>   - the copy inlined into `connections` (a marked region, the branch's `LANG_TARGETS`);
>   - the other pages' pairs and `L()` calls.
>   Each is a slice of DGO-971. The switcher is a display change, so it comes as a mock first. Until a
>   slice lands, the sections below describe the branch, not this tree.

## The fact, and where it lives

```yaml
# platform.state.yaml
schema_version: 1
language: en          # he | en
```

* **Declared** there, and there only. `reconcile.validate()` refuses a code the platform has no
  dictionary for, so a typo (`eng`) fails the compile instead of rendering a shell with no strings.
* **Compiled** by `reconcile render` into `.generated/registry/locale.json`:

  ```json
  {"active": "en", "default": "en", "dir": "ltr",
   "available": [{"code": "he", "label": "עברית", "label_en": "Hebrew", "dir": "rtl"},
                 {"code": "en", "label": "English", "label_en": "English", "dir": "ltr"}]}
  ```

  `available` is what a switcher renders — never a hardcoded pair in a UI.
* **Written** by `reconcile.set_language()` and by nothing else (gate G33). Two doors reach it:
  `./bbox lang <he|en>` from a terminal, and the console's switcher, which POSTs to
  `app-management`'s `/api/language` (the control plane owns desired-state writes; the layer-2 shell
  does not mount the repo). `reconcile.py lang` with no argument prints the current value.
* **Read** per request by the console (`.generated/registry/locale.json`, mtime-cached — a switch
  needs no restart) and by every app, in the browser.

## Switching it

| Where | What happens |
|---|---|
| Console top bar, beside the account chip | POST → `app-management` → `reconcile.py lang` + `render` → the shell reloads |
| `./bbox lang en` | the same write, no HTTP involved |
| `language:` in `platform.state.yaml` | the declaration itself; `render` picks it up |

No container is restarted. A language is a property of the office, not of a running process: the
render rewrites one compiled file, and each surface reads it when it next loads.

## How a UI reads it — `platform-base/bina-ui/bina-lang.js`

Vendored into each surface as `bina-lang.js` (or inlined for `connections`, which serves its page
from a Python string and has no static route). Gate G27 keeps every copy byte-identical to the
source: add a surface to `LANG_TARGETS` in `scripts/refactor/theme-token-lint.py`, and copy the
marked region.

It resolves the language in this order, first hit wins:

1. `?lang=xx` in the URL;
2. `<meta name="bina-lang" content="xx">` — **what the console injects into every app it frames**
   (see below), which is why a framed app needs no cookie, no fetch and no CORS;
3. `localStorage["bina.lang"]` — so an app opened on its own host remembers the last switch;
4. the document's own `<html lang>`;
5. `he`.

It publishes `window.L(he, en)` (and `BinaLang.pick`, the same function) and sets `<html lang dir>`.

### Two ways to put a string in both languages

```html
<!-- static markup: the Hebrew stays as the source text, English rides beside it -->
<button data-lang-he="רענון" data-lang-en="Refresh">רענון</button>
<!-- for an attribute rather than the element's text -->
<input data-lang-attr="placeholder" data-lang-he="חיפוש" data-lang-en="Search" placeholder="חיפוש">
```

```js
// a string built in JavaScript — there is no element to carry two attributes
el.textContent = L("אין תוצאות", "No results");
```

Elements added later by a renderer are translated too: a MutationObserver applies the attributes to
new subtrees. That is deliberate — the alternative is calling `apply()` after every `innerHTML`
assignment, and the one place somebody forgets is a screen that stays Hebrew in an English office.

## What the console does for the apps it frames

`/a/<alias>/` serves the app's HTML through `console/app.py`, which:

* rewrites the `<html>` tag with the office's `lang`/`dir` (`_apply_html_lang`) — server-side, because
  the direction IS the layout and a page that flips after a fetch paints one full frame wrong;
* injects `<meta name="bina-lang">` (`_lang_meta`), which is the runtime's second resolution step.

An app that is opened on its own host (`computers.localhost`) gets neither. Steps 3–5 above cover it.

## Tiles: where an app's name comes from

A tile carries four strings, all derived at compile time, none declared twice:

| Field | Source |
|---|---|
| `name` | `routing[].module.name` (Hebrew, authored) |
| `name_en` | `title.en` from app.json |
| `desc` | `routing[].module.desc` (Hebrew, authored) |
| `desc_en` | `summary.en` from app.json |

The shell reads the pair with `modName(m)` / `modDesc(m)`. A remote app's tile carries the same pair
plus `label` (`{he, en}` — the office's own name), read with `officeLabel()`. Group headings are the
one thing the shell translates itself: `module.group` is a four-value enum, so `GROUP_EN` in
`console/static/app.js` owns their English.

**A module's Hebrew name is what an English shell shows if app.json declares no `en`** — no blank
row, and no translation table in the shell.

## Adding a language

1. A row in `reconcile.LANGUAGES` (`label`, `label_en`, `dir`).
2. A row in `bina-lang.js`'s `DIRS` and dictionary code.
3. That is the compile half. The UI half is the copy: every `data-lang-*` pair and every `L(he, en)`
   call is a two-language fact, so a third language means revisiting them (or moving to keyed
   dictionaries). The switcher itself needs no change — it renders whatever `available` says.

## Traps

* **Never translate a data value.** `m.group` is compared against `"ראשי"`; a status string from
  `/api/computers` is compared against `"ok"`; a form value is sent to a server. Translate the
  DISPLAY, never the value. The test: *if I change this, does a comparison or a request break?*
* **`data-lang-*` is for static markup only.** On text a renderer produces, the runtime has nothing
  to fall back to if the attribute is missing, and an attribute written into a template literal is
  harder to read than `L(...)`.
* **A switch reloads the shell.** Not a live repaint: the rail, the headings, the tiles and the framed
  app all read the language at render time, and repainting only what the shell holds references to
  leaves half a screen in the old language.
* **Two surfaces carry their own language, by design.** The office agent (`bina-ds`) is a DeepSeek
  Harness whose locale is its own user setting (`$DSH_HOME/settings.yaml`, `locale.preference`) —
  its Settings → General → Language row. And Obsidian's UI language is Obsidian's own setting in its
  own config; the vault is mounted into that app, not managed by this one. Everything else follows
  `language:`.
