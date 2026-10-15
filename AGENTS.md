# AGENTS.md

- Python via uv (`.venv`); always run commands with `uv run`.
- Verify: `uv run ruff check .`, `uv run pytest` (network tests excluded; run with `-m network`), `uv run tucurul check-sizes`, `uv run tucurul build-site --out /tmp/site-check`.
- Scrapers use only `tucurul.sources.http.HttpClient` and `tucurul.sources.models`; raw cache in `data/raw/<fuente>/` (gitignored).
- SITL ingest: `uv run tucurul sitl-ingest` (~1 h live; resumable from cache; `--offline` re-runs from cache in seconds). Output in `data/sitl_diputados/` (gitignored, not versioned — regenerate locally), validation in its `metadata.json`.
- Senado ingest: `uv run tucurul senado-ingest` (~1 h live with anti-bot retries; resumable from cache; `--offline` re-runs from cache). Output in `data/senado/` (gitignored), validation in its `metadata.json`.
- After ingesting a source: update `data/coverage.csv` and run `uv run tucurul update-readme`.
