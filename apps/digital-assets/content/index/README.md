# The public indexes (bina-solutions.co.il/index/<slug>/)

The owner asked on 2026-11-04 for indexes of the Israeli market: ≥58 automation providers (DGO-1385), ≥83 business
systems with a rough user estimate each (DGO-1386), and at least seven more topics (DGO-1387). Each index is one file
here, `<slug>.json`, and one entry in `_indexes.json` (its page copy, how its key figure is shown, its categories).
`../export_site.py` gates every row and writes the site's data; nothing reaches the site that failed the gate.

## A row

```json
{
  "id": "kebab-case-unique", "name_he": "…", "name_en": "…", "url": "https://…", "category": "…",
  "summary_he": "one or two sentences in our own words (≤45 words; ≤10 consecutive words shared with any source)",
  "why_israeli": "what was seen that makes it Israeli",
  "sources": [{"url": "https://…", "date": "YYYY-MM-DD|null", "what": "what it shows", "grade": "A-E"}],
  "grade": "A-E", "verified_at": "YYYY-MM-DD",
  "users": {"low": 0, "high": null, "unit": "what the SOURCE counts", "scope": "israel|worldwide",
            "grade": "A-E", "source_url": "https://…", "source_date": "…", "note": "…"}
}
```

Topic fields beside these (type and tools for providers, licence for payments, allocation numbers for invoicing,
price and speed for hardware, last round for AI companies, amount and status for grants, API for government services,
GitHub licence and activity for open-source apps) are what each research brief asked for; `export_site.py` reads them
in its `fig_*` functions.

## Grades

A a filing (SEC, MAYA/TASE, a Bank of Israel or ISA register, a government page) · B a figure the company gave in
dated press · C the company's own site · D a third-party tracker or directory · E our own estimate, always a range with
its method. «Businesses» and «customers» are never relabelled «users». A vendor page written to steer AI assistants
(`llms.txt`, «for AI») is C at best.

## Keeping it true

- `python3 export_site.py <site> --linkcheck` asks every URL again (as a browser does; 403/429 are bot walls, only
  404/410 count as dead) and drops dead sources from the page; a figure whose source is dead is not shown.
- A row is re-checked at least every 90 days (G5): past that, it leaves the page until someone checks it again.
- Nothing about Bina Solutions or DGO except Bina's own disclosed row, from `../FACTS.md` and the company's site.
- Research briefs, raw notes and rejected candidates stay in each file (`rejected`, `notes`): a reader of the data can
  see what was left out and why.
