import os
os.environ['WEASYPRINT_DLL_DIRECTORIES'] = r'C:\msys64\mingw64\bin'
import sqlite3
import io
import os
from flask import send_file
from datetime import datetime
from flask import Flask, render_template, request, redirect, send_file, session, url_for, jsonify
from werkzeug.utils import secure_filename

# ReportLab Imports
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

app = Flask(__name__)
app.secret_key = "samaj_central_system_2026"
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

# ============================================================
# REGISTER GUJARATI FONT
# ============================================================
GUJARATI_FONT = 'Helvetica'
try:
    font_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts', 'NotoSansGujarati-Regular.ttf')
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont('Gujarati', font_path))
        GUJARATI_FONT = 'Gujarati'
    else:
        font_paths = [
            '/usr/share/fonts/truetype/noto/NotoSansGujarati-Regular.ttf',
            '/usr/share/fonts/opentype/noto/NotoSansGujarati-Regular.ttf',
            'C:/Windows/Fonts/NOTOSANSGUJARATI-REGULAR.TTF',
        ]
        for path in font_paths:
            if os.path.exists(path):
                pdfmetrics.registerFont(TTFont('Gujarati', path))
                GUJARATI_FONT = 'Gujarati'
                break
except:
    pass

# ============================================================
# MIXED GUJARATI + ENGLISH TEXT HELPER FOR PDF
# ============================================================
# The Noto Sans Gujarati font only contains Gujarati-script glyphs (no
# A-Z Latin letters). Real data (names, descriptions, month codes, etc.)
# is often a mix of Gujarati and English/numbers in the same line, so a
# single fontName can never render both correctly. This scans the text
# character-by-character and wraps each script run in its own <font>
# tag so ReportLab's Paragraph renders both scripts correctly together.
import xml.sax.saxutils as _saxutils

def guj_mix(text):
    if text is None:
        return ""
    text = str(text)
    if not text:
        return ""

    def is_gujarati(ch):
        return '\u0A80' <= ch <= '\u0AFF' or ch == '\u20B9'

    runs = []
    current_font = None
    current_chars = []
    for ch in text:
        f = GUJARATI_FONT if is_gujarati(ch) else 'Helvetica'
        if f != current_font and current_chars:
            runs.append((current_font, ''.join(current_chars)))
            current_chars = []
        current_font = f
        current_chars.append(ch)
    if current_chars:
        runs.append((current_font, ''.join(current_chars)))

    out = []
    for f, chunk in runs:
        out.append(f'<font name="{f}">{_saxutils.escape(chunk)}</font>')
    return ''.join(out)

# ============================================================
# DATABASE INITIALIZATION
# ============================================================
def init_db():
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("PRAGMA busy_timeout = 30000")
    
    # ... ટેબલ બનાવવાનો કોડ ...
    
    # admin યુઝર ચેક કરો
    cursor.execute("SELECT id FROM users WHERE username = 'admin'")
    if not cursor.fetchone():          # ← આ લાઇન 4 જગ્યાએ
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                       ('admin', '210784', 'treasurer'))  # ← આ 8 જગ્યાએ
    else:                               # ← આ 4 જગ્યાએ
        cursor.execute("UPDATE users SET password='210784', role='treasurer' WHERE username='admin'")  # ← આ 8 જગ્યાએ

    conn.commit()
    conn.close()

