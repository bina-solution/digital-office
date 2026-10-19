# Aligned Value Extraction

This feature verifies that the OCR query engine can locate a numeric value immediately below the Hebrew anchor word "תעודה" in scanned government forms. The workflow combines document upload, cached OCR reuse, and a relative position query with drawing overlays for visual inspection.

## Business Goal

Given a known template where the registration or certificate number sits directly beneath the label "תעודה", operators must be able to extract that number reliably via the `/documentJsonQuery` endpoint. Regressions here block automated onboarding flows.

## Preconditions

- `docker compose up -d --build` has deployed the `apitools` service and dependencies.
- The feature container can reach the production stack (joins `traefik-network` by default).
- Optional: set `APITOOLS_BASE_URL` to override the default `http://apitools:8080` target.

## Validation Steps

1. Ensure the fixtures listed in `fixtures/fixtures.json` exist. The validation script will upload each file to `/documentOcr` automatically.
2. Execute the automated harness (use `--list-cases` to enumerate fixtures or `--case <name>` to focus on one):
   ```bash
   cd feature-validation/aligned-value-extraction
   python3 validate-feature.py
   ```
   The script iterates through every case in `fixtures/fixtures.json`, POSTs the query with `draw=1`, and writes results to `benchmarks/<timestamp>.json` plus `benchmarks/latest.json`.
3. Inspect the benchmark output to confirm that:
   - `result.match_text` is populated with the certificate number beneath "תעודה".
   - `result.validations_passed` is `true`.
   - `drawing_path` is returned, indicating that the annotated image was generated.
4. Record the observed number and any tolerance tweaks inside `notes.md` for historical traceability.
5. Optional flags: `--fail-fast` stops on the first error, `--no-upload-cache` forces fresh uploads when debugging OCR regeneration, and `--base-url` overrides the scenario/base configuration.

## Recovery

If validation fails:
- Inspect the overlay image to confirm OCR positioning.
- Adjust query tolerances (e.g., `max_horizontal_offset`, `max_vertical_gap`) inside the request payload and re-run.
- Regenerate OCR by re-uploading if the cached result is stale or drawn from a different template.


# Out of the box run all the feature validations
`cd /<complete_dir>/feature-validation && docker compose up`