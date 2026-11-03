# Feature Validation

> **These are apitools' own suites.** They live here — `apps/apitools/feature-validation/` — because
> they validate this app's OCR/extraction engine. The one way to run them is the platform's single
> test entrypoint:
>
> ```bash
> ./bbox test apitools          # identical: ./bbox apitools test
> ./bbox test apitools --no-up  # the sidecar is already running (CI brings the stack up itself)
> ```
>
> That runs `apps/apitools/hooks/test`, which brings up the `feature-validation-api` driver from the
> compose file beside this README, runs every suite the granted capabilities allow, and writes
> `ci-artifacts/feature-validation.{junit.xml,md}`. It was `legacy/feature-validation/run-suites.sh`
> until the estate's only OCR coverage stopped being run out of the parked tree.

This directory tracks high-level product capabilities that must remain stable between deployments. Each feature entry documents the business goal, the API surface involved, datasets or inputs required, and how to validate behaviour manually or through automation.

## Structure

```
<feature-key>/
  README.md           # Feature narrative, API flow, and validation goals
  scenario.json       # Machine-readable description of inputs and expected outputs
  fixtures/           # Sample documents, payloads, or scripts used for validation
  notes.md            # Optional scratch space for learnings or follow-up
  benchmarks/         # Autofilled benchmark output written by the harness
```

## Usage

1. Start the production stack (`docker compose up -d --build`) so the validation containers can reach live services.
2. From this directory, run `docker compose up --build` to execute every feature harness (each container terminates after producing benchmarks).
3. Use `python3 validate-feature.py --list-cases` inside a feature directory to discover available fixtures or pass `--case <name>` to focus on a specific scenario when iterating.
4. Review the generated `benchmarks/` outputs under each feature folder and compare against `scenario.json`.
5. Capture insights or new edge-cases inside `notes.md`.

### Scenario Schema

- `upload_endpoint`, `endpoint`, and `query_params` set the network targets used by the runner; per-case overrides are supported.
- `assertions` is a list of declarative checks (`name`, `source`, `operator`) that the harness applies to the collected context (`analysis`, `query_response`, etc.). Scenario or case `expected` blocks provide the reference values.
- `expected.notes` fields are treated as documentation and copied into the benchmark output without affecting pass/fail state.

### Current Features
- `aligned-value-extraction/` – validates the `/documentJsonQuery` workflow that extracts the numeric value beneath the Hebrew label "תעודה".

Add new folders for additional capabilities as they are formalized. Keep documentation concise so it is easy to review before a release.

## API Server

A persistent FastAPI service (`feature-validation-api`) provides REST endpoints for running validations, querying benchmarks, and checking deployment service health. It also serves a live status dashboard at `/`.

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Status dashboard (HTML) |
| GET | `/api/health` | API health check |
| GET | `/api/status` | Combined deployment status (services + features) |
| GET | `/api/features` | List discovered features with latest benchmark summary |
| GET | `/api/features/{name}` | Feature detail + scenario + latest benchmark |
| GET | `/api/features/{name}/benchmarks` | List benchmark files |
| GET | `/api/features/{name}/benchmarks/latest` | Latest benchmark JSON |
| POST | `/api/run` | Run all validations (optional `?tag=` filter) |
| POST | `/api/run/{name}` | Run specific feature (optional `?cases=a,b`) |
| GET | `/api/services` | Health-check all configured services |
| GET | `/api/services/{name}` | Health-check a single service |

### Configuration (env vars)

| Variable | Default | Description |
|----------|---------|-------------|
| `FV_SCHEDULE_MINUTES` | `360` | Auto-run interval in minutes (0 to disable) |
| `FV_HEALTH_TIMEOUT` | `10` | Service health-check timeout (seconds) |
| `FV_HEALTH_TARGETS` | _(built-in)_ | Extra health targets: `name=url,name2=url2` |

### Running

```bash
# API only (included in main compose stack)
docker compose up feature-validation-api -d --build

# One-shot validation containers (unchanged)
docker compose up aligned-value-extraction find-option-matching --build
```

easyrun:
cd /root/deployment-hacohen/feature-validation && docker compose up