# એપ શરૂ થાય ત્યારે ફંક્શન કૉલ કરો
init_db()  # ← આ લાઇન શૂન્ય જગ્યાએ (લાઇન 144 હવે અહીં નથી)
    
    conn.commit()
    conn.close()
    
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'treasurer'")
    except Exception as e:
        pass

    try:
        cursor.execute("ALTER TABLE family_members ADD COLUMN blood_group TEXT")
    except Exception as e:
        print(f"[migration] family_members.blood_group column: {e}")
        
    cursor.execute("UPDATE users SET role='treasurer' WHERE role IS NULL OR role=''")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS families (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        firm_name TEXT, 
        family_name TEXT, 
        mobile TEXT, 
        address TEXT, 
        uif REAL DEFAULT 0.0
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS family_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        family_id INTEGER, 
        name TEXT, 
        mobile TEXT, 
        business_study TEXT, 
        birth_date TEXT
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        event_name TEXT, 
        event_date TEXT, 
        deadline_date TEXT, 
        event_type TEXT DEFAULT 'culture'
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rsvp (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        event_id INTEGER, 
        family_id INTEGER, 
        member_name TEXT, 
        mobile_number TEXT,
        head_count INTEGER DEFAULT 0,
        standard TEXT, 
        percentage TEXT, 
        item_name TEXT, 
        performance_type TEXT, 
        file_path TEXT, 
        leader_name TEXT, 
        leader_mobile TEXT, 
        participants_count INTEGER DEFAULT 1, 
        participants_names TEXT, 
        program_duration TEXT, 
        academic_year TEXT, 
        semester TEXT, 
        total_marks TEXT, 
        obtained_marks TEXT, 
        other_info TEXT, 
        submitted_at TEXT
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        family_id INTEGER, 
        target_month TEXT, 
        amount REAL, 
        paid_date TEXT
    )
    """)
    
    # ---- Migration: add a 'year' column to payments so old years' records
    # are preserved (tagged by year) instead of being overwritten/deleted
    # when a new collection year starts. ----
    cursor.execute("PRAGMA table_info(payments)")
    payment_cols = [c[1] for c in cursor.fetchall()]
    if 'year' not in payment_cols:
        cursor.execute("ALTER TABLE payments ADD COLUMN year INTEGER")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rollover_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year_from INTEGER,
        year_to INTEGER,
        family_id INTEGER,
        amount_added REAL,
        created_at TEXT
    )
    """)
    cursor.execute("SELECT value FROM app_settings WHERE key='current_collection_year'")
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO app_settings (key, value) VALUES ('current_collection_year', ?)",
                        (str(datetime.now().year),))
        active_year = datetime.now().year
    else:
        active_year = int(row[0])
    
    # Backfill any pre-existing payment rows (from before the 'year' column existed)
    # with the current active year so they aren't lost or ambiguous.
    cursor.execute("UPDATE payments SET year=? WHERE year IS NULL", (active_year,))
    
    conn.commit()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS yuvak_mandal (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        name TEXT, 
        birth_date TEXT, 
        mobile TEXT, 
        address TEXT, 
        education TEXT, 
        hobby TEXT, 
        entry_fee REAL DEFAULT 0.0, 
        photo_path TEXT, 
        is_executive INTEGER DEFAULT 0
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS yuvak_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        entry_date TEXT, 
        entry_type TEXT, 
        donor_name TEXT, 
        description TEXT, 
        amount REAL
    )
    """)
    
    try:
        cursor.execute("ALTER TABLE family_members ADD COLUMN mobile TEXT")
    except Exception as e:
        print(f"[migration] family_members.mobile column: {e}")
    try:
        cursor.execute("ALTER TABLE family_members ADD COLUMN business_study TEXT")
    except Exception as e:
        print(f"[migration] family_members.business_study column: {e}")
    try:
        cursor.execute("ALTER TABLE rsvp ADD COLUMN mobile_number TEXT")
    except Exception as e:
        print(f"[migration] rsvp.mobile_number column: {e}")
    try:
        cursor.execute("ALTER TABLE family_members ADD COLUMN house_number TEXT DEFAULT '1'")
    except Exception as e:
        print(f"[migration] family_members.house_number column: {e}")
    cursor.execute("UPDATE family_members SET house_number='1' WHERE house_number IS NULL OR house_number=''")
    try:
        cursor.execute("ALTER TABLE yuvak_ledger ADD COLUMN event_tag TEXT")
    except Exception as e:
        print(f"[migration] yuvak_ledger.event_tag column: {e}")
    cursor.execute("UPDATE yuvak_ledger SET event_tag='સામાન્ય' WHERE event_tag IS NULL OR event_tag=''")
    try:
        cursor.execute("ALTER TABLE family_members ADD COLUMN is_head INTEGER DEFAULT 0")
    except Exception as e:
        print(f"[migration] family_members.is_head column: {e}")
    cursor.execute("UPDATE family_members SET is_head=0 WHERE is_head IS NULL")
    
    # Ensure every (family, chula) group has at least one head — if none is
    # marked yet, auto-designate the first member (by id) in that group so
    # exports always have a "main person" to show.
    cursor.execute("SELECT DISTINCT family_id, house_number FROM family_members")
    for fam_id, house_num in cursor.fetchall():
        cursor.execute("SELECT COUNT(*) FROM family_members WHERE family_id=? AND house_number=? AND is_head=1", (fam_id, house_num))
        if cursor.fetchone()[0] == 0:
            cursor.execute("SELECT id FROM family_members WHERE family_id=? AND house_number=? ORDER BY id ASC LIMIT 1", (fam_id, house_num))
            first_member = cursor.fetchone()
            if first_member:
                cursor.execute("UPDATE family_members SET is_head=1 WHERE id=?", (first_member[0],))
    
    conn.commit()
    conn.close()

init_db()

# ============================================================
# HELPER FUNCTIONS
# ============================================================
def is_treasurer():
    return session.get("role", "treasurer") == "treasurer"

def get_current_collection_year():
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM app_settings WHERE key='current_collection_year'")
    row = cursor.fetchone()
    conn.close()
    if row:
        return int(row[0])
    return datetime.now().year

def set_current_collection_year(year):
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE app_settings SET value=? WHERE key='current_collection_year'", (str(year),))
    conn.commit()
    conn.close()

def format_date_to_indian(date_str):
    if not date_str:
        return ""
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue
    return date_str

def format_date_to_db(date_str):
    if not date_str:
        return ""
    date_str = date_str.replace('/', '-')
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str

def calculate_age(birth_date_str):
    if not birth_date_str:
        return 0
    try:
        birth_date = None
        for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
            try:
                birth_date = datetime.strptime(birth_date_str.strip(), fmt)
                break
            except:
                continue
        if not birth_date:
            return 0
        today = datetime.now()
        return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    except:
        return 0

@app.template_filter('clean_amt')
def clean_amt(value):
    try:
        val = float(value)
        return int(val) if val > 0 else ''
    except:
        return ''

@app.template_filter('inr_amt')
def inr_amt(value):
    
    """Format a number as Indian-style currency (e.g. 1,00,000.50) without losing decimals."""
    
    try:
        val = float(value)
    except (TypeError, ValueError):
        return '0'
    negative = val < 0
    val = abs(val)
    whole = int(val)
    paisa = round((val - whole) * 100)
    if paisa == 100:
        whole += 1
        paisa = 0
    num = str(whole)
    if len(num) > 3:
        last3 = num[-3:]
        rest = num[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        num = ",".join(groups) + "," + last3
    result = f"{num}.{paisa:02d}" if paisa else num
    return ("-" if negative else "") + result

# ============================================================
# LOGIN & LOGOUT
# ============================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        conn = sqlite3.connect("samaj.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password, role, family_id FROM users WHERE username=? AND password=?", (username, password))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            session["logged_in"] = True
            session["user_id"] = user[0]
            session["username"] = user[1]
            session["role"] = user[3] or "treasurer"
            session["family_id"] = user[4]
            return redirect("/")
        else:
            error = "ખોટું યુઝરનેમ અથવા પાસવર્ડ!"
            
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/manage-users", methods=["GET", "POST"])
def manage_users():
    if not session.get("logged_in") or session.get("role") != "treasurer":
        return redirect("/")
        
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            username = request.form.get("username")
            password = request.form.get("password")
            role = request.form.get("role", "committee")
            family_id = request.form.get("family_id") if role == "farm_head" else None
            
            try:
                cursor.execute("INSERT INTO users (username, password, role, family_id) VALUES (?, ?, ?, ?)",
                               (username, password, role, family_id))
                conn.commit()
            except Exception as e:
                print(f"Error: {e}")
                
        elif action == "delete":
            user_id = request.form.get("user_id")
            cursor.execute("DELETE FROM users WHERE id=? AND username != 'admin'", (user_id,))
            conn.commit()
            
    # યૂઝર્સની યાદી મેળવો
    cursor.execute("SELECT id, username, role, family_id FROM users")
    users = cursor.fetchall()
    
    # બધી જ ફેમિલીની યાદી મેળવો (id, family_name, firm_name)
    cursor.execute("SELECT id, family_name, firm_name FROM families")
    all_families = cursor.fetchall()
    
    conn.close()
    
    return render_template("manage_users.html", users=users, all_families=all_families, current_username=session.get("username"))


@app.route("/")
def home():
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM families")
    total_families = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM events")
    total_events = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM yuvak_mandal")
    total_yuvak = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(amount) FROM payments")
    total_collection = cursor.fetchone()[0] or 0
    
    conn.close()
    
    return render_template("home.html", 
                          total_families=total_families,
                          total_events=total_events,
                          total_yuvak=total_yuvak,
                          total_collection=total_collection,
                          now=datetime.now())

# ============================================================
# FAMILIES SECTION
# ============================================================
@app.route("/families")
def families():
    if not session.get("logged_in"):
        return redirect("/login")
    
    # જો યૂઝર ફાર્મ હેડ હોય, તો તેને આખું પરિવાર મેનુ એક્સેસ કરવા દેવું નહીં
    if session.get("role") == "farm_head":
        fam_id = session.get("family_id")
        if fam_id:
            return redirect(f"/family/{fam_id}/members")
        return "<h3>તમને આ પેજ એક્સેસ કરવાની પરવાનગી નથી!</h3>", 403
    
    search = request.args.get("search", "")
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    if search:
        cursor.execute("""
            SELECT id, firm_name, family_name, mobile, address, uif 
            FROM families 
            WHERE firm_name LIKE ? OR family_name LIKE ? 
            ORDER BY id DESC
        """, (f"%{search}%", f"%{search}%"))
    else:
        cursor.execute("SELECT id, firm_name, family_name, mobile, address, uif FROM families ORDER BY id DESC")
    
    families_data = cursor.fetchall()
    
    months_list = ['jan', 'feb', 'mar', 'apr', 'may', 'june', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
    formatted_data = []
    total_page_members = 0
    total_page_rs = 0
    total_page_uif = 0
    month_totals = {m: 0.0 for m in months_list}
    
    active_year = get_current_collection_year()

    cursor.execute("SELECT COUNT(*) FROM rollover_log WHERE year_to=?", (active_year,))
    can_undo_rollover = cursor.fetchone()[0] > 0

    # Which year is being viewed. Defaults to the active (current) year.
    # Past years are shown read-only; only the active year can be edited.
    try:
        view_year = int(request.args.get("year", active_year))
    except (TypeError, ValueError):
        view_year = active_year
    is_current_year_view = (view_year == active_year)

    # Build the list of years available to browse: only years that actually
    # have payment records, plus the active year itself. We no longer
    # auto-add "active_year - 1" as a placeholder, since that created a
    # confusing empty year pill that didn't correspond to real data.
    cursor.execute("SELECT DISTINCT year FROM payments WHERE year IS NOT NULL ORDER BY year DESC")
    available_years = [r[0] for r in cursor.fetchall()]
    if active_year not in available_years:
        available_years.append(active_year)
    available_years = sorted(set(available_years), reverse=True)

    for row in families_data:
        f_id = row[0]
        cursor.execute("SELECT COUNT(*) FROM family_members WHERE family_id=?", (f_id,))
        t_members = cursor.fetchone()[0]
        total_rs = t_members * 50
        annual_expected = total_rs * 12
        
        total_page_members += t_members
        total_page_rs += total_rs
        total_page_uif += row[5]
        
        cursor.execute("SELECT target_month, amount FROM payments WHERE family_id=? AND year=?", (f_id, view_year))
        pmt_records = dict(cursor.fetchall())
        amount_list = []
        annual_paid = 0.0
        
        for m in months_list:
            amt = pmt_records.get(m, 0)
            amount_list.append(amt)
            if is_current_year_view:
                month_totals[m] += amt
            annual_paid += amt
        
        # Total-based due calculation (not per-month): this correctly handles families
        # who pay the whole year's amount in a single month (e.g. ₹5400 all at once in
        # July) — the lump sum counts toward the full year, so other months don't
        # incorrectly show as still "due".
        #
        # UIF may already contain rolled-over dues from previous years (added
        # automatically by "Start New Year"). The combined debt is
        # (old UIF due + this year's expected fee), and any amount paid this
        # year comes off that COMBINED total — not just the current year's
        # portion — so old debt actually gets cleared as payments come in.
        uif_val = row[5] or 0
        combined_expected = uif_val + annual_expected
        grand_total_due = max(0, combined_expected - annual_paid)
        due_amount = max(0, annual_expected - annual_paid)  # current-year-only figure, still shown for historical years
        
        formatted_data.append({
            'id': f_id,
            'firm_name': row[1],
            'family_name': row[2],
            'mobile': row[3],
            'address': row[4],
            'uif': row[5],
            'total_members': t_members,
            'total_rs': total_rs,
            'amounts': amount_list,
            'due_amount': due_amount,
            'annual_expected': annual_expected,
            'annual_paid': annual_paid,
            'grand_total_due': grand_total_due
        })
    
    conn.close()
    total_page_due = sum(f['due_amount'] for f in formatted_data)
    total_page_grand_due = sum(f['grand_total_due'] for f in formatted_data)
    
    treasury_data = {
        1: month_totals['jan'], 2: month_totals['feb'], 3: month_totals['mar'], 4: month_totals['apr'],
        5: month_totals['may'], 6: month_totals['june'], 7: month_totals['jul'], 8: month_totals['aug'],
        9: month_totals['sep'], 10: month_totals['oct'], 11: month_totals['nov'], 12: month_totals['dec']
    }
    
    import datetime
    current_month_key = datetime.datetime.now().strftime("%b").lower()
    current_month_collection = month_totals.get(current_month_key, 0)

    return render_template("families.html", 
                           families=formatted_data, 
                           search=search,
                           total_page_members=total_page_members,
                           total_page_rs=total_page_rs,
                           total_page_uif=total_page_uif,
                           total_page_due=total_page_due,
                           total_page_grand_due=total_page_grand_due,
                           active_year=active_year,
                           view_year=view_year,
                           is_current_year_view=is_current_year_view,
                           available_years=available_years,
                           can_undo_rollover=can_undo_rollover,
                           user_is_treasurer=is_treasurer(),
                           treasury=treasury_data,
                           monthly_totals=month_totals,
                           current_month_name=current_month_key.upper(),
                           current_month_collection=current_month_collection)

@app.route("/collection/update/<int:family_id>", methods=["POST"])
def update_collection(family_id):
    if not session.get("logged_in"):
        return redirect("/login")
    if not is_treasurer():
        return redirect("/families")
    
    months_list = ['jan', 'feb', 'mar', 'apr', 'may', 'june', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
    today_str = datetime.now().strftime("%Y-%m-%d")
    active_year = get_current_collection_year()
    
    # Which year this edit applies to. Defaults to the active year if not
    # specified, but treasurer can now also correct past years' entries.
    try:
        target_year = int(request.form.get("target_year", active_year))
    except (ValueError, TypeError):
        target_year = active_year
        
    # ફોર્મમાંથી સર્ચ કરેલું નામ પકડો
    search_query = request.form.get("search", "").strip()
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    def safe_float(val, default=0.0):
        if val is None or val == '':
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default
    
    # UIF is a live/current field (not tied to a specific year), so only
    # update it when editing the active year to avoid a historical-year
    # edit accidentally changing today's UIF value.
    if target_year == active_year:
        uif_val = request.form.get(f"uif_{family_id}", "0")
        cursor.execute("UPDATE families SET uif=? WHERE id=?", (safe_float(uif_val), family_id))
    
    for m in months_list:
        amt_value = request.form.get(f"{m}_{family_id}", "0")
        amt = safe_float(amt_value)
        
        cursor.execute("SELECT id FROM payments WHERE family_id=? AND target_month=? AND year=?", (family_id, m, target_year))
        existing = cursor.fetchone()
        
        if amt > 0:
            if existing:
                cursor.execute("UPDATE payments SET amount=? WHERE family_id=? AND target_month=? AND year=?", (amt, family_id, m, target_year))
            else:
                cursor.execute("INSERT INTO payments (family_id, target_month, amount, paid_date, year) VALUES (?, ?, ?, ?, ?)",
                               (family_id, m, amt, today_str, target_year))
        elif existing:
            cursor.execute("DELETE FROM payments WHERE family_id=? AND target_month=? AND year=?", (family_id, m, target_year))
    
    conn.commit()
    conn.close()
    
    # જો સર્ચ કરેલું હોય તો સર્ચ અને વર્ષ સાથે જ તે જ પેજ પર પાછા જાઓ
    if search_query:
        return redirect(f"/families?search={search_query}&year={target_year}")
    return redirect(f"/families?year={target_year}")
    
    # UIF is a live/current field (not tied to a specific year), so only
    # update it when editing the active year to avoid a historical-year
    # edit accidentally changing today's UIF value.
    if target_year == active_year:
        uif_val = request.form.get(f"uif_{family_id}", "0")
        cursor.execute("UPDATE families SET uif=? WHERE id=?", (safe_float(uif_val), family_id))
    
    for m in months_list:
        amt_value = request.form.get(f"{m}_{family_id}", "0")
        amt = safe_float(amt_value)
        
        cursor.execute("SELECT id FROM payments WHERE family_id=? AND target_month=? AND year=?", (family_id, m, target_year))
        existing = cursor.fetchone()
        
        if amt > 0:
            if existing:
                cursor.execute("UPDATE payments SET amount=? WHERE family_id=? AND target_month=? AND year=?", (amt, family_id, m, target_year))
            else:
                cursor.execute("INSERT INTO payments (family_id, target_month, amount, paid_date, year) VALUES (?, ?, ?, ?, ?)",
                               (family_id, m, amt, today_str, target_year))
        elif existing:
            cursor.execute("DELETE FROM payments WHERE family_id=? AND target_month=? AND year=?", (family_id, m, target_year))
    
    conn.commit()
    conn.close()
    return redirect(f"/families?year={target_year}")


@app.route("/collection/delete-year", methods=["POST"])
def delete_collection_year():
    if not session.get("logged_in"):
        return redirect("/login")
    if not is_treasurer():
        return redirect("/families")
    
    active_year = get_current_collection_year()
    try:
        year_to_delete = int(request.form.get("year_to_delete", ""))
    except (ValueError, TypeError):
        return redirect("/families")
    
    # Never allow deleting the active year this way — that would wipe live
    # in-progress collection data. Use "Start New Year" / normal editing
    # for the active year instead.
    if year_to_delete == active_year:
        return redirect(f"/families?year={year_to_delete}")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM payments WHERE year=?", (year_to_delete,))
    cursor.execute("DELETE FROM rollover_log WHERE year_from=? OR year_to=?", (year_to_delete, year_to_delete))
    conn.commit()
    conn.close()
    return redirect(f"/families?year={active_year}")


@app.route("/collection/start-new-year", methods=["POST"])
def start_new_year():
    if not session.get("logged_in"):
        return redirect("/login")
    if not is_treasurer():
        return redirect("/families")

    months_list = ['jan', 'feb', 'mar', 'apr', 'may', 'june', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
    active_year = get_current_collection_year()

    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()

    cursor.execute("SELECT id, uif FROM families")
    all_families = cursor.fetchall()

    for f_id, current_uif in all_families:
        cursor.execute("SELECT COUNT(*) FROM family_members WHERE family_id=?", (f_id,))
        t_members = cursor.fetchone()[0]
        monthly_fee = t_members * 50

        cursor.execute("SELECT target_month, amount FROM payments WHERE family_id=? AND year=?", (f_id, active_year))
        pmt_records = dict(cursor.fetchall())

        # Total-based due (same formula as the family card badge): total annual fee
        # minus total actually paid this year, so lump-sum payments in any single
        # month are correctly credited toward the whole year.
        annual_expected = monthly_fee * 12
        annual_paid = sum(pmt_records.get(m, 0) for m in months_list)
        due_amount = max(0, annual_expected - annual_paid)

        new_uif = (current_uif or 0) + due_amount
        cursor.execute("UPDATE families SET uif=? WHERE id=?", (new_uif, f_id))

        # Log exactly how much was added to this family's UIF, so an accidental
        # "Start New Year" click can be precisely undone later (see /collection/undo-last-rollover).
        cursor.execute("""
            INSERT INTO rollover_log (year_from, year_to, family_id, amount_added, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (active_year, active_year + 1, f_id, due_amount, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

        # NOTE: old payment records are intentionally NOT deleted — they stay
        # in the database tagged with the old year (active_year) so the
        # month-by-month history remains available. The new year simply
        # starts writing fresh rows tagged with the new year number below.

    # Move the "active" year forward. New collection entries will be tagged
    # with this new year; old records remain untouched under the old year.
    cursor.execute("UPDATE app_settings SET value=? WHERE key='current_collection_year'", (str(active_year + 1),))

    conn.commit()
    conn.close()
    return redirect("/families")


@app.route("/collection/set-active-year", methods=["POST"])
def set_active_year():
    if not session.get("logged_in"):
        return redirect("/login")
    if not is_treasurer():
        return redirect("/families")

    try:
        new_year = int(request.form.get("new_year", "").strip())
    except (ValueError, TypeError):
        return redirect("/families")

    if 2000 <= new_year <= 2100:
        set_current_collection_year(new_year)

    return redirect("/families")


@app.route("/collection/undo-last-rollover", methods=["POST"])
def undo_last_rollover():
    if not session.get("logged_in"):
        return redirect("/login")
    if not is_treasurer():
        return redirect("/families")

    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()

    # Find the most recent rollover batch (all log rows share the same year_to)
    cursor.execute("SELECT MAX(year_to) FROM rollover_log")
    row = cursor.fetchone()
    latest_year_to = row[0] if row else None

    if latest_year_to is None:
        conn.close()
        return redirect("/families")

    cursor.execute("SELECT family_id, amount_added, year_from FROM rollover_log WHERE year_to=?", (latest_year_to,))
    entries = cursor.fetchall()

    year_from = None
    for f_id, amount_added, y_from in entries:
        year_from = y_from
        cursor.execute("SELECT uif FROM families WHERE id=?", (f_id,))
        r = cursor.fetchone()
        if r:
            new_uif = max(0, (r[0] or 0) - amount_added)
            cursor.execute("UPDATE families SET uif=? WHERE id=?", (new_uif, f_id))

    # Remove the log entries for this rollover (it's now undone) and move the
    # active year back to where it was before that rollover.
    cursor.execute("DELETE FROM rollover_log WHERE year_to=?", (latest_year_to,))
    if year_from is not None:
        cursor.execute("UPDATE app_settings SET value=? WHERE key='current_collection_year'", (str(year_from),))

    conn.commit()
    conn.close()
    return redirect("/families")

# ============================================================
# FAMILY CRUD
# ============================================================
@app.route("/family/add", methods=["GET", "POST"])
def add_family():
    if not session.get("logged_in"):
        return redirect("/login")
    
    if request.method == "POST":
        conn = sqlite3.connect("samaj.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO families (firm_name, family_name, mobile, address, uif) 
            VALUES (?, ?, ?, ?, ?)
        """, (request.form["firm_name"], 
              request.form["family_name"], 
              request.form["mobile"], 
              request.form["address"], 
              float(request.form.get("uif", 0))))
        conn.commit()
        conn.close()
        return redirect("/families")
    
    return render_template("family_add.html", family=None)

@app.route("/family/edit/<int:family_id>", methods=["GET", "POST"])
def edit_family(family_id):
    if not session.get("logged_in"):
        return redirect("/login")
    
    # જો યૂઝર ફાર્મ હેડ હોય, તો તે માત્ર પોતાની 'family_id' જ એડિટ કરી શકે!
    if session.get("role") == "farm_head" and session.get("family_id") != family_id:
        return "<h3>તમને આ પરિવારની માહિતી એડિટ કરવાની પરવાનગી નથી!</h3>", 403

        # ... બાકીનો તમારો જૂનો કોડ અહીં રહેશે ...
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    if request.method == "POST":
        cursor.execute("""
            UPDATE families 
            SET firm_name=?, family_name=?, mobile=?, address=?, uif=? 
            WHERE id=?
        """, (request.form["firm_name"], 
              request.form["family_name"], 
              request.form["mobile"], 
              request.form["address"], 
              float(request.form.get("uif", 0)), 
              family_id))
        conn.commit()
        conn.close()
        return redirect("/families")
    
    cursor.execute("SELECT id, firm_name, family_name, mobile, address, uif FROM families WHERE id=?", (family_id,))
    family = cursor.fetchone()
    conn.close()
    return render_template("family_add.html", family=family)

@app.route("/family/delete/<int:family_id>")
def delete_family(family_id):
    if not session.get("logged_in"):
        return redirect("/login")
    
    # ફક્ત ખજાનચી જ ડિલીટ કરી શકે
    if session.get("role") != "treasurer":
        return redirect("/families")
        
    # ... બાકીનો જૂનો ડિલીટ કરવાનો કોડ ...
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM family_members WHERE family_id=?", (family_id,))
    cursor.execute("DELETE FROM payments WHERE family_id=?", (family_id,))
    cursor.execute("DELETE FROM families WHERE id=?", (family_id,))
    conn.commit()
    conn.close()
    return redirect("/families")

# ============================================================
# MEMBERS SECTION
# ============================================================
@app.route("/family/<int:family_id>/members")
def family_members(family_id):
    if not session.get("logged_in"):
        return redirect("/login")
    
    user_role = session.get("role")
    user_family_id = session.get("family_id")
    
    # જો યૂઝર ફાર્મ હેડ (farm_head) હોય, તો તે ફક્ત પોતાના જ પરિવારની આઈડી જોઈ શકે!
    if user_role == "farm_head" and str(user_family_id) != str(family_id):
        return "<h3>તમને આ પરિવારના સભ્યો જોવાની પરવાનગી નથી!</h3>", 403
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, family_id, name, mobile, business_study, birth_date 
        FROM family_members 
        WHERE family_id=?
    """, (family_id,))
    members_raw = cursor.fetchall()
    
    members_data = [(m[0], m[1], m[2], m[3] if m[3] else "-", m[4] if m[4] else "-", format_date_to_indian(m[5])) 
                    for m in members_raw]
    
    cursor.execute("SELECT family_name, firm_name FROM families WHERE id=?", (family_id,))
    family = cursor.fetchone() or ("Unknown", "Unknown")
    conn.close()
    
    return render_template("members.html", members=members_data, family=family, family_id=family_id)

@app.route("/family/<int:family_id>/add-member", methods=["GET", "POST"])
def add_member(family_id):
    if not session.get("logged_in"):
        return redirect("/login")
    
    if request.method == "POST":
        db_bdate = format_date_to_db(request.form["birth_date"])
        conn = sqlite3.connect("samaj.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO family_members (family_id, name, mobile, business_study, birth_date, house_number) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, (family_id, 
              request.form["name"], 
              request.form.get("mobile", ""), 
              request.form.get("business_study", ""), 
              db_bdate,
              request.form.get("house_number", "1") or "1"))
        conn.commit()
        conn.close()
        return redirect(f"/family/{family_id}/members")
    
    return render_template("member_add.html", family_id=family_id, member=None)

@app.route("/family/<int:family_id>/edit-member/<int:member_id>", methods=["GET", "POST"])
def edit_member(family_id, member_id):
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    if request.method == "POST":
        db_bdate = format_date_to_db(request.form["birth_date"])
        cursor.execute("""
            UPDATE family_members 
            SET name=?, mobile=?, business_study=?, birth_date=?, blood_group=?, house_number=? 
            WHERE id=?
        """, (request.form["name"], 
              request.form.get("mobile", ""), 
              request.form.get("education", "") or request.form.get("business_study", ""), 
              db_bdate, 
              request.form.get("blood_group", ""),
              request.form.get("house_number", "1") or "1",
              member_id))
        conn.commit()
        conn.close()
        return redirect(f"/family/{family_id}/members")
    
    cursor.execute("""
        SELECT id, family_id, name, mobile, business_study, birth_date, blood_group, house_number 
        FROM family_members 
        WHERE id=?
    """, (member_id,))
    m = cursor.fetchone()
    conn.close()
    
    if not m:
        return "<h3>સભ્ય મળ્યો નથી!</h3>"
        
    # ડેટાબેઝના ઇન્ડેક્સ મુજબ મોબાઈલ અને બિઝનેસને પ્રોપર મેચ કરો
    raw_mobile = m[3] if m[3] else ""
    raw_bus = m[4] if m[4] else ""
    
    # જો મોબાઇલના ખાનામાં ટેક્સ્ટ હોય અને બિઝનેસના ખાનામાં નંબર હોય તો ઓટોમેટિક સ્વેપ કરી લો
    if raw_mobile and not raw_mobile.isdigit() and raw_bus.isdigit():
        final_mobile, final_bus = raw_bus, raw_mobile
    else:
        final_mobile, final_bus = raw_mobile, raw_bus

    member = (
        m[0], # 0: id
        m[1], # 1: family_id
        m[2], # 2: name
        format_date_to_indian(m[5]) if m[5] else "", # 3: birth_date
        final_mobile, # 4: mobile
        final_bus,    # 5: business_study / education
        m[6] if len(m) > 6 and m[6] else "", # 6: blood_group
        m[7] if len(m) > 7 and m[7] else "1"  # 7: house_number
    )
    return render_template("member_add.html", family_id=family_id, member=member)

@app.route("/family/<int:family_id>/delete-member/<int:member_id>")
def delete_member(family_id, member_id):
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM family_members WHERE id=?", (member_id,))
    conn.commit()
    conn.close()
    return redirect(f"/family/{family_id}/members")

# ============================================================
# blood_group_detail
# ============================================================
def get_db_connection():
    conn = sqlite3.connect("samaj.db")
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/blood-group/<blood_group>')
def blood_group_detail(blood_group):
    conn = get_db_connection()
    if blood_group.upper() == 'ALL':
        members = conn.execute("SELECT * FROM family_members WHERE blood_group IS NOT NULL AND blood_group != ''").fetchall()
        blood_group = "બધા જ"
    else:
        members = conn.execute("SELECT * FROM family_members WHERE blood_group = ?", (blood_group,)).fetchall()
    conn.close()
    return render_template('blood_group_detail.html', members=members, blood_group=blood_group)
@app.route('/blood-report')
def blood_report():
    if not session.get("logged_in"):
        return redirect("/login")
    return redirect('/families')
# ============================================================
# 🩸 બ્લડ ગ્રૂપ એક્સેલ એક્સપોર્ટ
# ============================================================
@app.route('/export/blood-group/<blood_group>/excel')
def export_blood_group_excel(blood_group):
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = get_db_connection()
    members = conn.execute("SELECT * FROM family_members WHERE blood_group = ?", (blood_group,)).fetchall()
    conn.close()
    
    output = io.StringIO()
    output.write('\ufeff')
    output.write("ક્રમ,સભ્યનું નામ,મોબાઈલ,બ્લડ ગ્રૂપ,અભ્યાસ/ધંધો,સરનામું\n")
    
    for idx, m in enumerate(members, start=1):
        name = m['name'] if 'name' in m and m['name'] else "-"
        mobile = m['mobile'] if 'mobile' in m and m['mobile'] else "-"
        bg = m['blood_group'] if 'blood_group' in m and m['blood_group'] else "-"
        bs = m['business_study'] if 'business_study' in m and m['business_study'] else "-"
        output.write(f'"{idx}","{name}","{mobile}","{bg}","{bs}"\n')
    
    buf = io.BytesIO()
    buf.write(output.getvalue().encode('utf-8-sig'))
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"blood_group_{blood_group}.csv", mimetype="text/csv")

