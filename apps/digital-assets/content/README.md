# The content library

Everything the business writes for the world, as files a writer (person or agent) works in. One
command makes each file the business's, in digital assets.

```
content/<type>/<slug>.<lang>.md      ← a piece: YAML front matter + the Markdown body
        │  ./bbox digital-assets content [--dry-run] [--activate] [<type>/<slug> …]
        ▼
slot content.<type>.<slug>-<lang>    ← one slot per piece, born under the blueprint content-<type>
  └─ versions                        ← one per changed file (its sha256 kept in meta); drafts until activated
       └─ active                     ← what the sites show (they read the bundle)
```

| File | What it is |
|---|---|
| [BRIEF.md](BRIEF.md) | The writer's brief: the reader, the Israeli author's voice, research minimums, the nine types and their lengths, media and link placeholders, the front matter, and the checklist. |
| [FACTS.md](FACTS.md) | The only things a piece may say about DGO, as of the release. Change a fact here first, then re-check the pieces. |
| [assignments.yaml](assignments.yaml) | Every piece the library is to hold: 35 flagship articles, 231 project profiles in 21 categories, and 77 more (tutorials, comparisons, directories, news, reports, glossary). Each entry names its Plane work item. |
| `linkmap.py` + [linkmap/](linkmap/) | The link map (DGO-793): who links to whom between digital-office.co.il, bina-solutions.co.il and the public repository, and since when. Every sitemap page and the README are read; each link keeps the day it was first seen, or the day it went. `linkmap/LINKS.md` names pages with no link to the other site and links to the repository's old private address. Run it after every publication. |
| `layer_gate.py` | The gate between the SEO layers (DGO-664): `--layer 1` (the map: every list exists, is sourced, checked within 91 days, and has its place on the site), `--layer 2` (every planned piece written and clean in the quarterly check), `--layer 3` (media: closed until layer 2 passes). Item by item, exit 1 until the layer is perfect. |
| `recheck.py` + [rechecks/](rechecks/) | The quarterly check (DGO-817). Every written piece goes through the same list: its links still answer, FACTS.md is not newer than it, it is due 91 days after its own date, its sources were opened within a quarter, every price carries its year, and every «משרד» is read by a person. `--write` keeps the result as `rechecks/<year>-Q<n>.md`; the reading of the DGO lines against FACTS.md is added there by hand. It never edits a piece. |
| [interfaces.yaml](interfaces.yaml) + `interfaces.py` + [interfaces/](interfaces/) | The monthly check of the interfaces the library and the office lean on (DGO-812): tax authority, gov.il identity, Bank of Israel, ביטוח לאומי, the companies registrar, WhatsApp, Morning, retailers. One GET each; the state (ok, blocked to a robot, gone), the address, a page's title and headings, an API's shape and never its values; `interfaces/<YYYY-MM>.md` says what changed since the last month. |
| [topics.yaml](topics.yaml) | The topics log (DGO-818): every new subject, in the words it was said in (the owner, a user, a Search Console query), until it is a work item or declined with its reason. `topics.py` lists the open entries; `topics.py --check` keeps the log's rules. |
| `render.py` | Files → JSON. Runs on the host, where the YAML library is. It refuses a file whose front matter disagrees with its path. |
| `importer.py` | JSON → digital assets, idempotent. Runs inside the app's container, against its own API. |
| `../hooks/content` | The verb that joins the two. |

The **types** are blueprints in `../blueprints/content-*.yaml`. Each one extends `content-library`:

| Blueprint | What it holds |
|---|---|
| `content-article` | in-depth articles |
| `content-project` | project profiles |
| `content-tutorial` | tutorials |
| `content-comparison` | comparisons |
| `content-directory` | directories |
| `content-news` | news |
| `content-report` | reports |
| `content-post` | posts |
| `content-glossary` | glossary |

A blueprint declares the type — its hub slot, its shape and its rules — and never lists the pieces.
A new article therefore needs no new image. The importer creates the piece's slot through
`POST /api/slots` with `blueprint: content-<type>`, and the screen then shows where the piece belongs.

**Placeholders.** Media and links are placeholders that the site's renderer resolves:
- `[[image: …]]`, `[[screenshot: …]]`, `[[diagram: …]]`, `[[video: youtube | …]]`, `[[icon: …]]`
- `dgo://<type>/<slug>` links between pieces
- `:::dgo` / `:::tip` / `:::warning` boxes

The media layer comes after the text layer is complete (SEO · 9 in the Plane project DGO).
