# io — the Digital Office mark

- **`i`** is the person: the dot is the head, the line is the body.
- **`0`** is the system that wraps every business need.
- **The half line inside it** is the apps.

It reads `i0`, binary 1·0.

## The construction

- **Anchor grid.** Four anchors across and four up, equally spaced, so the grid is perfect squares.
  In modules both ways they are 0 · 2 · 4 · 6. The mark is 1:1.
- **Stroke.** Stroke = every gap = 1 module.
- **Where the parts sit.**
  - The i's body runs y1–y3, and its head's top is y4.
  - The o spans x2–x4 and y1–y4.
  - The apps line stands on x3 from y2 to y3.

## The versions

`versions/001.svg … 100.svg` are 100 square icons, ranked by
[beautiful](https://github.com/solomonBoltin/beautiful) `--mode=logo`, which includes its
curve-repetition factor. Every one is measured on its Chrome render (see `scores.csv`):

- black area = white area;
- ink left of centre = ink right of it, and ink above = ink below: the mark sits on the point that
  halves its ink both ways;
- an exact score of 95.00 or more.

Each version records its radii in modules: caps, o outer/inner and tile. When they repeat one radius
(or a concentric offset of it), the curves factor is 1.00.

## Files

- `sheet.png` shows all 100; `top12.png` shows the best twelve.
- `construction.png` is #1 on its anchor grid.
- `tools/` holds:
  - `iomark.py`: the geometry, raster and SVG;
  - `search3.py` and `search4.py`: score every factor combination; `search4.py` sweeps the
    halves-centred space;
  - `finalize4.py`: picks 100 diverse versions, re-renders them in Chrome, re-checks each one (exact
    score ≥ 95, black = white, ink 1:1 both ways) and draws the sheets;
  - `construction.py`.

## Regenerate

Needs `pip install git+https://github.com/solomonBoltin/beautiful` at a version that has `curves.py`.

```bash
python tools/search3.py && python tools/search4.py && python tools/finalize4.py out
```

## The chosen mark

The chosen mark is version 7's geometry: square anchors; caps, o and tile all on one ½-module radius.
It is drawn in the old icon's colours and radii (measured in `beautiful/demo/logos/bina_final.py`):
- tile `#1b5e4a`, corner radius 22 % of its side;
- ink `#fbfcfc`;
- mint `#7ecfad` on the head and the apps;
- every stroke end at 0.27 × the stroke.

One drawing, two colourways, each used on the surface it contrasts with:

| file | colourway | use it on |
|---|---|---|
| `final/logo-1.svg` (also `final/favicon.svg`) | green tile, white i0, mint | light surfaces: site header, favicon, app icon |
| `final/logo-15.svg` | white tile, green i0, mint | dark surfaces: console sidebar, desktop bar, site footer |

- **In the console:** `platform-base/console/static` draws the sidebar and desktop-bar mark inline and
  serves `favicon.svg` (#1's drawing) — the same GEOMETRY, in the office's palette since 2026-10-07
  («Olive Grove», `platform-base/bina-ui/theme-tokens.css`): the tile is olive (`--olive`), the i0 is
  what is written on olive (`--olive-ink`), the head and the apps are lime (`--lime`) — three tokens
  that are the same on the light ground and on the dark one, so the mark is one mark; inline it names
  them, the favicon file writes their values. The files in `final/` and the previews keep the
  colourway the mark was designed in (the three values above) — they are its record, and whatever is
  drawn outside the office (the site).
- **Previews:** `final/previews/` holds the console, the site header and the site footer.
- **Versions:** `final/oldstyle-versions.png` shows the 20 versions this pair was chosen from; the
  tools are `tools/oldstyle.py` and `old_render.py`.