# ============================================================
# 🩸 બ્લડ ગ્રૂપ પીડીએફ એક્સપોર્ટ (ગુજરાતી સપોર્ટ સાથે)
# ============================================================
@app.route('/export/blood-group/<blood_group>/pdf')
def export_blood_group_pdf(blood_group):
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = get_db_connection()
    members = conn.execute("SELECT * FROM family_members WHERE blood_group = ?", (blood_group,)).fetchall()
    conn.close()
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=20, leftMargin=20, topMargin=30, bottomMargin=30)
    story = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, alignment=1, spaceAfter=4, textColor=colors.HexColor("#dc3545"))
    sub_style = ParagraphStyle('SubTitle', parent=styles['Normal'], fontSize=12, alignment=1, spaceAfter=16, textColor=colors.HexColor("#64748b"))
    cell_style = ParagraphStyle('Cell', parent=styles['Normal'], fontSize=9, alignment=1, leading=12)
    header_cell_style = ParagraphStyle('HeaderCell', parent=styles['Normal'], fontSize=10, alignment=1, textColor=colors.white, leading=12)
    
    story.append(Paragraph(f"<b>{guj_mix('શ્રી કચ્છ કડવા પાટીદાર સત્સંગ સમાજ')}</b>", title_style))
    story.append(Paragraph(f"<b>{guj_mix(f'બ્લડ ગ્રૂપ: {blood_group} - સભ્યોની યાદી (કુલ સભ્યો: {len(members)})')}</b>", sub_style))
    
    data = [[
        Paragraph(f"<b>{guj_mix('ક્રમ')}</b>", header_cell_style),
        Paragraph(f"<b>{guj_mix('સભ્યનું નામ')}</b>", header_cell_style),
        Paragraph(f"<b>{guj_mix('મોબાઈલ')}</b>", header_cell_style),
        Paragraph(f"<b>{guj_mix('બ્લડ ગ્રૂપ')}</b>", header_cell_style),
        Paragraph(f"<b>{guj_mix('જન્મ તારીખ')}</b>", header_cell_style),
        Paragraph(f"<b>{guj_mix('ઉંમર')}</b>", header_cell_style)
    ]]
    
    for idx, m in enumerate(members, start=1):
        bdate_raw = m['birth_date'] if 'birth_date' in m and m['birth_date'] else ""
        formatted_bdate = format_date_to_indian(bdate_raw) if bdate_raw else "-"
        age = calculate_age(bdate_raw) if bdate_raw else "-"
        
        data.append([
            str(idx),
            Paragraph(guj_mix(m['name'] if 'name' in m and m['name'] else "-"), cell_style),
            str(m['mobile'] if 'mobile' in m and m['mobile'] else "-"),
            str(m['blood_group'] if 'blood_group' in m and m['blood_group'] else "-"),
            str(formatted_bdate),
            str(age)
        ])
    
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#dc3545")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")])
    ]))
    story.append(t)
    
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"blood_group_{blood_group}.pdf", mimetype="application/pdf")


# ============================================================
# HOUSE-WISE LIST (ઘર / ચૂલા પ્રમાણે યાદી)
# ============================================================
def _get_house_list_data(search="", head_only=False):
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()

    if search:
        cursor.execute("""
            SELECT id, firm_name, family_name FROM families
            WHERE firm_name LIKE ? OR family_name LIKE ?
            ORDER BY firm_name ASC
        """, (f"%{search}%", f"%{search}%"))
    else:
        cursor.execute("SELECT id, firm_name, family_name FROM families ORDER BY firm_name ASC")
    families = cursor.fetchall()

    result = []
    for f_id, firm_name, family_name in families:
        cursor.execute("""
            SELECT house_number, name, mobile, business_study, birth_date, is_head
            FROM family_members WHERE family_id=?
            ORDER BY house_number ASC, name ASC
        """, (f_id,))
        members = cursor.fetchall()
        if not members:
            continue

        houses = {}
        for house_num, name, mobile, business_study, birth_date, is_head in members:
            if head_only and not is_head:
                continue
            house_key = house_num or "1"
            if house_key not in houses:
                houses[house_key] = []
            houses[house_key].append({
                'name': name,
                'mobile': mobile or '-',
                'business_study': business_study or '-',
                'birth_date': format_date_to_indian(birth_date) if birth_date else '-',
                'is_head': bool(is_head)
            })

        if not houses:
            continue

        # Sort houses numerically where possible, else alphabetically
        def house_sort_key(h):
            try:
                return (0, int(h))
            except ValueError:
                return (1, h)

        sorted_houses = sorted(houses.items(), key=lambda kv: house_sort_key(kv[0]))

        result.append({
            'family_id': f_id,
            'firm_name': firm_name,
            'family_name': family_name,
            'houses': sorted_houses,
            'house_count': len(sorted_houses)
        })

    conn.close()
    return result


@app.route("/house-list")
def house_list():
    if not session.get("logged_in"):
        return redirect("/login")
        
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    user_role = session.get("role")
    search = request.args.get("search", "")
    
    can_edit = (user_role in ["treasurer", "committee"])
    user_is_treasurer = (user_role == "treasurer")
    
    # પરિવારની યાદી મેળવો (સર્ચ મુજબ અથવા બધી)
    if search:
        cursor.execute("SELECT id, family_name, firm_name, mobile, uif FROM families WHERE family_name LIKE ? OR firm_name LIKE ?", 
                       (f"%{search}%", f"%{search}%"))
    else:
        cursor.execute("SELECT id, family_name, firm_name, mobile, uif FROM families")
        
    family_rows = cursor.fetchall()
    
    families = []
    total_houses_count = 0
    total_members_count = 0
    
    for fam in family_rows:
        fam_id = fam[0]
        family_name = fam[1]
        firm_name = fam[2]
        
        # અહીં સાચું ટેબલ નામ 'family_members' વાપરવામાં આવ્યું છે
        cursor.execute("SELECT house_number, name, mobile, birth_date, is_head FROM family_members WHERE family_id = ? ORDER BY house_number, is_head DESC", (fam_id,))
        member_rows = cursor.fetchall()
        
        houses_dict = {}
        for m in member_rows:
            h_num = m[0] if m[0] else "1"
            if h_num not in houses_dict:
                houses_dict[h_num] = []
            houses_dict[h_num].append({
                "name": m[1],
                "mobile": m[2],
                "birth_date": m[3],
                "is_head": m[4]
            })
            total_members_count += 1
            
        houses_list = list(houses_dict.items())
        total_houses_count += len(houses_list)
        
        if houses_list:
            families.append({
                "family_id": fam_id,
                "family_name": family_name,
                "firm_name": firm_name,
                "house_count": len(houses_list),
                "houses": houses_list
            })
            
    conn.close()
    
    return render_template("house_list.html", 
                           families=families, 
                           total_houses=total_houses_count, 
                           total_members=total_members_count, 
                           search=search, 
                           user_is_treasurer=user_is_treasurer, 
                           can_edit=can_edit)


@app.route("/house-list/manage/<int:family_id>", methods=["GET", "POST"])
def manage_chulas(family_id):
    if not session.get("logged_in"):
        return redirect("/login")

    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()

    cursor.execute("SELECT id, firm_name, family_name FROM families WHERE id=?", (family_id,))
    fam = cursor.fetchone()
    if not fam:
        conn.close()
        return "<h3>પરિવાર મળ્યો નથી!</h3>"

    if request.method == "POST":
        cursor.execute("SELECT id FROM family_members WHERE family_id=?", (family_id,))
        member_ids = [r[0] for r in cursor.fetchall()]
        
        # First, save each member's chula number
        for m_id in member_ids:
            chula_val = request.form.get(f"chula_{m_id}", "1").strip() or "1"
            cursor.execute("UPDATE family_members SET house_number=? WHERE id=?", (chula_val, m_id))
        
        # Then apply head selection: the form sends one radio value per chula
        # group (head_for_chula_<chula_number> = member_id), so exactly one
        # head is possible per chula. Reset all, then mark the chosen ones.
        cursor.execute("UPDATE family_members SET is_head=0 WHERE family_id=?", (family_id,))
        cursor.execute("SELECT DISTINCT house_number FROM family_members WHERE family_id=?", (family_id,))
        chula_numbers = [r[0] for r in cursor.fetchall()]
        for chula_num in chula_numbers:
            chosen_head = request.form.get(f"head_for_chula_{chula_num}")
            if chosen_head:
                cursor.execute("UPDATE family_members SET is_head=1 WHERE id=? AND family_id=?", (chosen_head, family_id))
            else:
                # No head explicitly chosen for this chula — default to the
                # first member in it, so the export always has a main person.
                cursor.execute("SELECT id FROM family_members WHERE family_id=? AND house_number=? ORDER BY id ASC LIMIT 1", (family_id, chula_num))
                fallback = cursor.fetchone()
                if fallback:
                    cursor.execute("UPDATE family_members SET is_head=1 WHERE id=?", (fallback[0],))
        
        conn.commit()
        conn.close()
        return redirect("/house-list")

    cursor.execute("""
        SELECT id, name, mobile, house_number, is_head FROM family_members
        WHERE family_id=? ORDER BY house_number ASC, name ASC
    """, (family_id,))
    members = cursor.fetchall()
    conn.close()

    distinct_chulas = sorted(set((m[3] or "1") for m in members), key=lambda x: (0, int(x)) if x.isdigit() else (1, x))

    return render_template("manage_chulas.html",
                          family_id=family_id,
                          firm_name=fam[1],
                          family_name=fam[2],
                          members=members,
                          distinct_chulas=distinct_chulas)


@app.route("/house-list/export/pdf")
def export_house_list_pdf():
    if not session.get("logged_in"):
        return redirect("/login")

    mode = request.args.get("mode", "all")
    head_only = (mode == "head")
    data = _get_house_list_data(head_only=head_only)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=15, alignment=1, spaceAfter=5, textColor=colors.HexColor("#1e3a8a"))
    sub_style = ParagraphStyle('SubTitle', parent=styles['Normal'], fontSize=12, alignment=1, spaceAfter=15, textColor=colors.HexColor("#1e3a8a"))
    story.append(Paragraph(f"<b>{guj_mix('શ્રી કચ્છ કડવા પાટીદાર સત્સંગ સમાજ પ્રેરિત')}</b>", title_style))
    subtitle_text = 'ચૂલા પ્રમાણે યાદી (ફક્ત મુખ્ય વ્યક્તિ)' if head_only else 'ચૂલા પ્રમાણે યાદી (બધા સભ્યો)'
    story.append(Paragraph(f"<b>{guj_mix(subtitle_text)}</b>", sub_style))

    cell_style = ParagraphStyle('Cell', parent=styles['Normal'], fontSize=8, alignment=1, leading=10)
    header_style = ParagraphStyle('Header', parent=styles['Normal'], fontSize=8, alignment=1, textColor=colors.white, leading=10)

    header_row = ["ક્રમ", "ફાર્મ / પરિવારનું નામ", "ઘર નં.", "સભ્યનું નામ", "મોબાઈલ", "જન્મ તારીખ"]
    data_rows = [[Paragraph(guj_mix(h), header_style) for h in header_row]]

    idx = 1
    for fam in data:
        for house_num, members in fam['houses']:
            for m in members:
                data_rows.append([
                    str(idx),
                    Paragraph(guj_mix(f"{fam['firm_name']} ({fam['family_name']})"), cell_style),
                    Paragraph(guj_mix(house_num), cell_style),
                    Paragraph(guj_mix(m['name'] + (' ⭐' if m.get('is_head') and not head_only else '')), cell_style),
                    str(m['mobile']),
                    str(m['birth_date']),
                ])
                idx += 1

    if len(data_rows) == 1:
        data_rows.append([Paragraph(guj_mix("કોઈ સભ્ય નથી"), cell_style)] + [""] * 5)

    t = Table(data_rows, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1e3a8a")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('FONTNAME', (0,1), (0,-1), 'Helvetica'),
        ('FONTNAME', (4,1), (5,-1), 'Helvetica'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")])
    ]))
    story.append(t)
    doc.build(story)
    buffer.seek(0)
    download_name = "chula_head_list.pdf" if head_only else "chula_full_list.pdf"
    return send_file(buffer, as_attachment=True, download_name=download_name, mimetype="application/pdf")


