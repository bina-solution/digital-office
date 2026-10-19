# Find-Option Matching Validation

Validates the `find option` action of `/documentJsonQuery` — given a list of candidate texts, the API checks which ones appear in the OCR output using fuzzy matching.

## Background

A production incident occurred when ~850 supplier names were sent as options against a single document. The fuzzy matching loop (822 options × 3222 annotations × `fuzz.WRatio()`) exceeded the gunicorn 120s worker timeout under concurrent load, causing `WORKER TIMEOUT → SIGABRT → 500`.

## Test Cases

| Case | Options | Purpose |
|------|---------|---------|
| `small-option-set-with-matches` | 6 | Correctness: verifies known matches and no false positives |
| `no-matches-expected` | 3 | Correctness: verifies zero matches for non-existent options |
| `large-option-set-stress-test` | 600+ | Resilience: verifies completion without timeout |

All cases use a cached OCR file (`393087f3d7f25e05fe2be24ce5c25d8c`).

## Running

```bash
# Via docker compose (from feature-validation/)
docker compose run --rm find-option-matching

# Run a specific case
docker compose run --rm find-option-matching python validate-feature.py --case small-option-set-with-matches

# Direct (with venv)
cd find-option-matching
APITOOLS_BASE_URL=http://localhost:8080 python validate-feature.py
```

## Output

Benchmark results are written to `benchmarks/latest.json` and timestamped files.
