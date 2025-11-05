from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
import os, json, uuid, datetime
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
MATTERS_PATH = os.path.join(DATA_DIR, "matters.json")
USERS_PATH = os.path.join(DATA_DIR, "users.json")

FIELDS = [
    "Ref",
    "Date Received",
    "Group Entity",
    "Counterparty",
    "Branch",
    "Legal",
    "Internal Dept",
    "Contract Type",
    "Contract Name",
    "Internal Stakeholder",
    "Who With",
    "Stage",
    "Overall Status",
    "Date Closed",
    "Commentary",
    "Days with Legal",
    "Total Cycle Time",
    "Owner",
]

ALLOWED_STATUSES = [
    "Received/Under Review",
    "Drafted/Comments Sent",
    "Further/Final Review",
    "Counterparty Signature",
    "Internal Signature",
    "Closed"
]

# --- Canonicalize any legacy keys saved by older imports ---
LEGACY_TO_CANON = {
    "Date": "Date Received",
    "Group": "Group Entity",
    "Status": "Overall Status",
    # add other one-offs if you find them
}

def canonicalize_matter_keys(m: dict) -> dict:
    """Mutates a matter dict in place, moving legacy keys to canonical FIELDS."""
    for old, new in LEGACY_TO_CANON.items():
        if old in m and new not in m:
            m[new] = m.pop(old)
    return m

def load_json(path):
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def normalize_date(date_str):
    # Accepts DD/MM/YYYY or YYYY-MM-DD; returns YYYY-MM-DD
    if not date_str:
        return ""
    try:
        if "/" in date_str:
            d = datetime.datetime.strptime(date_str, "%d/%m/%Y").date()
        else:
            d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        return d.isoformat()
    except Exception:
        return date_str  # leave as-is

def new_id():
    return uuid.uuid4().hex[:10]

def get_matters():
    data = load_json(MATTERS_PATH)

    # Optional legacy key fixer (safe to keep)
    LEGACY_TO_CANON = {
        "Date": "Date Received",
        "Group": "Group Entity",
        "Status": "Overall Status",
    }
    def canonicalize_matter_keys(m: dict) -> dict:
        for old, new in LEGACY_TO_CANON.items():
            if old in m and new not in m:
                m[new] = m.pop(old)
        return m

    changed = False
    for m in data:
        canonicalize_matter_keys(m)
        if not m.get("id"):
            m["id"] = new_id()
            changed = True
        for f in FIELDS:
            if f not in m:
                m[f] = ""

    # ✨ Persist any ids we just generated so they remain stable across requests
    if changed:
        write_matters(data)

    return data



def write_matters(matters):
    save_json(MATTERS_PATH, matters)

def distinct_values(matters, field):
    vals = sorted({(m.get(field) or "").strip() for m in matters if (m.get(field) or "").strip()})
    return vals

def get_users():
    data = load_json(USERS_PATH)
    # normalize schema: id, name, job_title, function
    for u in data:
        u.setdefault("id", u.get("name","").lower().replace(" ", "") or new_id())
        u.setdefault("name", "")
        u.setdefault("job_title", "")
        u.setdefault("function", "")
    return data

def save_users(users):
    save_json(USERS_PATH, users)

def find_user_by_name(users, name):
    name_norm = (name or "").strip().lower()
    for u in users:
        if u.get("name","").strip().lower() == name_norm:
            return u
    return None


from collections import defaultdict, Counter

def month_key(date_str):
    # Expects YYYY-MM-DD; returns 'YYYY-MM'
    try:
        return date_str[:7]
    except Exception:
        return ""
    
import re

def to_int(val, default=0):
    """Parse integers safely from Excel-imported values (handles '', 'N/A', '12.0', '1,234')."""
    if val is None:
        return default
    if isinstance(val, (int,)):
        return val
    try:
        s = str(val).strip()
        if s == "" or s.lower() in {"na", "n/a", "none"}:
            return default
        s = s.replace(",", "")
        return int(float(s))
    except Exception:
        return default