@app.route("/house-list/export/excel")
def export_house_list_excel():
    if not session.get("logged_in"):
        return redirect("/login")

    mode = request.args.get("mode", "all")
    head_only = (mode == "head")
    data = _get_house_list_data(head_only=head_only)

    output = io.StringIO()
    output.write('\ufeff')
    output.write("ક્રમ,ફાર્મ / પરિવારનું નામ,ઘર નં.,સભ્યનું નામ,મુખ્ય વ્યક્તિ,મોબાઈલ,જન્મ તારીખ\n")

    idx = 1
    for fam in data:
        for house_num, members in fam['houses']:
            for m in members:
                head_mark = "હા" if m.get('is_head') else "ના"
                output.write(f'"{idx}","{fam["firm_name"]} ({fam["family_name"]})","{house_num}","{m["name"]}","{head_mark}","{m["mobile"]}","{m["birth_date"]}"\n')
                idx += 1

    buf = io.BytesIO()
    buf.write(output.getvalue().encode('utf-8-sig'))
    buf.seek(0)
    excel_download_name = "chula_head_list.csv" if head_only else "chula_full_list.csv"
    return send_file(buf, as_attachment=True, download_name=excel_download_name, mimetype="text/csv")


@app.route("/member/add-public", methods=["GET", "POST"])
def add_member_public():
    if request.method == "POST":
        # ફોર્મમાંથી આવતી વિગતોને બરાબર સાચા નામે પકડો
        family_id = request.form.get("family_id")
        name = request.form.get("member_name") or request.form.get("name", "")
        mobile = request.form.get("mobile_number") or request.form.get("mobile", "")
        business_study = request.form.get("business_study", "")
        birth_date = format_date_to_db(request.form.get("birth_date", ""))
        blood_group = request.form.get("blood_group", "")
        house_number = request.form.get("house_number", "1")
        
        conn = sqlite3.connect("samaj.db")
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, firm_name, family_name FROM families WHERE id=?", (family_id,))
        fam_row = cursor.fetchone()
        if not fam_row:
            conn.close()
            return "<h3>પરિવાર મળી નથી!</h3>"
        
        cursor.execute("""
        INSERT INTO family_members (family_id, name, mobile, business_study, birth_date, blood_group, house_number)
         VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (family_id, name, mobile, business_study, birth_date, blood_group, house_number))
        conn.commit()
        conn.close()
        
        # Keep the same family selected so multiple members can be added back-to-back
        # without re-searching the dropdown each time.
        return redirect(f"/member/add-public?family_id={family_id}&added=1")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, firm_name, family_name FROM families ORDER BY firm_name ASC")
    families = cursor.fetchall()
    conn.close()
    
    families_for_js = [{"id": f[0], "label": f"{f[1]} ({f[2]})"} for f in families]
    
    selected_family_id = request.args.get("family_id", "")
    just_added = request.args.get("added") == "1"
    selected_family_label = ""
    if selected_family_id:
        for f in families:
            if str(f[0]) == str(selected_family_id):
                selected_family_label = f"{f[1]} ({f[2]})"
                break
    
    return render_template("member_add_public.html", 
                          families=families, 
                          families_for_js=families_for_js,
                          success=False,
                          selected_family_id=selected_family_id,
                          selected_family_label=selected_family_label,
                          just_added=just_added)

# ============================================================
# EVENTS SYSTEM
# ============================================================
@app.route("/events")
def events():
    if not session.get("logged_in"):
        return redirect("/login")
    if session.get("role") != "treasurer":
        return "<h3>તમને ઇવેન્ટ્સ મેનુ એક્સેસ કરવાની પરવાનગી નથી!</h3>", 403
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, event_name, event_date, deadline_date, event_type FROM events ORDER BY id DESC")
    events_data = cursor.fetchall()
    
    events_list = []
    for ev in events_data:
        ev_id, name, e_date, d_date, ev_type = ev
        cursor.execute("SELECT COUNT(*) FROM rsvp WHERE event_id=?", (ev_id,))
        total_entries = cursor.fetchone()[0]
        
        events_list.append({
            'id': ev_id,
            'name': name,
            'date': format_date_to_indian(e_date),
            'deadline': format_date_to_indian(d_date),
            'type': ev_type,
            'total_entries': total_entries,
            'link': f"{request.host_url.rstrip('/')}/rsvp/{ev_id}"
        })
    
    conn.close()
    return render_template("events.html", events=events_list)

@app.route("/event/add", methods=["GET", "POST"])
def add_event():
    if not session.get("logged_in"):
        return redirect("/login")
    
    if request.method == "POST":
        conn = sqlite3.connect("samaj.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO events (event_name, event_date, deadline_date, event_type) 
            VALUES (?, ?, ?, ?)
        """, (request.form["event_name"], 
              format_date_to_db(request.form["event_date"]), 
              format_date_to_db(request.form["deadline_date"]), 
              request.form["event_type"]))
        conn.commit()
        conn.close()
        return redirect("/events")
    
    return render_template("event_add.html", event=None)

@app.route("/event/edit/<int:event_id>", methods=["GET", "POST"])
def edit_event(event_id):
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    if request.method == "POST":
        cursor.execute("""
            UPDATE events 
            SET event_name=?, event_date=?, deadline_date=?, event_type=? 
            WHERE id=?
        """, (request.form["event_name"], 
              format_date_to_db(request.form["event_date"]), 
              format_date_to_db(request.form["deadline_date"]), 
              request.form["event_type"], 
              event_id))
        conn.commit()
        conn.close()
        return redirect("/events")
    
    cursor.execute("SELECT id, event_name, event_date, deadline_date, event_type FROM events WHERE id=?", (event_id,))
    ev = cursor.fetchone()
    conn.close()
    
    event = (ev[0], ev[1], format_date_to_indian(ev[2]), format_date_to_indian(ev[3]), ev[4])
    return render_template("event_add.html", event=event)

@app.route("/event/delete/<int:event_id>")
def delete_event(event_id):
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM rsvp WHERE event_id=?", (event_id,))
    cursor.execute("DELETE FROM events WHERE id=?", (event_id,))
    conn.commit()
    conn.close()
    return redirect("/events")

# ============================================================
# VIEW EVENT ENTRIES
# ============================================================
@app.route("/event/view/<int:event_id>")
def view_event_entries(event_id):
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    ev_info = cursor.execute("SELECT event_name, event_type FROM events WHERE id=?", (event_id,)).fetchone()
    if not ev_info:
        conn.close()
        return "ઇવેન્ટ મળી નથી."
    
    cursor.execute("""
        SELECT 
            r.id, r.family_id, r.member_name, r.mobile_number, 
            r.standard, r.percentage, r.item_name, r.performance_type, 
            r.file_path, r.head_count, r.leader_name, r.leader_mobile,
            r.participants_count, r.participants_names, r.program_duration,
            r.academic_year, r.semester, r.total_marks, r.obtained_marks,
            r.other_info
        FROM rsvp r
        WHERE r.event_id = ?
        ORDER BY r.id DESC
    """, (event_id,))
    raw_entries = cursor.fetchall()
    
    formatted_entries = []
    total_head_count = 0
    
    for r in raw_entries:
        firm_title = "Unknown"
        if r[1]:
            f_info = cursor.execute("SELECT firm_name, family_name FROM families WHERE id=?", (r[1],)).fetchone()
            if f_info:
                firm_title = f"{f_info[0]} ({f_info[1]})"
        
        head_count = int(r[9]) if r[9] is not None and r[9] != '' else 0
        total_head_count += head_count
        
        file_path = r[8]
        if file_path and not file_path.startswith('/') and not file_path.startswith('http'):
            file_path = '/' + file_path
        
        formatted_entries.append({
            'id': r[0],
            'firm_name': firm_title,
            'member_name': r[2] or '-',
            'mobile_number': r[3] or '-',
            'standard': r[4] or '-',
            'percentage': r[5] or '-',
            'item_name': r[6] or '-',
            'performance_type': r[7],
            'file_path': file_path,
            'head_count': head_count,
            'leader_name': r[10] or '-',
            'leader_mobile': r[11] or '-',
            'participants_count': r[12] or 0,
            'participants_names': r[13] or '',
            'program_duration': r[14] or '-',
            'academic_year': r[15] or '-',
            'semester': r[16] or '-',
            'total_marks': r[17] or '-',
            'obtained_marks': r[18] or '-',
            'other_info': r[19] or '-'
        })
    
    conn.close()
    
    return render_template("event_entries.html", 
                          entries=formatted_entries, 
                          event_name=ev_info[0], 
                          event_type=ev_info[1], 
                          event_id=event_id,
                          total_head_count=total_head_count)

# ============================================================
# EVENT ENTRIES EXPORTS - PDF & EXCEL
# ============================================================
def _get_event_entries_export_data(event_id):
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()

    ev_info = cursor.execute("SELECT event_name, event_type FROM events WHERE id=?", (event_id,)).fetchone()
    if not ev_info:
        conn.close()
        return None, None, None, None

    cursor.execute("""
        SELECT 
            r.id, r.family_id, r.member_name, r.mobile_number, 
            r.item_name, r.performance_type, r.head_count,
            r.participants_count, r.participants_names, r.file_path,
            r.leader_name, r.leader_mobile,
            r.standard, r.academic_year, r.semester,
            r.total_marks, r.obtained_marks, r.percentage
        FROM rsvp r
        WHERE r.event_id = ?
        ORDER BY r.id DESC
    """, (event_id,))
    raw_entries = cursor.fetchall()

    formatted_entries = []
    total_head_count = 0
    for r in raw_entries:
        firm_title = "-"
        if r[1]:
            f_info = cursor.execute("SELECT firm_name, family_name FROM families WHERE id=?", (r[1],)).fetchone()
            if f_info:
                firm_title = f"{f_info[0]} ({f_info[1]})"
        head_count = int(r[6]) if r[6] is not None and r[6] != '' else 0
        total_head_count += head_count

        file_path = r[9]
        file_link = ""
        if file_path:
            if file_path.startswith('http'):
                file_link = file_path
            else:
                if not file_path.startswith('/'):
                    file_path = '/' + file_path
                file_link = request.host_url.rstrip('/') + file_path

        formatted_entries.append({
            'firm_name': firm_title,
            'member_name': r[2] or '-',
            'mobile_number': r[3] or '-',
            'item_name': r[4] or '-',
            'performance_type': r[5] or '-',
            'head_count': head_count,
            'participants_count': r[7] or 0,
            'participants_names': r[8] or '-',
            'file_link': file_link or '-',
            'leader_name': r[10] or '-',
            'leader_mobile': r[11] or '-',
            'standard': r[12] or '-',
            'academic_year': r[13] or '-',
            'semester': r[14] or '-',
            'total_marks': r[15] or '-',
            'obtained_marks': r[16] or '-',
            'percentage': r[17] or '-',
        })

    conn.close()
    return ev_info[0], ev_info[1], formatted_entries, total_head_count


@app.route("/event/<int:event_id>/export/pdf")
def export_event_entries_pdf(event_id):
    if not session.get("logged_in"):
        return redirect("/login")

    event_name, event_type, entries, total_head_count = _get_event_entries_export_data(event_id)
    if event_name is None:
        return "ઇવેન્ટ મળી નથી."

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=15, alignment=1, spaceAfter=5, textColor=colors.HexColor("#1e3a8a"))
    sub_style = ParagraphStyle('SubTitle', parent=styles['Normal'], fontSize=12, alignment=1, spaceAfter=15, textColor=colors.HexColor("#1e3a8a"))
    cell_style = ParagraphStyle('Cell', parent=styles['Normal'], fontSize=8, alignment=1, leading=10)
    header_style = ParagraphStyle('Header', parent=styles['Normal'], fontSize=8, alignment=1, textColor=colors.white, leading=10)

    story.append(Paragraph(f"<b>{guj_mix(event_name)}</b>", title_style))
    type_label = {'culture': 'સાંસ્કૃતિક', 'saraswati': 'સરસ્વતી', 'jamvanu': 'જમવાનું'}.get(event_type, event_type or '-')
    story.append(Paragraph(guj_mix(f"પ્રકાર: {type_label}  |  કુલ હેડ કાઉન્ટ: {total_head_count}"), sub_style))

    if event_type == 'culture':
        header_row = ["ક્રમ", "પરિવાર", "સભ્ય", "મોબાઈલ", "ટીમ લીડરનું નામ", "ટીમ લીડર મોબાઈલ", "વસ્તુ", "પ્રકાર", "સહભાગીઓની સંખ્યા", "સહભાગીઓના નામ"]
        data = [[Paragraph(guj_mix(h), header_style) for h in header_row]]
        for idx, e in enumerate(entries, start=1):
            data.append([
                str(idx),
                Paragraph(guj_mix(e['firm_name']), cell_style),
                Paragraph(guj_mix(e['member_name']), cell_style),
                str(e['mobile_number']),
                Paragraph(guj_mix(e['leader_name']), cell_style),
                str(e['leader_mobile']),
                Paragraph(guj_mix(e['item_name']), cell_style),
                Paragraph(guj_mix(type_label), cell_style),
                str(e['participants_count']) if e['participants_count'] else "-",
                Paragraph(guj_mix(e['participants_names']), cell_style),
            ])
        if not entries:
            data.append([Paragraph(guj_mix("કોઈ એન્ટ્રી નથી"), cell_style)] + [""] * 9)

    elif event_type == 'saraswati':
        header_row = ["ક્રમ", "પરિવાર", "વિદ્યાર્થીનું નામ", "મોબાઈલ નંબર", "ધોરણ / કલાસ", "શૈક્ષણિક વર્ષ", "સેમેસ્ટર", "કુલ ગુણ", "મેળવેલ ગુણ", "ટકાવારી (%)"]
        data = [[Paragraph(guj_mix(h), header_style) for h in header_row]]
        for idx, e in enumerate(entries, start=1):
            data.append([
                str(idx),
                Paragraph(guj_mix(e['firm_name']), cell_style),
                Paragraph(guj_mix(e['member_name']), cell_style),
                str(e['mobile_number']),
                Paragraph(guj_mix(e['standard']), cell_style),
                Paragraph(guj_mix(e['academic_year']), cell_style),
                Paragraph(guj_mix(e['semester']), cell_style),
                str(e['total_marks']),
                str(e['obtained_marks']),
                str(e['percentage']),
            ])
        if not entries:
            data.append([Paragraph(guj_mix("કોઈ એન્ટ્રી નથી"), cell_style)] + [""] * 9)

    else:
        header_row = ["ક્રમ", "પરિવાર", "સભ્ય", "મોબાઈલ", "હેડ કાઉન્ટ", "વસ્તુ", "પ્રકાર", "સહભાગીઓ"]
        data = [[Paragraph(guj_mix(h), header_style) for h in header_row]]
        for idx, e in enumerate(entries, start=1):
            participants = f"{e['participants_count']}" if e['participants_count'] else "-"
            if e['participants_names'] and e['participants_names'] != '-':
                participants += f" ({e['participants_names'][:40]})"
            data.append([
                str(idx),
                Paragraph(guj_mix(e['firm_name']), cell_style),
                Paragraph(guj_mix(e['member_name']), cell_style),
                str(e['mobile_number']),
                str(e['head_count']) if e['head_count'] else "-",
                Paragraph(guj_mix(e['item_name']), cell_style),
                Paragraph(guj_mix(type_label if e['performance_type'] == event_type else (e['performance_type'] or '-')), cell_style),
                Paragraph(guj_mix(participants), cell_style),
            ])
        if not entries:
            data.append([Paragraph(guj_mix("કોઈ એન્ટ્રી નથી"), cell_style)] + [""] * 7)

    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1e3a8a")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")])
    ]))
    story.append(t)

    footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=10, alignment=1, spaceBefore=12, textColor=colors.HexColor("#1e3a8a"))
    story.append(Paragraph(guj_mix(f"કુલ એન્ટ્રીઝ: {len(entries)}  |  કુલ હેડ કાઉન્ટ: {total_head_count}"), footer_style))

    doc.build(story)
    buffer.seek(0)
    safe_name = "".join(c for c in event_name if c.isalnum() or c in (' ', '_')).strip().replace(' ', '_') or "event"
    return send_file(buffer, as_attachment=True, download_name=f"{safe_name}_entries.pdf", mimetype="application/pdf")


