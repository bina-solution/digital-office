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