def is_closed(m):
    """Treat common ‘closed’ synonyms as closed."""
    s = str(m.get("Overall Status", "") or "").strip().lower()
    # exact/contains match for common variations
    return (
        s == "closed"
        or "close" in s
        or "complete" in s
        or "executed" in s
        or "signed" in s
        or s == "done"
    )

from datetime import date

def compute_cycle_days(date_received_iso: str, date_closed_iso: str) -> int:
    """Return calendar day difference (>=0) between ISO dates YYYY-MM-DD."""
    try:
        if not date_received_iso or not date_closed_iso:
            return 0
        d1 = datetime.date.fromisoformat(str(date_received_iso))
        d2 = datetime.date.fromisoformat(str(date_closed_iso))
        delta = (d2 - d1).days
        return max(delta, 0)
    except Exception:
        return 0



def compute_open_by_stage(matters):
    open_matters = [m for m in matters if str(m.get("Overall Status","")).lower() == "open"]
    counts = Counter((m.get("Stage") or "Unspecified") for m in open_matters)
    labels = list(counts.keys())
    values = [counts[k] for k in labels]
    return labels, values

def compute_legal_vs_stakeholder_avgs(matters):
    open_matters = [m for m in matters if str(m.get("Overall Status","")).lower() == "open"]
    if not open_matters:
        return 0, 0
    legal_days = 0
    stakeholder_days = 0
    for m in open_matters:
        dl = to_int(m.get("Days with Legal"), 0)
        tt = to_int(m.get("Total Cycle Time"), 0)
        legal_days += dl
        stakeholder_days += max(tt - dl, 0)
    n = len(open_matters)
    return round(legal_days / n, 2), round(stakeholder_days / n, 2)


def compute_monthly_counts(matters):
    """
    Monthly counts keyed by the *Date Received* month.
    - New Contracts: count of matters received that month.
    - Closed Contracts: count of matters whose status indicates closed (see is_closed),
      bucketed in the *same receipt month*.
    - Rolling Open: cumulative (new - closed).
    """
    by_month_new = Counter()
    by_month_closed = Counter()

    for m in matters:
        mk = month_key(m.get("Date Received", "") or "")
        if not mk:
            continue
        by_month_new[mk] += 1
        if is_closed(m):
            by_month_closed[mk] += 1

    months = sorted(set(by_month_new.keys()) | set(by_month_closed.keys()))
    new_vals = [by_month_new.get(m, 0) for m in months]
    closed_vals = [by_month_closed.get(m, 0) for m in months]

    rolling = []
    running = 0
    for m in months:
        running += by_month_new.get(m, 0) - by_month_closed.get(m, 0)
        rolling.append(running)

    return months, new_vals, closed_vals, rolling



def compute_monthly_cycle_time_avgs(matters):
    """
    Group by Date Received month and average:
    - Avg. Time w/Legal
    - Avg. Time w/Stakeholder (= Total Cycle Time - Days with Legal, clamped at 0)
    - Avg. Total Cycle Time
    """
    buckets = defaultdict(list)  # month -> list of (dl, sh, tt)
    for m in matters:
        mk = month_key(m.get("Date Received", "") or "")
        if not mk:
            continue
        dl = to_int(m.get("Days with Legal"), 0)
        tt = to_int(m.get("Total Cycle Time"), 0)
        sh = max(tt - dl, 0)
        buckets[mk].append((dl, sh, tt))

    months = sorted(buckets.keys())
    avg_dl, avg_sh, avg_tt = [], [], []

    for mk in months:
        rows = buckets[mk]
        if rows:
            n = len(rows)
            dl = sum(r[0] for r in rows) / n
            sh = sum(r[1] for r in rows) / n
            tt = sum(r[2] for r in rows) / n
        else:
            dl = sh = tt = 0
        avg_dl.append(round(dl, 2))
        avg_sh.append(round(sh, 2))
        avg_tt.append(round(tt, 2))

    return months, avg_dl, avg_sh, avg_tt


