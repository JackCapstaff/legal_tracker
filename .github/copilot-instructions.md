## Purpose

Concise instructions for AI coding agents working on this repository (Legal Case Tracker - Flask).
Focus: how the app is structured, data flows, important conventions, and safe places to change behavior.

## Big picture

- Single-process Flask app with a single entrypoint: `app.py`.
- Views render Jinja2 templates from `templates/` and persist data as JSON files under `data/` (no RDBMS).
- Primary resources: "matters" stored in `data/matters.json` and simple owners/users in `data/users.json`.
- File uploads go to `data/uploads/` (existing folder). Exports use `reportlab` to write PDFs; imports use `pandas`/`openpyxl`.

## How to run locally (Windows PowerShell example)

1. Create and activate venv, install deps:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Run in development mode:

   ```powershell
   $env:FLASK_APP = 'app.py'; $env:FLASK_ENV = 'development'; flask run
   # or: python app.py
   ```

Notes: sessions use `SECRET_KEY` environment variable; without it the app uses a dev secret.

## Key files & directories

- `app.py` — main Flask app. Contains routes for dashboard, matters CRUD, owners CRUD, import/export, and small helpers.
- `templates/` — Jinja2 templates (see `templates/base.html` for nav and flash handling patterns).
- `data/` — JSON-backed storage: `matters.json`, `users.json`, plus `uploads/` for file attachments.
- `requirements.txt` — runtime dependencies: Flask, reportlab (pdf export), pandas + openpyxl (excel import).

## Important code patterns and conventions (do not assume a DB)

- Canonical matter fields are listed in `app.py` near the top in the `FIELDS = [...]` array. When adding a new field, update that list first.
- Persistence is JSON-based: use `get_matters()` / `write_matters()` and `get_users()` / `save_users()` helpers to read/write files. Always use these helpers to keep schema normalization consistent.
- IDs: `new_id()` creates a short uuid-like id (10 hex chars). Do not assume integer IDs.
- Dates: `normalize_date()` accepts `DD/MM/YYYY` or `YYYY-MM-DD` and returns `YYYY-MM-DD`. Use it when reading user input.
- Aggregations/charts are computed in small functions (e.g., `compute_open_by_stage`, `compute_monthly_counts`). Prefer reusing them for new dashboard endpoints.

## Import / Export specifics

- Excel import requires `pandas` and `openpyxl` (already in `requirements.txt`). The importer maps common column headers — see README import section for expected headers.
- PDF export requires `reportlab`. If not installed, the app flashes an error and suggests `pip install reportlab`.

## Editing guidance and safe changes

- Adding a new field to matters:
  1. Add the field name to `FIELDS` in `app.py`.
  2. Update `templates/matters_form.html` to include form input for that field.
  3. Update importer mapping (if needed) and any export templates.
  4. Update sample data in `data/matters.json` if the change is structural for tests or demos.
- Persisted JSON is the source of truth; tests (none present) and manual checks should inspect `data/matters.json` after changes.

## Debugging tips

- Start the app with `FLASK_ENV=development` to get debug reloader and stack traces.
- Check `data/matters.json` for current state; small edits can be made directly for repro steps.
- For PDF/export issues ensure `reportlab` is installed; for import issues ensure `pandas` + `openpyxl` present and uploaded file has expected headers.

## API surface

- `GET /api/matters` — returns all matters as JSON.
- `POST /api/matters` — accepts a JSON matter (will be appended). Useful for headless imports or tests.

## Tests / CI / Builds

- There are no automated tests or CI configuration in the repo. Keep changes small and verify by running the app locally and inspecting `data/*.json`.

## When opening PRs

- Include a short note describing data schema changes and any required steps to migrate `data/matters.json` for reviewers.
- If you add a dependency (e.g., a library for imports/exports), update `requirements.txt` and mention why in the PR.

---

If anything here is unclear or you'd like me to emphasise a different area (e.g., the importer flow or adding automated tests), tell me what to expand and I'll update this file.
