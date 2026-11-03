# cad-api — products as digital replicas, and what it takes to make them

What it is for: a product the office makes (a chimney cap, a fence, a gate) is a parametric model: the
job's own sizes and options in, and out come the pieces to cut, how they sit on stock sheets, the bill of
materials (sheets, mesh, rivets, caulk, hours), the cost and the 3D file. A size is never a new product.

Doors, at `http://cad-api:8996` inside the office:
- `GET /api/caps` — the gallery's caps (pan, standard, pitched, bell, cube, chase, tee, turtle, bishop):
  their parameters and where each rule came from.
- `POST /api/caps/<style>/quote` with a job — `{"cap_spec": {…}}` exactly as the services app stores it,
  or `{"params": {"L": 30, "W": 20, …}}`, plus `material`, `gauge`, `sheet: {w, h}` (the caller's stock),
  `price_list` → `parts` (blank, bends, rivets, mesh), `sheets` (placed), `bom` (sheets, sheet_fill, mesh,
  rivets, caulk, hours + why), `cost` (each line with its source; whole sheets and the used share),
  `notes` (every ASSUMED rule). Read-only, ~0.1 s.
- `POST /api/caps/<style>/model?format=step|glb` → the cap folded, in inches (needs the kernel build).
- The older families: `GET /api/families`, `POST /api/families/<id>/takeoff|model`.
- CLI: `./bbox cad-api families|takeoff|model|verify`.

Who uses it: the services app (`capmodel.py`) asks for a cap's BOM with the builder's own record and
prices it with its own Prices & setup — the cap's price in every quote when `cap_model_url` is set.

Traps:
- Every rule says its source: Alan (MEET-41), the shop's builder (cap3d.js), the shop's own installs
  (photos), or ASSUMED (industry). An unsaid rule is listed in `notes`, never filled silently.
- The base follows the chimney (Alan): brick → the masonry hood (10½″ strips, 10½ × 6 legs); a chase or
  a flue → the single flashing L+7 with a hole and a collar per flue.
- `CAD_KERNEL=0` builds the quote-only image (no OpenCascade); `/model` then answers 503.
- A piece bigger than the sheet is an `error` (copper comes 36 × 120), never a quiet extra sheet.
- A new style = a function in `caps/styles.py` returning parts + notes, registered with `style(Style(…))`,
  and a test against the shop's own numbers in `test_caps.py`.