def stage_bucket(stage):
    s = (stage or "").lower()
    legal_stages = ["received", "review", "draft", "comments", "legal"]
    if any(k in s for k in legal_stages):
        return "Legal"
    # Everything else -> Stakeholder/Other
    return "Stakeholder/Other"

def compute_owner_table(matters):
    open_matters = [m for m in matters if str(m.get("Overall Status","")).lower() == "open"]
    owners = defaultdict(lambda: {"total":0, "with_legal":0, "with_others":0})
    for m in open_matters:
        owner = (m.get("Owner") or m.get("Legal") or "Unassigned").strip() or "Unassigned"
        owners[owner]["total"] += 1
        if stage_bucket(m.get("Stage","")) == "Legal":
            owners[owner]["with_legal"] += 1
        else:
            owners[owner]["with_others"] += 1
    # Convert to sorted list of tuples
    rows = []
    for name, data in owners.items():
        rows.append({"owner": name, **data})
    rows.sort(key=lambda r: (-r["total"], r["owner"].lower()))
    return rows

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

@app.route("/")
def dashboard():
    matters = get_matters()
    total = len(matters)
    open_count = sum(1 for m in matters if str(m.get("Overall Status","")).lower() == "open")
    closed_count = sum(1 for m in matters if is_closed(m))
    stages = {}
    for m in matters:
        s = m.get("Stage","") or "Unspecified"
        stages[s] = stages.get(s, 0) + 1

    # Charts
    open_by_stage_labels, open_by_stage_values = compute_open_by_stage(matters)
    avg_legal, avg_stakeholder = compute_legal_vs_stakeholder_avgs(matters)
    months_counts, new_vals, closed_vals, rolling_vals = compute_monthly_counts(matters)
    months_cycle, avg_dl_vals, avg_sh_vals, avg_tt_vals = compute_monthly_cycle_time_avgs(matters)
    owner_rows = compute_owner_table(matters)

    # --- Recent Matters toggle (default: hide closed) ---
    show_closed = request.args.get("show_closed") == "1"

    # sort newest first (by Date Received ISO string)
    recent_matters = sorted(matters, key=lambda m: m.get("Date Received", ""), reverse=True)

    def _is_closed(m):
        return str(m.get("Overall Status", "")).strip().lower() == "closed"

    if not show_closed:
        recent_matters = [m for m in recent_matters if not _is_closed(m)]

    recent_matters = recent_matters[:5]

    return render_template(
        "dashboard.html",
        total=total,
        open_count=open_count,
        closed_count=closed_count,
        stages=stages,
        matters=recent_matters,            # <-- pass filtered list
        show_closed=show_closed,           # <-- pass toggle state to template
        open_by_stage_labels=open_by_stage_labels,
        open_by_stage_values=open_by_stage_values,
        avg_legal=avg_legal,
        avg_stakeholder=avg_stakeholder,
        months_counts=months_counts,
        new_vals=new_vals,
        closed_vals=closed_vals,
        rolling_vals=rolling_vals,
        months_cycle=months_cycle,
        avg_dl_vals=avg_dl_vals,
        avg_sh_vals=avg_sh_vals,
        avg_tt_vals=avg_tt_vals,
        owner_rows=owner_rows,
    )