@app.route("/event/<int:event_id>/export/excel")
def export_event_entries_excel(event_id):
    if not session.get("logged_in"):
        return redirect("/login")

    event_name, event_type, entries, total_head_count = _get_event_entries_export_data(event_id)
    if event_name is None:
        return "ઇવેન્ટ મળી નથી."

    def hyperlink_cell(link):
        if link and link != "-":
            url_escaped = link.replace('"', '""')
            return f'"=HYPERLINK(""{url_escaped}"",""ફાઈલ ખોલો"")"'
        return '"-"'

    output = io.StringIO()
    output.write('\ufeff')

    if event_type == 'culture':
        output.write("ક્રમ,પરિવાર,સભ્ય,મોબાઈલ,ટીમ લીડરનું નામ,ટીમ લીડર મોબાઈલ નંબર,વસ્તુ,પ્રકાર,સહભાગીઓની સંખ્યા,સહભાગીઓના નામ,ફાઈલ લિંક\n")
        for idx, e in enumerate(entries, start=1):
            file_cell = hyperlink_cell(e["file_link"])
            output.write(f'"{idx}","{e["firm_name"]}","{e["member_name"]}","{e["mobile_number"]}","{e["leader_name"]}","{e["leader_mobile"]}","{e["item_name"]}","{e["performance_type"]}","{e["participants_count"]}","{e["participants_names"]}",{file_cell}\n')

    elif event_type == 'saraswati':
        output.write("ક્રમ,પરિવાર,વિદ્યાર્થીનું નામ,મોબાઈલ નંબર,ધોરણ / કલાસ,શૈક્ષણિક વર્ષ,સેમેસ્ટર,કુલ ગુણ,મેળવેલ ગુણ,ટકાવારી (%),ફાઈલ લિંક\n")
        for idx, e in enumerate(entries, start=1):
            file_cell = hyperlink_cell(e["file_link"])
            output.write(f'"{idx}","{e["firm_name"]}","{e["member_name"]}","{e["mobile_number"]}","{e["standard"]}","{e["academic_year"]}","{e["semester"]}","{e["total_marks"]}","{e["obtained_marks"]}","{e["percentage"]}",{file_cell}\n')

    else:
        output.write("ક્રમ,પરિવાર,સભ્ય,મોબાઈલ,હેડ કાઉન્ટ,વસ્તુ,પ્રકાર,સહભાગીઓની સંખ્યા,સહભાગીઓના નામ,ફાઈલ લિંક\n")
        for idx, e in enumerate(entries, start=1):
            file_cell = hyperlink_cell(e["file_link"])
            output.write(f'"{idx}","{e["firm_name"]}","{e["member_name"]}","{e["mobile_number"]}","{e["head_count"]}","{e["item_name"]}","{e["performance_type"]}","{e["participants_count"]}","{e["participants_names"]}",{file_cell}\n')

    buf = io.BytesIO()
    buf.write(output.getvalue().encode('utf-8-sig'))
    buf.seek(0)
    safe_name = "".join(c for c in event_name if c.isalnum() or c in (' ', '_')).strip().replace(' ', '_') or "event"
    return send_file(buf, as_attachment=True, download_name=f"{safe_name}_entries.csv", mimetype="text/csv")

# ============================================================
# RSVP PUBLIC - 3 SEPARATE TEMPLATES
# ============================================================
# RSVP POST - Success response (without any button)
@app.route("/rsvp/<int:event_id>/lookup/<int:family_id>")
def rsvp_lookup_existing(event_id, family_id):
    """Public JSON endpoint used by the RSVP forms: when a family selects
    themselves from the dropdown, this returns their previously submitted
    entry (if any) for this event, so the form can pre-fill instead of
    showing blank fields (which is what caused edited entries to not match
    what was actually saved before)."""
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT member_name, mobile_number, head_count, item_name, leader_name,
               leader_mobile, participants_count, participants_names, program_duration,
               standard, percentage, academic_year, semester, total_marks,
               obtained_marks, other_info, file_path
        FROM rsvp WHERE event_id=? AND family_id=?
    """, (event_id, family_id))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"found": False})

    return jsonify({
        "found": True,
        "member_name": row[0] or "",
        "mobile_number": row[1] or "",
        "head_count": row[2] or "",
        "item_name": row[3] or "",
        "leader_name": row[4] or "",
        "leader_mobile": row[5] or "",
        "participants_count": row[6] or "",
        "participants_names": row[7] or "",
        "program_duration": row[8] or "",
        "standard": row[9] or "",
        "percentage": row[10] or "",
        "academic_year": row[11] or "",
        "semester": row[12] or "",
        "total_marks": row[13] or "",
        "obtained_marks": row[14] or "",
        "other_info": row[15] or "",
        "file_path": row[16] or ""
    })


@app.route("/rsvp/<int:event_id>", methods=["GET", "POST"])
def rsvp_public(event_id):
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, event_name, event_date, deadline_date, event_type FROM events WHERE id=?", (event_id,))
    ev = cursor.fetchone()
    if not ev:
        conn.close()
        return "<h3>ઇવેન્ટ મળી નથી!</h3>"
    
    is_expired = ev[3] and datetime.now().strftime("%Y-%m-%d") > ev[3]
    
    if request.method == "POST":
        if is_expired:
            conn.close()
            return "<h3>ક્ષમા કરશો, આ લિંકની ડેડલાઈન પૂરી થઈ ગઈ છે!</h3>"
        
        family_id = request.form.get("family_id")
        member_name = request.form.get("member_name", "")
        mobile_number = request.form.get("mobile_number", "")
        
        head_count_str = request.form.get("head_count", "1")
        try:
            head_count = int(head_count_str) if head_count_str else 1
        except (ValueError, TypeError):
            head_count = 1
        
        item_name = request.form.get("item_name", "")
        leader_name = request.form.get("leader_name", "")
        leader_mobile = request.form.get("leader_mobile", "")
        participants_count = request.form.get("participants_count", 0)
        participants_names = request.form.get("participants_names", "")
        program_duration = request.form.get("program_duration", "")
        
        standard = request.form.get("standard", "")
        percentage = request.form.get("percentage", "")
        academic_year = request.form.get("academic_year", "")
        semester = request.form.get("semester", "")
        total_marks = request.form.get("total_marks", "")
        obtained_marks = request.form.get("obtained_marks", "")
        
        other_info = request.form.get("other_info", "")
        performance_type = ev[4]
        
        file_url = ""
        if 'uploaded_file' in request.files:
            file = request.files['uploaded_file']
            if file and file.filename != '':
                filename = secure_filename(f"{event_id}_{family_id}_{datetime.now().strftime('%M%S')}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                file_url = f"/static/uploads/{filename}"
        
        cursor.execute("SELECT id, file_path FROM rsvp WHERE event_id = ? AND family_id = ?", (event_id, family_id))
        existing = cursor.fetchone()
        
        # If this is an edit and no new file was chosen, keep the previously
        # uploaded file instead of wiping it out with an empty value.
        if existing and not file_url:
            file_url = existing[1] or ""
        
        if existing:
            cursor.execute("""
                UPDATE rsvp 
                SET member_name=?, mobile_number=?, head_count=?,
                    item_name=?, performance_type=?, file_path=?,
                    leader_name=?, leader_mobile=?, participants_count=?, participants_names=?,
                    program_duration=?, standard=?, percentage=?, academic_year=?,
                    semester=?, total_marks=?, obtained_marks=?, other_info=?,
                    submitted_at=?
                WHERE id=?
            """, (member_name, mobile_number, head_count,
                  item_name, performance_type, file_url,
                  leader_name, leader_mobile, participants_count, participants_names,
                  program_duration, standard, percentage, academic_year,
                  semester, total_marks, obtained_marks, other_info,
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S"), existing[0]))
            conn.commit()
            conn.close()
            return """
            <div style='text-align:center; margin-top:60px; padding:30px; max-width:480px; margin-left:auto; margin-right:auto; background:white; border-radius:16px; box-shadow:0 8px 30px rgba(0,0,0,0.08);'>
                <div style='font-size:64px;'>✅</div>
                <h2 style='color:#059669; margin:15px 0 8px; font-size:22px;'>RSVP અપડેટ થઈ ગયું!</h2>
                <p style='font-size:16px; color:#1e293b;'>તમારી વિગત સફળતાપૂર્વક અપડેટ થઈ છે.</p>
                <p style='font-size:15px; color:#64748b; margin-top:8px;'>ધન્યવાદ! 🙏</p>
            </div>
            """
        
        try:
            cursor.execute("""
                INSERT INTO rsvp (
                    event_id, family_id, member_name, mobile_number, head_count,
                    standard, percentage, item_name, performance_type, file_path,
                    leader_name, leader_mobile, participants_count, participants_names,
                    program_duration, academic_year, semester, total_marks,
                    obtained_marks, other_info, submitted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (event_id, family_id, member_name, mobile_number, head_count,
                  standard, percentage, item_name, performance_type, file_url,
                  leader_name, leader_mobile, participants_count, participants_names,
                  program_duration, academic_year, semester, total_marks,
                  obtained_marks, other_info,
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
        except Exception as e:
            conn.close()
            return f"""
            <div style='text-align:center; margin-top:60px; padding:30px; max-width:480px; margin-left:auto; margin-right:auto; background:white; border-radius:16px; box-shadow:0 8px 30px rgba(0,0,0,0.08);'>
                <div style='font-size:64px;'>❌</div>
                <h2 style='color:#dc2626; font-size:22px; margin:15px 0 8px;'>સબમિશન ભૂલ!</h2>
                <p style='font-size:14px; color:#64748b;'>{str(e)}</p>
            </div>
            """
        
        conn.close()
        return """
        <div style='text-align:center; margin-top:60px; padding:30px; max-width:480px; margin-left:auto; margin-right:auto; background:white; border-radius:16px; box-shadow:0 8px 30px rgba(0,0,0,0.08);'>
            <div style='font-size:64px;'>🎉</div>
            <h2 style='color:#059669; margin:15px 0 8px; font-size:22px;'>RSVP સફળતાપૂર્વક સબમિટ થઈ ગયું!</h2>
            <p style='font-size:16px; color:#1e293b;'>તમારી વિગત સબમિટ થઈ ગઈ છે.</p>
            <p style='font-size:15px; color:#64748b; margin-top:8px;'>ધન્યવાદ! 🙏</p>
        </div>
        """
    
    cursor.execute("SELECT id, firm_name FROM families ORDER BY firm_name ASC")
    all_families = cursor.fetchall()
    conn.close()
    
    event = (ev[0], ev[1], format_date_to_indian(ev[2]), format_date_to_indian(ev[3]), ev[4])
    
    if ev[4] == 'culture':
        return render_template("rsvp_culture.html", event=event, families=all_families, is_expired=is_expired)
    elif ev[4] == 'saraswati':
        return render_template("rsvp_saraswati.html", event=event, families=all_families, is_expired=is_expired)
    else:
        return render_template("rsvp_jamvanu.html", event=event, families=all_families, is_expired=is_expired)

# ============================================================
# COLLECTION EXPORTS
# ============================================================
@app.route("/collection/export/pdf")
def export_collection_pdf():
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, firm_name, family_name, uif FROM families ORDER BY id DESC")
    families_data = cursor.fetchall()
    months_list = ['jan', 'feb', 'mar', 'apr', 'may', 'june', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
    active_year = get_current_collection_year()
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
    story = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=15, alignment=1, spaceAfter=5, textColor=colors.HexColor("#1e3a8a"))
    sub_style = ParagraphStyle('SubTitle', parent=styles['Normal'], fontSize=12, alignment=1, spaceAfter=15, textColor=colors.HexColor("#1e3a8a"))
    story.append(Paragraph(f"<b>{guj_mix('શ્રી કચ્છ કડવા પાટીદાર સત્સંગ સમાજ પ્રેરિત')}</b>", title_style))
    story.append(Paragraph(f"<b>{guj_mix('શ્રી કચ્છ કડવા પાટીદાર સંત્સંગ યુવક મંડળ, નડિયાદ')}</b>", sub_style))
    story.append(Paragraph(guj_mix(f"વર્ષ: {active_year}"), sub_style))

    cell_style = ParagraphStyle('Cell', parent=styles['Normal'], fontSize=8, alignment=1, leading=10)
    header_style = ParagraphStyle('Header', parent=styles['Normal'], fontSize=8, alignment=1, textColor=colors.white, leading=10)

    header_row = ["ક્રમ", "ફાર્મ / પરિવારનું નામ", "UIF", "JAN", "FEB", "MAR", "APR", "MAY", "JUNE", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    data = [[Paragraph(guj_mix(h), header_style) for h in header_row]]
    for idx, row in enumerate(families_data, start=1):
        f_id = row[0]
        cursor.execute("SELECT target_month, amount FROM payments WHERE family_id=? AND year=?", (f_id, active_year))
        pmt_records = dict(cursor.fetchall())
        f_row = [str(idx), Paragraph(guj_mix(f"{row[1]} ({row[2]})"), cell_style), Paragraph(guj_mix(f"₹{int(row[3])}"), cell_style)]
        for m in months_list:
            amt = pmt_records.get(m, 0)
            f_row.append(str(int(amt)) if amt > 0 else "0")
        data.append(f_row)
    
    conn.close()
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1e3a8a")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('FONTNAME', (2,1), (-1,-1), 'Helvetica'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")])
    ]))
    story.append(t)
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="society_monthly_collection.pdf", mimetype="application/pdf")

@app.route("/collection/export/excel")
def export_collection_excel():
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, firm_name, family_name, uif FROM families ORDER BY id DESC")
    families_data = cursor.fetchall()
    months_list = ['jan', 'feb', 'mar', 'apr', 'may', 'june', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
    active_year = get_current_collection_year()
    
    output = io.StringIO()
    output.write(f"Year: {active_year}\n")
    output.write("Sr.No,Firm/Family Name,UIF,JAN,FEB,MAR,APR,MAY,JUNE,JUL,AUG,SEP,OCT,NOV,DEC\n")
    for idx, row in enumerate(families_data, start=1):
        f_id = row[0]
        cursor.execute("SELECT target_month, amount FROM payments WHERE family_id=? AND year=?", (f_id, active_year))
        pmt_records = dict(cursor.fetchall())
        line = f'"{idx}","{row[1]} ({row[2]})","{int(row[3])}"'
        for m in months_list:
            line += f',"{int(pmt_records.get(m, 0))}"'
        output.write(line + "\n")
    
    conn.close()
    buf = io.BytesIO()
    buf.write(output.getvalue().encode('utf-8-sig'))
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="society_monthly_collection.csv", mimetype="text/csv")

