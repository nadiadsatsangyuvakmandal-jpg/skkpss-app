"""
Standalone database fix script for Samaj App.

Run this ONCE directly, in the SAME folder as your samaj.db file:

    python fix_database.py

This will add any missing columns/tables (event_tag, rollover_log, etc.)
directly, without depending on app.py's automatic migration. It is safe
to run multiple times - it only adds what's missing and never deletes
any of your existing data.

After running this, restart your Flask app normally (python app.py).
"""
import sqlite3
import os
import sys

DB_PATH = "samaj.db"

if not os.path.exists(DB_PATH):
    print(f"❌ '{DB_PATH}' ફાઈલ આ ફોલ્ડરમાં મળી નથી.")
    print(f"   કૃપા કરીને આ સ્ક્રિપ્ટને 'samaj.db' જ્યાં છે ત્યાં જ મૂકીને ચલાવો.")
    sys.exit(1)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print(f"✅ '{DB_PATH}' સાથે જોડાયું. ફિક્સ કરવાનું શરૂ કરું છું...\n")


def column_exists(table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def table_exists(table):
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cursor.fetchone() is not None


fixes_applied = []

# ---- users.role ----
if table_exists("users") and not column_exists("users", "role"):
    cursor.execute("ALTER TABLE users ADD COLUMN role TEXT")
    cursor.execute("UPDATE users SET role='treasurer' WHERE role IS NULL OR role=''")
    fixes_applied.append("users.role (બધા હાલના યુઝર treasurer બન્યા)")
elif table_exists("users"):
    cursor.execute("UPDATE users SET role='treasurer' WHERE role IS NULL OR role=''")

# ---- family_members.house_number ----
if table_exists("family_members") and not column_exists("family_members", "house_number"):
    cursor.execute("ALTER TABLE family_members ADD COLUMN house_number TEXT")
    cursor.execute("UPDATE family_members SET house_number='1' WHERE house_number IS NULL OR house_number=''")
    fixes_applied.append("family_members.house_number (બધા સભ્યો ચૂલો '1' થયા)")
elif table_exists("family_members"):
    cursor.execute("UPDATE family_members SET house_number='1' WHERE house_number IS NULL OR house_number=''")

# ---- payments.year ----
if table_exists("payments") and not column_exists("payments", "year"):
    cursor.execute("ALTER TABLE payments ADD COLUMN year INTEGER")
    import datetime
    this_year = datetime.datetime.now().year
    cursor.execute("UPDATE payments SET year=? WHERE year IS NULL", (this_year,))
    fixes_applied.append(f"payments.year (જૂના રેકોર્ડ {this_year} વર્ષના ગણાયા)")

# ---- yuvak_ledger.event_tag ----
if table_exists("yuvak_ledger") and not column_exists("yuvak_ledger", "event_tag"):
    cursor.execute("ALTER TABLE yuvak_ledger ADD COLUMN event_tag TEXT")
    cursor.execute("UPDATE yuvak_ledger SET event_tag='સામાન્ય' WHERE event_tag IS NULL OR event_tag=''")
    fixes_applied.append("yuvak_ledger.event_tag (બધી જૂની એન્ટ્રી 'સામાન્ય' પ્રસંગની ગણાઈ)")
elif table_exists("yuvak_ledger"):
    cursor.execute("UPDATE yuvak_ledger SET event_tag='સામાન્ય' WHERE event_tag IS NULL OR event_tag=''")

# ---- app_settings table ----
if not table_exists("app_settings"):
    cursor.execute("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT)")
    fixes_applied.append("app_settings ટેબલ બનાવ્યું")

cursor.execute("SELECT value FROM app_settings WHERE key='current_collection_year'")
row = cursor.fetchone()
if not row:
    import datetime
    this_year = datetime.datetime.now().year
    cursor.execute("INSERT INTO app_settings (key, value) VALUES ('current_collection_year', ?)", (str(this_year),))
    fixes_applied.append(f"ચાલુ વર્ષ {this_year} સેટ કર્યું")

# ---- rollover_log table ----
if not table_exists("rollover_log"):
    cursor.execute("""
        CREATE TABLE rollover_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year_from INTEGER,
            year_to INTEGER,
            family_id INTEGER,
            amount_added REAL,
            created_at TEXT
        )
    """)
    fixes_applied.append("rollover_log ટેબલ બનાવ્યું")

conn.commit()
conn.close()

print("=" * 55)
if fixes_applied:
    print("✅ આ ફિક્સ કર્યા:")
    for f in fixes_applied:
        print(f"   • {f}")
else:
    print("✅ બધું પહેલેથી બરાબર છે — કંઈ ફિક્સ કરવાની જરૂર નહોતી.")
print("=" * 55)
print("\nહવે તમારી Flask app ફરી ચલાવો (python app.py) અને પેજ ચેક કરો.")