@app.route("/matters")
def matters_list():
    matters = get_matters()

    # Text search
    q = request.args.get("q","").strip().lower()
    if q:
        matters = [m for m in matters if q in json.dumps(m).lower()]

    # Filterable fields
    FILTER_FIELDS = [
        "Group Entity","Counterparty","Branch","Legal","Internal Dept",
        "Contract Type","Internal Stakeholder","Who With","Stage","Overall Status"
    ]

    # Build distinct options
    filter_options = {f: distinct_values(get_matters(), f) for f in FILTER_FIELDS}

    # Capture current selections
    active = {f: (request.args.get(f.replace(' ', '_')) or "").strip() for f in FILTER_FIELDS}

    # Apply filters
    def match_field(mval, selected):
        if not selected:
            return True
        return (mval or "").strip().lower() == selected.strip().lower()

    filtered = []
    for m in matters:
        ok = True
        for f in FILTER_FIELDS:
            sel = active[f]
            if not match_field(m.get(f, ""), sel):
                ok = False
                break
        if ok:
            filtered.append(m)

    return render_template("matters_list.html",
                           matters=filtered, q=q,
                           filter_options=filter_options, active_filters=active)



@app.route("/matters/new", methods=["GET","POST"])
def matters_new():

    
    users = get_users()
    if request.method == "POST":
        data = {f: request.form.get(f, "").strip() for f in FIELDS}
        data["Date Received"] = normalize_date(data.get("Date Received"))
        try:
            data["Days with Legal"] = int(request.form.get("Days with Legal") or 0)
        except ValueError:
            data["Days with Legal"] = 0
        try:
            data["Total Cycle Time"] = int(request.form.get("Total Cycle Time") or 0)
        except ValueError:
            data["Total Cycle Time"] = 0

        matters = get_matters()
        data["id"] = new_id()
        matters.append(data)
        write_matters(matters)
        flash("Matter created", "success")
        return redirect(url_for("matters_list"))
    return render_template("matters_form.html", matter=None, fields=FIELDS, users=users, allowed_statuses=ALLOWED_STATUSES)

@app.route("/matters/<mid>/close", methods=["POST"])
def matters_close(mid):
    matters = get_matters()
    m = next((x for x in matters if x["id"] == mid), None)
    if not m:
        flash("Matter not found", "danger")
        return redirect(url_for("matters_list"))

    # Set closed fields
    today_iso = date.today().isoformat()
    m["Overall Status"] = "Closed"
    m["Date Closed"] = today_iso

    # Ensure Date Received is normalized
    m["Date Received"] = normalize_date(m.get("Date Received", ""))

    # Recalculate cycle time
    m["Total Cycle Time"] = compute_cycle_days(m.get("Date Received", ""), today_iso)

    write_matters(matters)
    flash("Case closed.", "success")
    return redirect(url_for("matters_edit", mid=mid))


@app.route("/matters/<mid>/edit", methods=["GET","POST"])
def matters_edit(mid):
    users = get_users()
    matters = get_matters()
    matter = next((m for m in matters if m["id"] == mid), None)
    if not matter:
        flash("Matter not found", "danger")
        return redirect(url_for("matters_list"))

    if request.method == "POST":
        for f in FIELDS:
            val = (request.form.get(f) or "").strip()
            if f in ("Date Received", "Date Closed"):
                val = normalize_date(val)
            if f in ("Days with Legal", "Total Cycle Time"):
                try:
                    val = int(val or 0)
                except ValueError:
                    val = 0
            matter[f] = val

        # Recompute total cycle time if a closed date is present
        if matter.get("Date Closed"):
            matter["Total Cycle Time"] = compute_cycle_days(
                matter.get("Date Received", ""), matter.get("Date Closed", "")
            )

        write_matters(matters)
        flash("Matter updated", "success")
        return redirect(url_for("matters_list"))

    return render_template(
        "matters_form.html",
        matter=matter,
        fields=FIELDS,
        users=users,
        allowed_statuses=ALLOWED_STATUSES,
    )



@app.route("/matters/<mid>/delete", methods=["POST"])
def matters_delete(mid):
    matters = get_matters()
    matters = [m for m in matters if m["id"] != mid]
    write_matters(matters)
    flash("Matter deleted", "info")
    return redirect(url_for("matters_list"))

@app.route("/export/json")
def export_json():
    return send_file(MATTERS_PATH, as_attachment=True, download_name="matters.json")