# ============================================================
# YUVAK MANDAL - PUBLIC JOIN
# ============================================================
# ============================================================
# YUVAK MANDAL - PUBLIC JOIN
# ============================================================
@app.route("/yuvak/join", methods=["GET", "POST"])
def yuvak_join_public():
    if request.method == "POST":
        name = request.form.get("name")
        bdate = format_date_to_db(request.form.get("birth_date"))
        mobile = request.form.get("mobile")
        address = request.form.get("address")
        education = request.form.get("education")
        hobby = request.form.get("hobby")
        fee = float(request.form.get("entry_fee", 0)) if request.form.get("entry_fee") else 0.0
        is_exec = 1 if request.form.get("is_executive") else 0
        
        photo_url = ""
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename != '':
                filename = secure_filename(f"yuvak_{mobile}_{datetime.now().strftime('%M%S')}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                photo_url = f"/static/uploads/{filename}"
        
        conn = sqlite3.connect("samaj.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO yuvak_mandal (name, birth_date, mobile, address, education, hobby, entry_fee, photo_path, is_executive)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, bdate, mobile, address, education, hobby, fee, photo_url, is_exec))
        conn.commit()
        conn.close()
        return """
        <div style='text-align:center; margin-top:50px; padding:20px;'>
            <h2>✅ યુવક મંડળમાં રજીસ્ટ્રેશન સફળતાપૂર્વક થઈ ગયું છે.</h2>
            <p style='font-size:18px;'>ધન્યવાદ! 🙏</p>
        </div>
        """
    
    return render_template("yuvak_join.html")


# ============================================================
# YUVAK MANDAL - ADMIN
# ============================================================
@app.route("/yuvak")
def yuvak():
    if not session.get("logged_in"):
        return redirect("/login")
    if session.get("role") != "treasurer":
        return "<h3>તમને આ મેનુ એક્સેસ કરવાની પરવાનગી નથી!</h3>", 403
    
    search = request.args.get("search", "")
    filter_type = request.args.get("filter", "")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    # સ્ક્રીન પર દેખાતી યાદી માટેની ક્વેરી (ફિલ્ટરવાળી)
    query = """
        SELECT id, name, birth_date, mobile, address, education, hobby, entry_fee, photo_path, is_executive 
        FROM yuvak_mandal 
    """
    params = []
    
    if search:
        query += " WHERE name LIKE ? OR mobile LIKE ?"
        params.extend([f"%{search}%", f"%{search}%"])
    elif filter_type == 'karobari':
        query += " WHERE is_executive = 1"
        
    query += " ORDER BY id ASC"
    
    cursor.execute(query, params)
    raw = cursor.fetchall()
    
    # મહત્વનું: ઉપરના સ્ટેટ્સ કાર્ડ્સ માટે ક્યારેય ન બદલાય તેવો કુલ ડેટા (All Records)
    cursor.execute("SELECT entry_fee, birth_date, is_executive FROM yuvak_mandal")
    all_yuvaks_data = cursor.fetchall()
    conn.close()
    
    # કુલ આંકડાઓની સાચી ગણતરી
    total_yuvak_count = len(all_yuvaks_data)
    total_karobari_count = sum(1 for y in all_yuvaks_data if y[2] == 1)
    total_fee_sum = sum(y[0] for y in all_yuvaks_data if y[0])
    
    total_age_sum = 0
    age_count = 0
    for y in all_yuvaks_data:
        if y[1]:
            a = calculate_age(y[1])
            if a > 0:
                total_age_sum += a
                age_count += 1
    avg_age = round(total_age_sum / age_count, 1) if age_count > 0 else 0
    
    active_yuvaks = []
    for y in raw:
        age = calculate_age(y[2])  # birth_date
        active_yuvaks.append({
            'id': y[0],
            'name': y[1],
            'bdate': format_date_to_indian(y[2]),
            'age': age,
            'mobile': y[3],
            'address': y[4],
            'education': y[5],
            'hobby': y[6],
            'fee': y[7],
            'photo': y[8],
            'exec': "હા" if y[9] == 1 else "ના"
        })
    
    return render_template("yuvak.html", 
                          yuvaks=active_yuvaks, 
                          search=search,
                          total_yuvak_count=total_yuvak_count,
                          total_karobari_count=total_karobari_count,
                          total_fee_sum=total_fee_sum,
                          avg_age=avg_age)


@app.route("/yuvak/add", methods=["GET", "POST"])
def add_yuvak():
    if not session.get("logged_in"):
        return redirect("/login")
    
    if request.method == "POST":
        is_exec = 1 if request.form.get("is_executive") else 0
        photo_url = ""
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename != '':
                filename = secure_filename(f"yuvak_{request.form['mobile']}_{datetime.now().strftime('%M%S')}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                photo_url = f"/static/uploads/{filename}"
        
        conn = sqlite3.connect("samaj.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO yuvak_mandal (name, birth_date, mobile, address, education, hobby, entry_fee, photo_path, is_executive) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (request.form["name"], 
              format_date_to_db(request.form["birth_date"]), 
              request.form["mobile"], 
              request.form.get("address", ""), 
              request.form.get("education", ""), 
              request.form.get("hobby", ""), 
              float(request.form.get("entry_fee", 0) or 0), 
              photo_url, 
              is_exec))
        conn.commit()
        conn.close()
        return redirect("/yuvak")
    
    return render_template("yuvak_add.html", yuvak=None)


@app.route("/yuvak/edit/<int:y_id>", methods=["GET", "POST"])
def edit_yuvak(y_id):
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    if request.method == "POST":
        is_exec = 1 if request.form.get("is_executive") else 0
        photo_query = ""
        photo_args = []
        if 'photo' in request.files:
            file = request.files['photo']
            if file and file.filename != '':
                filename = secure_filename(f"yuvak_{request.form['mobile']}_{datetime.now().strftime('%M%S')}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                photo_query = ", photo_path=?"
                photo_args = [f"/static/uploads/{filename}"]
        
        args = [request.form["name"], 
                format_date_to_db(request.form["birth_date"]), 
                request.form["mobile"], 
                request.form.get("address", ""), 
                request.form.get("education", ""), 
                request.form.get("hobby", ""), 
                float(request.form.get("entry_fee", 0) or 0), 
                is_exec]
        if photo_query:
            args.extend(photo_args)
        args.append(y_id)
        
        cursor.execute(f"""
            UPDATE yuvak_mandal 
            SET name=?, birth_date=?, mobile=?, address=?, education=?, hobby=?, entry_fee=?, is_executive=? {photo_query}
            WHERE id=?
        """, args)
        conn.commit()
        conn.close()
        return redirect("/yuvak")
    
    cursor.execute("""
        SELECT id, name, birth_date, mobile, address, education, hobby, entry_fee, is_executive, photo_path 
        FROM yuvak_mandal 
        WHERE id=?
    """, (y_id,))
    y = cursor.fetchone()
    conn.close()
    
    yuvak = (y[0], y[1], format_date_to_indian(y[2]), y[3], y[4], y[5], y[6], y[7], y[8], y[9])
    return render_template("yuvak_add.html", yuvak=yuvak)


@app.route("/yuvak/delete/<int:y_id>")
def delete_yuvak(y_id):
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM yuvak_mandal WHERE id=?", (y_id,))
    conn.commit()
    conn.close()
    return redirect("/yuvak")


# ============================================================
# YUVAK EXPORTS - PDF (ReportLab)
# ============================================================
@app.route("/yuvak/export/pdf")
def export_yuvak_pdf():
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, mobile, birth_date, address, education, hobby, entry_fee, is_executive 
        FROM yuvak_mandal 
        ORDER BY id ASC
    """)
    raw = cursor.fetchall()
    conn.close()
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), 
                            rightMargin=20, leftMargin=20, 
                            topMargin=30, bottomMargin=30)
    story = []
    styles = getSampleStyleSheet()
    
    # ===== USE REGISTERED GUJARATI FONT FOR MIXED TEXT =====
    FONT_NAME = GUJARATI_FONT
    
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], 
                                  fontSize=16, alignment=1, spaceAfter=4, 
                                  textColor=colors.HexColor("#15803d"),
                                  fontName='Helvetica')
    sub_style = ParagraphStyle('SubTitle', parent=styles['Normal'], 
                               fontSize=12, alignment=1, spaceAfter=4, 
                               textColor=colors.HexColor("#15803d"),
                               fontName='Helvetica')
    date_style = ParagraphStyle('Date', parent=styles['Normal'], 
                                fontSize=10, alignment=1, spaceAfter=16, 
                                textColor=colors.HexColor("#64748b"),
                                fontName='Helvetica')
    cell_style = ParagraphStyle('Cell', parent=styles['Normal'], 
                                fontSize=8, leading=10)
    
    story.append(Paragraph("<b>Shri Kutch Kadva Patidar Satsang Samaj Prerit</b>", title_style))
    story.append(Paragraph("<b>Shri Kutch Kadva Patidar Santsang Yuvak Mandal, Nadiad</b>", sub_style))
    story.append(Paragraph(f"Date: {datetime.now().strftime('%d-%m-%Y')}  |  Total Members: {len(raw)}", date_style))
    
    header_cell_style = ParagraphStyle('HeaderCell', parent=styles['Normal'], fontSize=9, alignment=1, textColor=colors.white, leading=11)
    data = [[Paragraph(f"<b>{guj_mix('ક્રમ')}</b>", header_cell_style), "ID", "Name", "Mobile", "Birth Date", "Age", "Address", "Education", "Hobby", "Entry Fee", "Executive"]]
    
    for idx, r in enumerate(raw, start=1):
        age = calculate_age(r[3]) if r[3] else "-"
        birth = format_date_to_indian(r[3]) if r[3] else "-"
        data.append([
            str(idx), str(r[0]),
            Paragraph(guj_mix(r[1] or "-"), cell_style),
            str(r[2] or "-"), birth,
            str(age),
            Paragraph(guj_mix(r[4] or "-"), cell_style),
            Paragraph(guj_mix(r[5] or "-"), cell_style),
            Paragraph(guj_mix(r[6] or "-"), cell_style),
            Paragraph(guj_mix(f"₹{int(r[7])}") if r[7] else guj_mix("₹0"), cell_style),
            "Yes" if r[8]==1 else "No"
        ])
    
    col_widths = [32, 28, 82, 62, 68, 28, 88, 62, 62, 58, 48]
    t = Table(data, repeatRows=1, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#15803d")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 9),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('VALIGN', (0,0), (-1,0), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,0), 4),
        ('BOTTOMPADDING', (0,0), (-1,0), 4),
        ('FONTNAME', (0,1), (1,-1), 'Helvetica'),
        ('FONTNAME', (3,1), (5,-1), 'Helvetica'),
        ('FONTNAME', (10,1), (10,-1), 'Helvetica'),
        ('FONTSIZE', (0,1), (-1,-1), 8),
        ('ALIGN', (0,1), (-1,-1), 'CENTER'),
        ('VALIGN', (0,1), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,1), (-1,-1), 3),
        ('BOTTOMPADDING', (0,1), (-1,-1), 3),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#94a3b8")),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
        ('ALIGN', (2,1), (2,-1), 'LEFT'),
        ('ALIGN', (6,1), (6,-1), 'LEFT'),
        ('ALIGN', (7,1), (7,-1), 'LEFT'),
        ('ALIGN', (8,1), (8,-1), 'LEFT'),
    ]))
    story.append(t)
    
    footer_style = ParagraphStyle('Footer', parent=styles['Normal'], 
                                  fontSize=9, alignment=1, spaceBefore=10,
                                  textColor=colors.HexColor("#64748b"),
                                  fontName='Helvetica')
    story.append(Paragraph(f"Total Members: {len(raw)}", footer_style))
    
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, 
                     download_name=f"yuvak_mandal_register_{datetime.now().strftime('%d-%m-%Y')}.pdf", 
                     mimetype="application/pdf")


# ============================================================
# YUVAK EXPORTS - EXCEL (Gujarati)
# ============================================================
@app.route("/yuvak/export/excel")
def export_yuvak_excel():
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, mobile, birth_date, address, education, hobby, entry_fee, is_executive 
        FROM yuvak_mandal 
        ORDER BY id ASC
    """)
    raw = cursor.fetchall()
    conn.close()
    
    output = io.StringIO()
    output.write('\ufeff')
    output.write("ક્રમ,ID,નામ,મોબાઈલ,જન્મ તારીખ,ઉંમર,સરનામું,અભ્યાસ,શોખ,પ્રવેશ ફી,કારોબારી\n")
    
    for idx, r in enumerate(raw, start=1):
        age = calculate_age(r[3]) if r[3] else "-"
        birth = format_date_to_indian(r[3]) if r[3] else "-"
        output.write(f'"{idx}","{r[0]}","{r[1] or "-"}","{r[2] or "-"}","{birth}","{age}","{r[4] or "-"}","{r[5] or "-"}","{r[6] or "-"}","{int(r[7]) if r[7] else 0}","{"હા" if r[8]==1 else "ના"}"\n')
    
    output.seek(0)
    buf = io.BytesIO()
    buf.write(output.getvalue().encode('utf-8-sig'))
    buf.seek(0)
    
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"yuvak_register_{datetime.now().strftime('%d-%m-%Y')}.csv",
        mimetype="text/csv"
    )
# ============================================================
# YUVAK LEDGER
# ============================================================
@app.route("/yuvak/ledger", methods=["GET", "POST"])
def yuvak_ledger():
    if not session.get("logged_in"):
        return redirect("/login")
    
    # જો યૂઝરનો રોલ ખજાનચી (treasurer) ન હોય, તો તેને લેજર ખોલવા ન દેવો અને હોમ પેજ પર મોકલી દેવો
    if session.get("role") != "treasurer":
        return redirect("/")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    if request.method == "POST":
        if not is_treasurer():
            conn.close()
            return redirect("/yuvak/ledger")
        entry_date = format_date_to_db(request.form["entry_date"])
        entry_type = request.form["entry_type"]
        donor_name = request.form.get("donor_name", "")
        description = request.form["description"]
        amount = float(request.form["amount"])
        event_tag = request.form.get("event_tag", "").strip() or "સામાન્ય"
        
        cursor.execute("""
            INSERT INTO yuvak_ledger (entry_date, entry_type, donor_name, description, amount, event_tag) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, (entry_date, entry_type, donor_name, description, amount, event_tag))
        conn.commit()
    
    # ===== FILTERS: date range + event =====
    filter_date_from = request.args.get("date_from", "")
    filter_date_to = request.args.get("date_to", "")
    filter_event = request.args.get("event_tag", "")
    
    query = "SELECT id, entry_date, entry_type, donor_name, description, amount, event_tag FROM yuvak_ledger WHERE 1=1"
    params = []
    if filter_date_from:
        query += " AND entry_date >= ?"
        params.append(filter_date_from)
    if filter_date_to:
        query += " AND entry_date <= ?"
        params.append(filter_date_to)
    if filter_event:
        query += " AND event_tag = ?"
        params.append(filter_event)
    query += " ORDER BY entry_date DESC, id DESC"
    
    cursor.execute(query, params)
    raw_ledger = cursor.fetchall()
    
    # List of all distinct event tags used so far (for the filter dropdown)
    cursor.execute("SELECT DISTINCT event_tag FROM yuvak_ledger WHERE event_tag IS NOT NULL AND event_tag != '' ORDER BY event_tag ASC")
    all_event_tags = [r[0] for r in cursor.fetchall()]
    
    ledger_entries = []
    total_income = 0.0
    total_expense = 0.0
    
    for row in raw_ledger:
        amt = row[5]
        if row[2] == 'income':
            total_income += amt
        else:
            total_expense += amt
        
        ledger_entries.append({
            'id': row[0],
            'date': format_date_to_indian(row[1]),
            'date_iso': row[1],
            'type': "આવક" if row[2] == 'income' else "જાવક",
            'type_raw': row[2],
            'donor_name': row[3] if row[3] else "-",
            'desc': row[4],
            'amount': amt,
            'event_tag': row[6] if row[6] else "સામાન્ય"
        })
    
    # ===== BALANCE CALCULATION - FIXED =====
    closing_balance = total_income - total_expense
    
    conn.close()
    
    return render_template("yuvak_ledger.html", 
                          ledger=ledger_entries, 
                          income=total_income, 
                          expense=total_expense, 
                          balance=closing_balance, 
                          edit_entry=None,
                          all_event_tags=all_event_tags,
                          filter_date_from=filter_date_from,
                          filter_date_to=filter_date_to,
                          filter_event=filter_event,
                          user_is_treasurer=is_treasurer())

@app.route("/yuvak/ledger/edit/<int:l_id>", methods=["GET", "POST"])
def edit_ledger_entry(l_id):
    if not session.get("logged_in"):
        return redirect("/login")
    if not is_treasurer():
        return redirect("/yuvak/ledger")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    if request.method == "POST":
        cursor.execute("""
            UPDATE yuvak_ledger 
            SET entry_date=?, entry_type=?, donor_name=?, description=?, amount=?, event_tag=? 
            WHERE id=?
        """, (format_date_to_db(request.form["entry_date"]), 
              request.form["entry_type"], 
              request.form.get("donor_name", ""), 
              request.form["description"], 
              float(request.form["amount"]), 
              request.form.get("event_tag", "").strip() or "સામાન્ય",
              l_id))
        conn.commit()
        conn.close()
        return redirect("/yuvak/ledger")
    
    cursor.execute("""
        SELECT id, entry_date, entry_type, donor_name, description, amount, event_tag 
        FROM yuvak_ledger 
        WHERE id=?
    """, (l_id,))
    sub_row = cursor.fetchone()
    
    cursor.execute("""
        SELECT id, entry_date, entry_type, donor_name, description, amount, event_tag 
        FROM yuvak_ledger 
        ORDER BY entry_date DESC, id DESC
    """)
    raw_ledger = cursor.fetchall()
    
    cursor.execute("SELECT DISTINCT event_tag FROM yuvak_ledger WHERE event_tag IS NOT NULL AND event_tag != '' ORDER BY event_tag ASC")
    all_event_tags = [r[0] for r in cursor.fetchall()]
    
    ledger_entries = []
    total_income = 0.0
    total_expense = 0.0
    
    for r in raw_ledger:
        amt = r[5]
        if r[2] == 'income':
            total_income += amt
        else:
            total_expense += amt
        ledger_entries.append({
            'id': r[0],
            'date': format_date_to_indian(r[1]),
            'date_iso': r[1],
            'type': "આવક" if r[2] == 'income' else "જાવક",
            'type_raw': r[2],
            'donor_name': r[3] if r[3] else "-",
            'desc': r[4],
            'amount': amt,
            'event_tag': r[6] if r[6] else "સામાન્ય"
        })
    
    closing_balance = total_income - total_expense
    conn.close()
    
    edit_entry = {
        'id': sub_row[0],
        'date': sub_row[1],  # already stored as YYYY-MM-DD; HTML date input needs ISO format
        'type': sub_row[2],
        'donor_name': sub_row[3] if sub_row[3] else "",
        'desc': sub_row[4],
        'amount': sub_row[5],
        'event_tag': sub_row[6] if sub_row[6] else "સામાન્ય"
    }
    
    return render_template("yuvak_ledger.html", 
                          ledger=ledger_entries, 
                          income=total_income, 
                          expense=total_expense, 
                          balance=closing_balance, 
                          edit_entry=edit_entry,
                          all_event_tags=all_event_tags,
                          filter_date_from="",
                          filter_date_to="",
                          filter_event="",
                          user_is_treasurer=is_treasurer())

@app.route("/yuvak/ledger/delete/<int:l_id>")
def delete_ledger_entry_route(l_id):
    if not session.get("logged_in"):
        return redirect("/login")
    if not is_treasurer():
        return redirect("/yuvak/ledger")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM yuvak_ledger WHERE id=?", (l_id,))
    conn.commit()
    conn.close()
    return redirect("/yuvak/ledger")

@app.route("/yuvak/ledger/export/pdf")
def export_ledger_pdf():
    if not session.get("logged_in"):
        return redirect("/login")
    
    filter_date_from = request.args.get("date_from", "")
    filter_date_to = request.args.get("date_to", "")
    filter_event = request.args.get("event_tag", "")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    query = "SELECT id, entry_date, entry_type, donor_name, description, amount FROM yuvak_ledger WHERE 1=1"
    params = []
    if filter_date_from:
        query += " AND entry_date >= ?"
        params.append(filter_date_from)
    if filter_date_to:
        query += " AND entry_date <= ?"
        params.append(filter_date_to)
    if filter_event:
        query += " AND event_tag = ?"
        params.append(filter_event)
    query += " ORDER BY id ASC"
    
    cursor.execute(query, params)
    raw = cursor.fetchall()
    conn.close()
    
    # ===== IF NO DATA =====
    if not raw:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
        story = []
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, alignment=1)
        story.append(Paragraph(f"<b>{guj_mix('યુવક લેજર')}</b>", title_style))
        story.append(Paragraph("<br/>", title_style))
        story.append(Paragraph(guj_mix('કોઈ ડેટા નથી'), title_style))
        doc.build(story)
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, 
                         download_name=f"yuvak_ledger_{datetime.now().strftime('%d-%m-%Y')}.pdf", 
                         mimetype="application/pdf")
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), 
                            rightMargin=20, leftMargin=20, 
                            topMargin=30, bottomMargin=30)
    story = []
    styles = getSampleStyleSheet()
    
    # ===== FONT SETUP =====
    FONT_NAME = GUJARATI_FONT
    
    # ===== SEPARATE INCOME AND EXPENSE =====
    income_entries = []
    expense_entries = []
    total_income = 0
    total_expense = 0
    
    for r in raw:
        entry = {
            'date': format_date_to_indian(r[1]),
            'donor': r[3] if r[3] else "-",
            'desc': r[4] if r[4] else "-",
            'amount': r[5]
        }
        if r[2] == 'income':
            income_entries.append(entry)
            total_income += r[5]
        else:
            expense_entries.append(entry)
            total_expense += r[5]
    
    # ===== TITLE =====
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], 
                                  fontSize=16, alignment=1, spaceAfter=4, 
                                  textColor=colors.HexColor("#1e3a8a"),
                                  fontName=FONT_NAME)
    sub_style = ParagraphStyle('SubTitle', parent=styles['Normal'], 
                               fontSize=12, alignment=1, spaceAfter=16, 
                               textColor=colors.HexColor("#1e3a8a"),
                               fontName=FONT_NAME)
    
    story.append(Paragraph(f"<b>{guj_mix('શ્રી કચ્છ કડવા પાટીદાર સત્સંગ સમાજ પ્રેરિત')}</b>", title_style))
    story.append(Paragraph(f"<b>{guj_mix('શ્રી કચ્છ કડવા પાટીદાર સંત્સંગ યુવક મંડળ, નડિયાદ')}</b>", sub_style))
    filter_bits = []
    if filter_event:
        filter_bits.append(filter_event)
    if filter_date_from:
        filter_bits.append(f"{filter_date_from} થી")
    if filter_date_to:
        filter_bits.append(f"{filter_date_to} સુધી")
    filter_note = " | ".join(filter_bits) if filter_bits else "બધા રેકોર્ડ"
    story.append(Paragraph(guj_mix(f"તારીખ: {datetime.now().strftime('%d-%m-%Y')}  |  યુવક લેજર  |  {filter_note}"), sub_style))
    story.append(Paragraph("<br/>", sub_style))
    
    # ===== TABLE DATA =====
    header_style = ParagraphStyle('Header', parent=styles['Normal'], 
                                  fontSize=11, alignment=1, 
                                  textColor=colors.white)
    cell_style = ParagraphStyle('Cell', parent=styles['Normal'], 
                                fontSize=9, leading=12)
    
    data = []
    data.append([
        Paragraph(f"<b>{guj_mix('ક્રમ')}</b>", header_style),
        Paragraph(f"<b>{guj_mix('આવક (Credit)')}</b>", header_style),
        Paragraph(f"<b>{guj_mix('ક્રમ')}</b>", header_style),
        Paragraph(f"<b>{guj_mix('જાવક (Debit)')}</b>", header_style)
    ])
    
    max_rows = max(len(income_entries), len(expense_entries), 1)
    for i in range(max_rows):
        inc_no = ""
        inc_text = ""
        exp_no = ""
        exp_text = ""
        
        if i < len(income_entries):
            d = income_entries[i]
            inc_no = str(i + 1)
            inc_text = f"""
            <b>{guj_mix(d['desc'])}</b><br/>
            <font size=8 color=#64748b>{guj_mix(d['donor'])} | {d['date']}</font><br/>
            <b><font color=#059669 size=12>{guj_mix('₹')}{int(d['amount'])}</font></b>
            """
        
        if i < len(expense_entries):
            e = expense_entries[i]
            exp_no = str(i + 1)
            exp_text = f"""
            <b>{guj_mix(e['desc'])}</b><br/>
            <font size=8 color=#64748b>{guj_mix(e['donor'])} | {e['date']}</font><br/>
            <b><font color=#dc2626 size=12>{guj_mix('₹')}{int(e['amount'])}</font></b>
            """
        
        data.append([
            Paragraph(inc_no, cell_style) if inc_no else Paragraph("", cell_style),
            Paragraph(inc_text, cell_style) if inc_text else Paragraph("<font color=#d1d5db>—</font>", cell_style),
            Paragraph(exp_no, cell_style) if exp_no else Paragraph("", cell_style),
            Paragraph(exp_text, cell_style) if exp_text else Paragraph("<font color=#d1d5db>—</font>", cell_style)
        ])
    
    # ===== TOTAL =====
    total_style = ParagraphStyle('Total', parent=styles['Normal'], 
                                 fontSize=11, alignment=2)
    data.append([
        "", Paragraph(f"<b>{guj_mix('કુલ આવક: ₹')}{int(total_income)}</b>", total_style),
        "", Paragraph(f"<b>{guj_mix('કુલ જાવક: ₹')}{int(total_expense)}</b>", total_style)
    ])
    
    # ===== CREATE TABLE =====
    col_widths = [30, doc.width/2 - 40, 30, doc.width/2 - 40]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0,0), (1,0), colors.HexColor("#059669")),
        ('BACKGROUND', (2,0), (3,0), colors.HexColor("#dc2626")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTSIZE', (0,0), (-1,0), 11),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('VALIGN', (0,0), (-1,0), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,0), 8),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        # Body
        ('FONTSIZE', (0,1), (-1,-1), 9),
        ('ALIGN', (0,1), (0,-1), 'CENTER'),
        ('ALIGN', (2,1), (2,-1), 'CENTER'),
        ('VALIGN', (0,1), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,1), (-1,-1), 6),
        ('BOTTOMPADDING', (0,1), (-1,-1), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('BACKGROUND', (0,1), (1,-2), colors.HexColor("#f0fdf4")),
        ('BACKGROUND', (2,1), (3,-2), colors.HexColor("#fef2f2")),
        # Footer
        ('BACKGROUND', (0,-1), (1,-1), colors.HexColor("#d1fae5")),
        ('BACKGROUND', (2,-1), (3,-1), colors.HexColor("#fecaca")),
        ('FONTSIZE', (0,-1), (-1,-1), 11),
        ('TOPPADDING', (0,-1), (-1,-1), 8),
        ('BOTTOMPADDING', (0,-1), (-1,-1), 8),
    ]))
    story.append(t)
    
    # ===== BALANCE =====
    balance = total_income - total_expense
    balance_color = "#059669" if balance >= 0 else "#dc2626"
    balance_text = guj_mix(f"બેલેન્સ: ₹{int(abs(balance))} ({'આવક વધારે' if balance >= 0 else 'જાવક વધારે'})")
    
    balance_style = ParagraphStyle('Balance', parent=styles['Normal'], 
                                   fontSize=13, alignment=1, spaceBefore=12,
                                   textColor=colors.HexColor(balance_color))
    story.append(Paragraph(f"<b>{balance_text}</b>", balance_style))
    
    # ===== FOOTER =====
    footer_style = ParagraphStyle('Footer', parent=styles['Normal'], 
                                  fontSize=9, alignment=1, spaceBefore=10,
                                  textColor=colors.HexColor("#64748b"))
    story.append(Paragraph(guj_mix(f"કુલ એન્ટ્રીઝ: {len(raw)}"), footer_style))
    
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, 
                     download_name=f"yuvak_ledger_{datetime.now().strftime('%d-%m-%Y')}.pdf", 
                     mimetype="application/pdf")

@app.route("/yuvak/ledger/export/excel")
def export_ledger_excel():
    if not session.get("logged_in"):
        return redirect("/login")
    
    filter_date_from = request.args.get("date_from", "")
    filter_date_to = request.args.get("date_to", "")
    filter_event = request.args.get("event_tag", "")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    query = "SELECT entry_date, entry_type, donor_name, description, amount FROM yuvak_ledger WHERE 1=1"
    params = []
    if filter_date_from:
        query += " AND entry_date >= ?"
        params.append(filter_date_from)
    if filter_date_to:
        query += " AND entry_date <= ?"
        params.append(filter_date_to)
    if filter_event:
        query += " AND event_tag = ?"
        params.append(filter_event)
    query += " ORDER BY id ASC"
    
    cursor.execute(query, params)
    raw = cursor.fetchall()
    conn.close()
    
    # ===== HTML TABLE FOR EXCEL =====
    html = """
    <html xmlns:o="urn:schemas-microsoft-com:office:office" 
          xmlns:x="urn:schemas-microsoft-com:office:excel" 
          xmlns="http://www.w3.org/TR/REC-html40">
    <head>
        <meta charset="UTF-8">
        <!--[if gte mso 9]>
        <xml>
            <x:ExcelWorkbook>
                <x:ExcelWorksheets>
                    <x:ExcelWorksheet>
                        <x:Name>યુવક લેજર</x:Name>
                        <x:WorksheetOptions>
                            <x:DisplayGridlines/>
                        </x:WorksheetOptions>
                    </x:ExcelWorksheet>
                </x:ExcelWorksheets>
            </x:ExcelWorkbook>
        </xml>
        <![endif]-->
        <style>
            body { font-family: 'Noto Sans Gujarati', 'Arial Unicode MS', sans-serif; padding: 20px; }
            .header { text-align: center; padding: 15px; background: #1e3a8a; color: white; border-radius: 10px; margin-bottom: 20px; }
            .header h1 { font-size: 20px; margin: 0; color: #ffd54f; }
            .header h2 { font-size: 14px; margin: 5px 0 0; opacity: 0.9; }
            .header .date { font-size: 12px; margin-top: 6px; opacity: 0.8; border-top: 1px solid rgba(255,255,255,0.2); padding-top: 6px; }
            
            .balance-sheet { width: 100%; border-collapse: collapse; margin-top: 10px; }
            .balance-sheet th { padding: 10px; text-align: center; font-size: 13px; }
            .balance-sheet td { padding: 8px 10px; border: 1px solid #d1d5db; vertical-align: middle; }
            
            .credit-header { background: #059669; color: white; }
            .debit-header { background: #dc2626; color: white; }
            
            .credit-row { background: #f0fdf4; }
            .debit-row { background: #fef2f2; }
            
            .credit-total { background: #d1fae5; font-weight: bold; }
            .debit-total { background: #fecaca; font-weight: bold; }
            
            .balance-row { background: #dbeafe; font-weight: bold; font-size: 14px; }
            
            .amount.credit-amount { color: #059669; text-align: right; font-weight: 600; }
            .amount.debit-amount { color: #dc2626; text-align: right; font-weight: 600; }
            
            .footer { margin-top: 15px; padding: 10px; background: #f1f5f9; border-radius: 8px; text-align: center; font-size: 13px; color: #64748b; }
            .empty-cell { color: #d1d5db; text-align: center; }
        </style>
    </head>
    <body>
        
        <!-- HEADER -->
        <div class="header">
            <h1>🚩 શ્રી કચ્છ કડવા પાટીદાર સત્સંગ સમાજ પ્રેરિત</h1>
            <h2>🏛️ શ્રી કચ્છ કડવા પાટીદાર સંત્સંગ યુવક મંડળ, નડિયાદ</h2>
            <div class="date">📅 તારીખ: """ + datetime.now().strftime('%d-%m-%Y') + """ | 📊 યુવક લેજર | """ + (
                " | ".join(filter(None, [filter_event, f"{filter_date_from} થી" if filter_date_from else "", f"{filter_date_to} સુધી" if filter_date_to else ""])) or "બધા રેકોર્ડ"
            ) + """</div>
        </div>
        
        <!-- BALANCE SHEET -->
        <table class="balance-sheet">
            <tr>
                <th style="width:5%; background:#1e293b; color:white; font-size:12px;">ક્રમ</th>
                <th class="credit-header" style="width:40%;">📈 આવક (Credit)</th>
                <th style="width:10%; background:#1e293b; color:white; font-size:14px;">📊</th>
                <th style="width:5%; background:#1e293b; color:white; font-size:12px;">ક્રમ</th>
                <th class="debit-header" style="width:40%;">📉 જાવક (Debit)</th>
            </tr>
    """
    
    # ===== SEPARATE INCOME AND EXPENSE =====
    income_data = []
    expense_data = []
    
    for r in raw:
        date = format_date_to_indian(r[0])
        donor = r[2] or "-"
        desc = r[3] or "-"
        amount = r[4]
        
        if r[1] == 'income':
            income_data.append([date, donor, desc, amount])
        else:
            expense_data.append([date, donor, desc, amount])
    
    # ===== CREATE ROWS =====
    max_rows = max(len(income_data), len(expense_data), 1)
    total_income = sum([d[3] for d in income_data])
    total_expense = sum([d[3] for d in expense_data])
    
    for i in range(max_rows):
        html += "<tr>"
        
        # Sr.No for income
        if i < len(income_data):
            html += f'<td style="text-align:center; background:#f0fdf4; font-weight:600;">{i+1}</td>'
        else:
            html += '<td style="text-align:center; background:#f0fdf4;"></td>'
        
        # Income column (LEFT)
        if i < len(income_data):
            d = income_data[i]
            html += f"""
                <td class="credit-row">
                    <div><b>{d[2]}</b></div>
                    <div style="font-size:12px; color:#64748b;">{d[1]} | {d[0]}</div>
                    <div class="amount credit-amount">₹{int(d[3])}</div>
                </td>
            """
        else:
            html += '<td class="credit-row" style="color:#d1d5db; text-align:center;">—</td>'
        
        # Divider
        html += '<td style="text-align:center; background:#f8fafc; font-size:18px; color:#94a3b8;">|</td>'
        
        # Sr.No for expense
        if i < len(expense_data):
            html += f'<td style="text-align:center; background:#fef2f2; font-weight:600;">{i+1}</td>'
        else:
            html += '<td style="text-align:center; background:#fef2f2;"></td>'
        
        # Expense column (RIGHT)
        if i < len(expense_data):
            c = expense_data[i]
            html += f"""
                <td class="debit-row">
                    <div><b>{c[2]}</b></div>
                    <div style="font-size:12px; color:#64748b;">{c[1]} | {c[0]}</div>
                    <div class="amount debit-amount">₹{int(c[3])}</div>
                </td>
            """
        else:
            html += '<td class="debit-row" style="color:#d1d5db; text-align:center;">—</td>'
        
        html += "</tr>"
    
    # ===== TOTAL ROW =====
    html += f"""
        <tr>
            <td style="background:#f8fafc;"></td>
            <td class="credit-total" style="font-size:14px; text-align:right; padding-right:15px;">
                કુલ આવક: ₹{int(total_income)}
            </td>
            <td style="background:#f8fafc;"></td>
            <td style="background:#f8fafc;"></td>
            <td class="debit-total" style="font-size:14px; text-align:right; padding-right:15px;">
                કુલ જાવક: ₹{int(total_expense)}
            </td>
        </tr>
    """
    
    # ===== BALANCE =====
    balance = total_income - total_expense
    balance_text = f"બેલેન્સ: ₹{int(abs(balance))}"
    balance_status = f"({'આવક વધારે ✅' if balance >= 0 else 'જાવક વધારે ❌'})"
    balance_color = "#059669" if balance >= 0 else "#dc2626"
    
    html += f"""
        <tr>
            <td colspan="5" class="balance-row" style="text-align:center; font-size:16px; color:{balance_color};">
                {balance_text} {balance_status}
            </td>
        </tr>
    </table>
    """
    
    # ===== FOOTER =====
    html += f"""
        <div class="footer">
            📋 કુલ એન્ટ્રીઝ: {len(raw)}  |  🕐 રજીસ્ટર તારીખ: {datetime.now().strftime('%d-%m-%Y %H:%M')}
        </div>
        
    </body>
    </html>
    """
    
    output = io.BytesIO()
    output.write(html.encode('utf-8-sig'))
    output.seek(0)
    
    return send_file(
        output,
        as_attachment=True,
        download_name=f"yuvak_ledger_{datetime.now().strftime('%d-%m-%Y')}.xls",
        mimetype="application/vnd.ms-excel"
    )
# ============================================================
# BIRTHDAYS
# ============================================================
@app.route("/birthdays")
def birthdays():
    if not session.get("logged_in"):
        return redirect("/login")
    if session.get("role") != "treasurer":
        return "<h3>તમને જન્મદિનનું મેનુ જોવાની પરવાનગી નથી!</h3>", 403
    
    today = datetime.now()
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    # ===== FETCH ALL MEMBERS WITH BIRTH DATE =====
    cursor.execute("""
        SELECT 
            families.family_name, 
            family_members.name, 
            family_members.birth_date 
        FROM family_members 
        JOIN families ON families.id = family_members.family_id
        WHERE family_members.birth_date IS NOT NULL 
        AND family_members.birth_date != ''
        ORDER BY family_members.birth_date ASC
    """)
    data = cursor.fetchall()
    conn.close()
    
    today_list = []
    upcoming_list = []
    
    for row in data:
        if not row[2]:
            continue
        
        bdate_str = row[2].strip()
        bdate_obj = None
        
        # ===== TRY BOTH DATE FORMATS =====
        for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
            try:
                bdate_obj = datetime.strptime(bdate_str, fmt)
                break
            except:
                continue
        
        if bdate_obj:
            # ===== CHECK IF TODAY =====
            if bdate_obj.month == today.month and bdate_obj.day == today.day:
                today_list.append({
                    'family_name': row[0],
                    'name': row[1],
                    'birth_date': bdate_obj.strftime("%d-%m-%Y")
                })
            else:
                # ===== UPCOMING BIRTHDAYS =====
                upcoming_list.append({
                    'family_name': row[0],
                    'name': row[1],
                    'birth_date': bdate_obj.strftime("%d-%m-%Y")
                })
    
    # ===== SORT UPCOMING BY DATE =====
    upcoming_list.sort(key=lambda x: datetime.strptime(x['birth_date'], "%d-%m-%Y"))
    
    return render_template("birthdays.html", 
                          today_birthdays=today_list, 
                          upcoming_birthdays=upcoming_list)

@app.template_filter('format_date_to_indian')
def format_date_to_indian_filter(date_str):
    if not date_str:
        return ""
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue
    return date_str

@app.template_filter('calculate_age')
def calculate_age_filter(birth_date_str):
    return calculate_age(birth_date_str)

# ============================================================
# DIRECTORY
# ============================================================

@app.route("/directory")
def directory_view():
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    # અહીં subquery માંથી દરેક પરિવારના સૌથી પહેલા સભ્ય (MIN id) ને જ મુખ્ય સભ્ય તરીકે લીધેલ છે
    cursor.execute("""
        SELECT f.id, f.firm_name, f.family_name, f.address, 
               m.name as head_name, m.mobile, m.birth_date, m.business_study,
               (SELECT COUNT(*) FROM family_members WHERE family_id = f.id) as total_members
        FROM families f
        LEFT JOIN family_members m ON m.id = (
            SELECT id FROM family_members WHERE family_id = f.id ORDER BY id ASC LIMIT 1
        )
        GROUP BY f.id
        ORDER BY f.id ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    families = []
    for r in rows:
        families.append({
            "id": r[0],
            "firm_name": r[1] if r[1] else r[2],
            "family_name": r[2],
            "address": r[3],
            "head_name": r[4],
            "mobile": r[5],
            "birth_date": r[6],
            "business_study": r[7],
            "total_members": r[8]
        })
    
    return render_template("directory.html", families=families)

# ============================================================
# DIRECTORY_SABHYO_VIEW
# ============================================================

@app.route("/directory/family/<int:family_id>/members")
def directory_family_members(family_id):
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    
    # પરિવારનું નામ મેળવવા માટે
    cursor.execute("SELECT firm_name, family_name, address FROM families WHERE id = ?", (family_id,))
    family_info = cursor.fetchone()
    
    # તે પરિવારના બધા સભ્યો મેળવવા માટે
    cursor.execute("""
        SELECT name, mobile, birth_date, business_study, house_number, blood_group 
        FROM family_members 
        WHERE family_id = ?
        ORDER BY house_number ASC
    """, (family_id,))
    members = cursor.fetchall()
    conn.close()
    
    return render_template("directory_members.html", family_info=family_info, members=members)

# ============================================================
# ડિરેક્ટરી PDF એક્સપોર્ટ
# ============================================================
import io
from flask import send_file
import openpyxl
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# 1. ડિરેક્ટરી PDF એક્સપોર્ટ
@app.route("/directory/export/pdf")
def directory_export_pdf():
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT f.firm_name, f.family_name, f.address, m.name, m.mobile
        FROM families f
        LEFT JOIN family_members m ON m.id = (
            SELECT id FROM family_members WHERE family_id = f.id ORDER BY id ASC LIMIT 1
        )
        ORDER BY f.id ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, "Shri Kutch Kadva Patidar Satsang Samaj - Directory")
    
    y = height - 90
    p.setFont("Helvetica-Bold", 10)
    p.drawString(50, y, "Firm / Family Name")
    p.drawString(200, y, "Head Member")
    p.drawString(350, y, "Mobile")
    p.drawString(450, y, "Address")
    y -= 20
    
    p.setFont("Helvetica", 9)
    for r in rows:
        if y < 50:
            p.showPage()
            y = height - 50
        firm = str(r[0] if r[0] else r[1])[:25]
        head = str(r[3] if r[3] else '-')[:20]
        mob = str(r[4] if r[4] else '-')[:15]
        addr = str(r[2] if r[2] else '-')[:20]
        
        p.drawString(50, y, firm)
        p.drawString(200, y, head)
        p.drawString(350, y, mob)
        p.drawString(450, y, addr)
        y -= 18
        
    p.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="directory.pdf", mimetype="application/pdf")

# 2. ડિરેક્ટરી Excel એક્સપોર્ટ
@app.route("/directory/export/excel")
def directory_export_excel():
    if not session.get("logged_in"):
        return redirect("/login")
        
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT f.firm_name, f.family_name, f.address, m.name, m.mobile
        FROM families f
        LEFT JOIN family_members m ON m.id = (
            SELECT id FROM family_members WHERE family_id = f.id ORDER BY id ASC LIMIT 1
        )
        ORDER BY f.id ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Directory"
    
    ws.append(["ફાર્મ/પરિવાર નામ", "મુખ્ય સભ્ય", "મોબાઈલ", "એડ્રેસ"])
    for r in rows:
        ws.append([r[0] if r[0] else r[1], r[3] if r[3] else '-', r[4] if r[4] else '-', r[2] if r[2] else '-'])
        
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="directory.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# 3. બધા ફાર્મ લેબલ પ્રિન્ટ પેજ માટેનો રૂટ
@app.route("/directory/labels")
def directory_labels():
    if not session.get("logged_in"):
        return redirect("/login")
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT f.id, f.firm_name, f.family_name, f.address, 
               m.name as head_name, m.mobile
        FROM families f
        LEFT JOIN family_members m ON m.id = (
            SELECT id FROM family_members WHERE family_id = f.id ORDER BY id ASC LIMIT 1
        )
        ORDER BY f.id ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    families = []
    for r in rows:
        families.append({
            "id": r[0],
            "firm_name": r[1] if r[1] else r[2],
            "family_name": r[2],
            "address": r[3],
            "head_name": r[4],
            "mobile": r[5]
        })
    
    return render_template("directory_labels.html", families=families)


@app.route("/download-labels-pdf")
def download_labels_pdf():
    # લૉગિન વગર સીધી જ PDF ડાઉનલોડ થવા માટે અહીંથી ચેક હટાવી દીધો છે
    
    # અહી તમારી PDF જનરેટ થતી કે મોકલવાની બાકીની લાઈનો રહેશે
    # દા.ત. return send_file(...) અથવા જે પણ કોડ હોય તે અહીં રાખવો
    
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT f.id, f.firm_name, f.family_name, f.address, 
               m.name as head_name, m.mobile
        FROM families f
        LEFT JOIN family_members m ON m.id = (
            SELECT id FROM family_members WHERE family_id = f.id ORDER BY id ASC LIMIT 1
        )
        ORDER BY f.id ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    
    families = []
    for r in rows:
        families.append({
            "id": r[0],
            "firm_name": r[1] if r[1] else r[2],
            "family_name": r[2],
            "address": r[3],
            "head_name": r[4],
            "mobile": r[5]
        })
    
    return render_template("directory_labels.html", families=families)

# ============================================================
# Farm Head
# ============================================================
@app.route("/users")
def users_list():
    if not session.get("logged_in") or session.get("role") != 'treasurer':
        return redirect("/")
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, full_name, role, family_id FROM users")
    users = [{"id": r[0], "username": r[1], "full_name": r[2], "role": r[3], "family_id": r[4]} for r in cursor.fetchall()]
    conn.close()
    return render_template("users.html", users=users)

@app.route("/user/add", methods=["GET", "POST"])
def user_add():
    if not session.get("logged_in") or session.get("role") != 'treasurer':
        return redirect("/")
    conn = sqlite3.connect("samaj.db")
    cursor = conn.cursor()
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        full_name = request.form.get("full_name")
        role = request.form.get("role", "Farm Head")
        family_id = request.form.get("family_id") or None
        try:
            cursor.execute("INSERT INTO users (username, password, full_name, role, family_id) VALUES (?, ?, ?, ?, ?)",
                           (username, password, full_name, role, family_id))
            conn.commit()
            conn.close()
            return redirect("/users")
        except Exception as e:
            conn.close()
            return render_template("user_add.html", error="આ યુઝરનેમ પહેલેથી જ અસ્તિત્વમાં છે!", families=[])
            
    cursor.execute("SELECT id, family_name FROM families")
    families = [{"id": r[0], "family_name": r[1]} for r in cursor.fetchall()]
    conn.close()
    return render_template("user_add.html", families=families)

@app.route("/about-contact")
def about_contact():
    return render_template("about_contact.html")

# ============================================================
# RUN APP
# ============================================================
if __name__ == "__main__":
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    app.run(debug=True, host="0.0.0.0", port=5000)
