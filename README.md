# Legal Case Tracker (Flask)

A lightweight Flask app that stores each contract/matter as a JSON record and provides a dashboard and CRUD UI.

## Features (v0)
- Dashboard home with quick stats
- List/Add/Edit/Delete matters
- JSON storage in `data/matters.json`
- Export all matters to PDF and JSON
- Basic owners/users list in `data/users.json` (no auth yet)

## Setup
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
FLASK_APP=app.py FLASK_ENV=development flask run
# or: python app.py
```

Open http://127.0.0.1:5000

## Next Steps
- Authentication & roles
- Attachments & comments
- Filtering, search, and dashboards by stage/status
- Import from Excel (current file: `New work tracker 16-07-2024.xlsm`)


## Importing from Excel
- Go to **Import** in the top nav.
- Upload your `.xlsx` or `.xlsm` tracker.
- (Optional) specify the sheet name (e.g. `Contracts`). If omitted, the importer will choose the most likely sheet.
- Choose **Append** (default) or **Replace** mode.
- The importer attempts to map column headers like *Ref, Date Received, Group Entity, Counterparty, Branch, Legal, Internal Dept, Contract Type, Contract Name, Internal Stakeholder, Who With, Stage, Overall Status, Commentary, Days with Legal, Total Cycle Time, Owner*.

### CLI import (optional)
You can also POST JSON to `/api/matters` or extend the importer for headless use.