@app.route("/export/pdf")
def export_pdf():
    # Simple landscape A4 PDF listing matters in a table-like layout
    matters = get_matters()
    pdf_path = os.path.join(DATA_DIR, "matters_export.pdf")
    c = canvas.Canvas(pdf_path, pagesize=landscape(A4))
    width, height = landscape(A4)

    margin = 10 * mm
    x = margin
    y = height - margin

    title = "Matters Export"
    c.setFont("Helvetica-Bold", 16)
    c.drawString(x, y, title)
    y -= 10 * mm

    headers = ["Ref", "Date Received", "Group Entity", "Counterparty", "Stage", "Overall Status", "Owner"]
    c.setFont("Helvetica-Bold", 9)
    col_widths = [70*mm, 25*mm, 40*mm, 40*mm, 40*mm, 25*mm, 25*mm]

    # Header row
    cx = x
    for h, w in zip(headers, col_widths):
        c.drawString(cx, y, h)
        cx += w
    y -= 6 * mm
    c.setFont("Helvetica", 8)

    for m in matters:
        cx = x
        row = [
            m.get("Ref",""),
            m.get("Date Received",""),
            m.get("Group Entity",""),
            m.get("Counterparty",""),
            m.get("Stage",""),
            m.get("Overall Status",""),
            m.get("Owner",""),
        ]
        line_height = 5 * mm
        # Wrap long text crudely
        for cell, w in zip(row, col_widths):
            text = str(cell)[:120]
            c.drawString(cx, y, text)
            cx += w
        y -= line_height
        if y < margin + 20*mm:
            c.showPage()
            y = height - margin
            c.setFont("Helvetica-Bold", 9)
            cx = x
            for h, w in zip(headers, col_widths):
                c.drawString(cx, y, h)
                cx += w
            y -= 6 * mm
            c.setFont("Helvetica", 8)

    c.showPage()
    c.save()
    return send_file(pdf_path, as_attachment=True, download_name="matters_export.pdf")

@app.route("/api/matters", methods=["GET", "POST"])
def api_matters():
    if request.method == "POST":
        data = request.json or {}
        matters = get_matters()
        data.setdefault("id", new_id())
        matters.append(data)
        write_matters(matters)
        return jsonify({"ok": True, "id": data["id"]})
    return jsonify(get_matters())

from werkzeug.utils import secure_filename
import re

ALLOWED_EXTS = {'.xlsx', '.xlsm'}

def allowed_file(filename):
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTS

# Possible header aliases mapping to our canonical FIELDS keys
HEADER_ALIASES = {
    "Ref": ["Ref", "Reference", "Matter", "Title"],
    "Date Received": ["Date Received", "Received", "Date", "Date_received"],
    "Group Entity": ["Group Entity", "Group", "Entity", "Group_Entity"],
    "Counterparty": ["Counterparty", "Other Party", "Vendor", "Supplier", "Customer"],
    "Branch": ["Branch", "Site", "Location"],
    "Legal": ["Legal", "Lawyer", "Handler"],
    "Internal Dept": ["Internal Dept", "Department", "Internal Department", "Dept"],
    "Contract Type": ["Contract Type", "Type"],
    "Contract Name": ["Contract Name", "Agreement", "Name"],
    "Internal Stakeholder": ["Internal Stakeholder", "Stakeholder", "Requester", "Requestor"],
    "Who With": ["Who With", "With", "Counterparty Contact"],
    "Stage": ["Stage", "Phase", "Step"],
    "Overall Status": ["Overall Status", "Status"],
    "Commentary": ["Commentary", "Notes", "Comments", "Summary"],
    "Days with Legal": ["Days with Legal", "Days_with_Legal", "Days With Legal"],
    "Total Cycle Time": ["Total Cycle Time", "Total_Cycle_Time", "Cycle Time"],
    "Owner": ["Owner", "Matter Owner", "Assigned To", "Assignee", "Legal"],
    "Date Received": ["Date Received", "Date"],
    "Group Entity":  ["Group Entity", "Group"],
    "Overall Status": ["Overall Status", "Status"],
}

