# Engine binding contract — how to wire a fragment to `window.DO`

You are wiring static HTML screens in `digital-office/tooling/frag/*.html` to the live mock engine
defined in `digital-office/tooling/index.base.html`. **Only add `data-*` attributes** (and, when a
static repeated list must become live, replace the repeated rows with ONE container carrying
`data-list`/`data-row`). **Never change layout, CSS, geometry, text labels, or markup structure** —
fidelity to the real screenshots is graded pixel-by-pixel. When in doubt, bind less, keep markup identical.

## Binding hooks (all handled by the engine, event-delegated — you just add attributes)
- `data-bind="EXPR"` — sets the element's textContent to the live value of EXPR. Add `data-tick` to flash on change.
- `data-list="EXPR" data-row='<tpl>'` — EXPR must resolve to an array; the engine renders one row per item
  by substituting `{{key}}` from each item (and `{{i}}` = 1-based index). Put it on the `<tbody>` (for tables)
  or a wrapping container. The `data-row` template MUST reproduce the EXISTING row markup exactly (same
  classes/inline styles/columns) — just swap the hard-coded values for `{{key}}`.
- `data-open="KEY"` / `data-close` — open a built-in modal / close the topmost overlay.
- `data-action="NAME"` — run engine action NAME on click. Extra data comes from the element's `data-*`
  (e.g. `data-action="selectFolder" data-folder="gdoc"` → runs `selectFolder({folder:'gdoc', ...})`).
- `data-drag="file:ID"` (+ `draggable="true"`) and `data-drop="folder:ID"` — drag a file onto a folder
  moves it (`moveFile`). The `file:`/`folder:` prefixes are required.
- `data-menu` (left-click) / `data-ctx` (right-click) — attach a generic context menu to a row.
- `data-tab="PANE"` inside `[data-tabs]`, with `[data-pane="PANE"]` targets — tab switching.

## EXPR grammar (what `DO.val(expr)` resolves)
Dotted paths into `DO.state` (numbers auto-formatted he-IL). Plus computed keys:
`clock`, `sync`, `revenue`, `mail.unread`,
`ix.total|completed|review|progress|failed|companies|repos|pct|pctL`,
`drive.current` (files in selected folder), `drive.selName`, `drive.count`, `drive.trashN`.
If you need a new computed key, DO NOT add it — tell the orchestrator in your final report instead.

## Live state shapes (read-only reference — key names matter)
```
mail: [{id,from,subj,when,unread:bool,tag}]            // newest first; unread flips via openMail/readAll
drive.folders: [{id,name,sync,syncL}]                   // ids: gdoc, gdoc2, bs
drive.files:   [{id,folder,name,kind:'pdf'|'xls',size,status,statusL,when}]
drive.sel: '<folderId>'   drive.trash: []
infra.machine: {cpu,mem,disk,up, containers:[{name,state,cpu,mem}]}
infra.conc:    {running,queued,done, spans:[{name,pct,state:'run'|'done'|'queued'}]}
infra.kabil:   {lanes:[{name,n}]}
infra.bot:     {state,stateL,users,sessions,msgsToday}
notifications: [{id,kind:'ok'|'warn'|'err',text,when}]
customers/items/documents: already live (see mydocs frags for the pattern)
```

## Actions you may trigger via `data-action`
`selectFolder{folder}`, `uploadFile`, `trashFile{file}`, `moveFile{file,to}` (usually via drag),
`openMail{mail}`, `readAll`, `addDocument`, `addCustomer`, `addItem`, `markNotifsRead`.
Open built-in modals with `data-open="new-doc"|"new-customer"|"new-item"`.

## Worked examples (copy these patterns)
Table already wired — `frag/indox-repo-docs.html`:
```html
<tbody data-list="indox.incoming" data-row='<tr><td><input type="checkbox"></td><td class="idx">{{i}}</td><td>{{date}}</td><td>{{name}}</td>...<td><b style="color:var(--green-d)">{{did}}</b></td></tr>'></tbody>
```
Bound stat — `frag/indox-root.html`:
```html
<div class="n" data-bind="ix.completed" data-tick>0</div>
```
Button opening a modal — `frag/mydocs-docs.html`: `<button ... data-open="new-doc">+ מסמך חדש</button>`

## Build / verify (orchestrator runs this; you do NOT need to)
Edit frags → `cp tooling/index.base.html tooling/index.html` → `node tooling/assemble.js` →
`cp tooling/dist.html platform-mockup.html` → `python3 verify/render_mock.py` → `python3 verify/ui_map_diff.py`.
