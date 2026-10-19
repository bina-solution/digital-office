# archify — draw the office, from sources kept in git

**What it is for.** When somebody asks "how does X work here" — the link between two offices, an
app's bring-up, where a request goes — the answer is a DIAGRAM, and it is kept: a JSON source in
`apps/archify/diagrams/`, rendered by Archify into a self-contained page that every office (and every
linked office, through its tile) can open under "ארכיטקטורה".

**The source is the diagram.** Never hand-edit a rendered page and never keep a diagram outside the
repository. One file per diagram, named `<name>.<type>.json`, where the type is one of:

| type | answers | its arrays |
|---|---|---|
| `architecture` | what exists and what talks to what | `components` (with `pos`, `size`), `boundaries`, `connections` |
| `sequence` | who asks whom, in order | `participants`, `messages` (each with a `y`), optional `segments`, `activations` |
| `workflow` | the steps of one job, with branches | `lanes`, `phases`, `nodes`, `edges`, `mainPath` |
| `dataflow` | where data comes from and lands | `stages`, `nodes`, `flows` |
| `lifecycle` | the states a thing moves through | `lanes`, `states`, `transitions` |

Every file starts `{"schema_version": 1, "diagram_type": "<type>", "meta": {"title": …, "output":
"<name>.html"}}`. Unknown fields are REFUSED, not ignored. Copy the nearest existing file in
`diagrams/` and change it — that is faster and safer than writing one from the schema.

**The loop.**

```bash
./bbox archify validate            # every source, with the validator's own sentences; exit 1 if any fails
./bbox archify validate app-move   # one diagram
```

Then open the tile (or `GET http://archify:8080/api/diagrams`): a source that validates is rendered
the next time anyone looks; one that does not shows a card that says why. There is nothing to
restart and nothing to publish.

**What the validator insists on** (each of these was hit writing the first diagram):
- labels must FIT their boxes — a sequence with long participant names needs
  `"column_fit": "spread"` in `meta`;
- a `showcase` diagram may be at most 1085 wide (`meta.viewBox: [1080, 900]` is safe);
- `id`s are `^[a-zA-Z][a-zA-Z0-9_-]*$`; `meta.output` is a relative `.html` path.

**Say what was measured.** A diagram here is read as a statement about THIS office. Draw what the
code and the running system do (name the file or the command in a `cards` item when it helps), not
what a design once intended; when the system changes, change the source in the same commit.

**Not here:** the rendered pages (they are made at start, in the container), and anything secret —
a diagram is opened by every linked office that is given this app.