def normalize_headers(df_columns):
    """Return a dict mapping df column -> canonical field name using aliases and fuzzy match."""
    mapping = {}
    cols = list(df_columns)
    norm = [str(c).strip() for c in cols]

    # straight alias match first
    for can, aliases in HEADER_ALIASES.items():
        low_aliases = [a.lower() for a in aliases]
        for i, c in enumerate(norm):
            if c.lower() in low_aliases and cols[i] not in mapping:
                mapping[cols[i]] = can

    # fuzzy: remove non-alphanum and compare collapsed tokens
    def squash(s): return re.sub(r"[^a-z0-9]+", "", str(s).lower())
    unmapped = [c for c in cols if c not in mapping]
    for c in unmapped:
        sc = squash(c)
        for can, aliases in HEADER_ALIASES.items():
            if squash(can) == sc or any(squash(a) == sc for a in aliases):
                mapping[c] = can
                break
    return mapping

@app.route("/import", methods=["GET","POST"])
def import_matters():
    import io
    # Lazy import (clear error if pandas/openpyxl missing)
    try:
        import pandas as pd
    except Exception:
        flash("Importer requires pandas (and openpyxl). Run: pip install -r requirements.txt", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "GET":
        return render_template("import.html")

    file = request.files.get("file")
    sheet = (request.form.get("sheet") or "").strip()
    mode = request.form.get("mode") or "append"
    has_header = bool(request.form.get("has_header"))

    if not file or file.filename == "":
        flash("Please choose a file.", "danger")
        return redirect(request.url)
    if not allowed_file(file.filename):
        flash("Unsupported file type. Please upload .xlsx or .xlsm", "danger")
        return redirect(request.url)

    # Read the upload entirely in-memory
    file_bytes = file.read()
    if not file_bytes:
        flash("Uploaded file is empty.", "danger")
        return redirect(request.url)

    try:
        bio = io.BytesIO(file_bytes)
        if sheet:
            df = pd.read_excel(bio, sheet_name=sheet, engine="openpyxl", header=0 if has_header else None)
        else:
            df = pd.read_excel(bio, engine="openpyxl", header=0 if has_header else None)
    except Exception as e:
        flash(f"Could not read Excel: {e}", "danger")
        return redirect(request.url)

    # If multiple sheets returned, pick a likely one
    if isinstance(df, dict):
        prefer = None
        for k in df.keys():
            lk = str(k).lower()
            if any(key in lk for key in ["contract", "matter", "tracker"]):
                prefer = k
                break
        df = df.get(prefer or list(df.keys())[0])

    # Map headers -> canonical fields
    mapping = normalize_headers(df.columns)

    records = []
    for _, row in df.iterrows():
        rec = {f: "" for f in FIELDS}
        rec.setdefault("Date Closed", "")

        # copy values by mapped columns
        for col, val in row.items():
            if col in mapping:
                key = mapping[col]
                if pd.isna(val):
                    v = ""
                elif isinstance(val, pd.Timestamp):
                    v = val.date().isoformat()
                else:
                    v = str(val)
                rec[key] = v.strip()

        # normalize dates
        rec["Date Received"] = normalize_date(rec.get("Date Received"))
        if rec.get("Date Closed"):
            rec["Date Closed"] = normalize_date(rec.get("Date Closed"))

        # ints
        try:
            rec["Days with Legal"] = int(float(rec.get("Days with Legal") or 0))
        except Exception:
            rec["Days with Legal"] = 0
        try:
            rec["Total Cycle Time"] = int(float(rec.get("Total Cycle Time") or 0))
        except Exception:
            rec["Total Cycle Time"] = 0

        # ---> DERIVE Date Closed if missing but cycle time present
        if not rec.get("Date Closed") and rec.get("Date Received") and rec.get("Total Cycle Time", 0) > 0:
            try:
                d0 = datetime.date.fromisoformat(str(rec["Date Received"]))
                rec["Date Closed"] = (d0 + datetime.timedelta(days=int(rec["Total Cycle Time"]))).isoformat()
            except Exception:
                rec["Date Closed"] = rec.get("Date Closed", "")

        # skip empty rows
        if rec.get("Ref") or rec.get("Counterparty"):
            rec["id"] = new_id()
            records.append(rec)

    if not records:
        app.logger.warning("Import parsed zero records. Mapped columns: %s", mapping)
        flash("No valid records found to import.", "warning")
        return redirect(url_for("import_matters"))

    # AUTO-CREATE OWNERS from Owner / Legal
    owner_names = set()
    for r in records:
        name = (r.get("Owner") or r.get("Legal") or "").strip()
        if name:
            owner_names.add(name)
    users = get_users()
    changed = False
    for name in sorted(owner_names):
        if not find_user_by_name(users, name):
            users.append({"id": new_id(), "name": name, "job_title": "", "function": ""})
            changed = True
    if changed:
        save_users(users)

    # Write matters
    if mode == "replace":
        write_matters(records)
        flash(f"Imported {len(records)} matters (replaced existing).", "success")
    else:
        existing = get_matters()
        seen = {(m.get("Ref",""), m.get("Counterparty",""), m.get("Date Received","")) for m in existing}
        new_items = [r for r in records if (r.get("Ref",""), r.get("Counterparty",""), r.get("Date Received","")) not in seen]
        write_matters(existing + new_items)
        flash(f"Imported {len(new_items)} new matters (skipped {len(records)-len(new_items)} possible duplicates).", "success")

    return redirect(url_for("matters_list"))




@app.route("/owners")
def owners_list():
    users = get_users()
    return render_template("owners_list.html", users=users)

@app.route("/owners/new", methods=["GET","POST"])
def owners_new():
    users = get_users()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        job_title = (request.form.get("job_title") or "").strip()
        function = (request.form.get("function") or "").strip()
        if not name:
            flash("Name is required", "danger")
            return redirect(request.url)
        if find_user_by_name(users, name):
            flash("An owner with that name already exists.", "warning")
            return redirect(url_for("owners_list"))
        users.append({"id": new_id(), "name": name, "job_title": job_title, "function": function})
        save_users(users)
        flash("Owner created", "success")
        return redirect(url_for("owners_list"))
    return render_template("owners_form.html", user=None)

@app.route("/owners/<uid>/edit", methods=["GET","POST"])
def owners_edit(uid):
    users = get_users()
    user = next((u for u in users if u["id"] == uid), None)
    if not user:
        flash("Owner not found", "danger")
        return redirect(url_for("owners_list"))
    if request.method == "POST":
        user["name"] = (request.form.get("name") or "").strip()
        user["job_title"] = (request.form.get("job_title") or "").strip()
        user["function"] = (request.form.get("function") or "").strip()
        save_users(users)
        flash("Owner updated", "success")
        return redirect(url_for("owners_list"))
    return render_template("owners_form.html", user=user)

@app.route("/owners/<uid>/delete", methods=["POST"])
def owners_delete(uid):
    users = get_users()
    user = next((u for u in users if u["id"] == uid), None)
    if not user:
        flash("Owner not found", "danger")
        return redirect(url_for("owners_list"))
    # Prevent deletion if referenced by matters
    matters = get_matters()
    in_use = any((m.get("Owner","").strip().lower() == user["name"].strip().lower()) for m in matters)
    if in_use:
        flash("Cannot delete owner: they are assigned to one or more matters.", "warning")
        return redirect(url_for("owners_list"))
    users = [u for u in users if u["id"] != uid]
    save_users(users)
    flash("Owner deleted", "info")
    return redirect(url_for("owners_list"))


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
