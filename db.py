import sqlite3, json, os, datetime, yaml

# === RUTA DE LA BASE DE DATOS (local o Render) ==============================
# Si existe la variable de entorno BUDGET_DB (ej: "/data/budget.db" en Render),
# la usamos. Si no, guardamos "budget.db" junto al código (modo local).
DB_PATH = os.environ.get("BUDGET_DB", os.path.join(os.path.dirname(__file__), "budget.db"))

# Crea la carpeta del DB si no existe (útil cuando DB_PATH es /data/budget.db)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ============================================================================

YAML_PATH = os.path.join(os.path.dirname(__file__), "budgets.yaml")

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS category_templates(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ckey TEXT UNIQUE,
            name TEXT,
            ctype TEXT,
            owner TEXT,
            limit_total INTEGER,
            shares_json TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS budgets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_key TEXT,
            month TEXT,
            limit_total INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS contributions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            budget_id INTEGER,
            user TEXT,
            amount INTEGER,
            ts TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS incomes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT,
            amount INTEGER,
            ts TEXT,
            note TEXT
        )
    """)
    conn.commit()
    conn.close()

def ensure_users(usernames=("Jack","Jasmin")):
    conn = get_conn()
    c = conn.cursor()
    for u in usernames:
        c.execute("INSERT OR IGNORE INTO users(name) VALUES(?)", (u,))
    conn.commit()
    conn.close()

def load_templates_from_yaml():
    with open(YAML_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    cats = data.get("categories", [])
    conn = get_conn()
    c = conn.cursor()
    for cat in cats:
        c.execute("""
            INSERT OR REPLACE INTO category_templates(ckey, name, ctype, owner, limit_total, shares_json)
            VALUES(?,?,?,?,?,?)
        """, (
            cat["key"],
            cat["name"],
            cat["type"],
            cat.get("owner"),
            int(cat["limit_total"]),
            json.dumps(cat.get("shares", None)) if cat["type"] == "shared" else None
        ))
    conn.commit()
    conn.close()

def current_month():
    return datetime.datetime.now().strftime("%Y-%m")

def month_name(month_ym=None):
    import calendar
    if not month_ym:
        month_ym = current_month()
    y, m = month_ym.split("-")
    name = calendar.month_name[int(m)]
    return f"{name} {y}"

def ensure_budgets_for_month(month=None):
    if not month:
        month = current_month()
    conn = get_conn()
    c = conn.cursor()
    templates = c.execute("SELECT ckey, name, ctype, owner, limit_total, shares_json FROM category_templates").fetchall()
    for ckey, name, ctype, owner, limit_total, shares_json in templates:
        exists = c.execute("SELECT 1 FROM budgets WHERE template_key=? AND month=?", (ckey, month)).fetchone()
        if not exists:
            c.execute("INSERT INTO budgets(template_key, month, limit_total) VALUES(?,?,?)",
                      (ckey, month, limit_total))
    conn.commit()
    conn.close()

def list_budgets(month=None):
    if not month:
        month = current_month()
    conn = get_conn()
    c = conn.cursor()
    rows = c.execute("""
        SELECT b.id, b.template_key, t.name, t.ctype, t.owner, b.limit_total, t.shares_json
        FROM budgets b
        JOIN category_templates t ON t.ckey = b.template_key
        WHERE b.month = ?
        ORDER BY CASE t.ctype WHEN 'shared' THEN 0 ELSE 1 END, t.name
    """, (month,)).fetchall()
    conn.close()
    return rows

def sum_contribs(budget_id):
    conn = get_conn()
    c = conn.cursor()
    total = c.execute("SELECT COALESCE(SUM(amount),0) FROM contributions WHERE budget_id=?", (budget_id,)).fetchone()[0]
    conn.close()
    return int(total or 0)

def sum_contribs_by_user(budget_id, user):
    conn = get_conn()
    c = conn.cursor()
    total = c.execute("SELECT COALESCE(SUM(amount),0) FROM contributions WHERE budget_id=? AND user=?",
                      (budget_id, user)).fetchone()[0]
    conn.close()
    return int(total or 0)

def add_contribution(budget_id, user, amount):
    conn = get_conn()
    c = conn.cursor()
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    c.execute("INSERT INTO contributions(budget_id, user, amount, ts) VALUES(?,?,?,?)",
              (budget_id, user, int(amount), ts))
    conn.commit()
    conn.close()

def add_income(user, amount, note=""):
    conn = get_conn()
    c = conn.cursor()
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    c.execute("INSERT INTO incomes(user, amount, ts, note) VALUES(?,?,?,?)",
              (user, int(amount), ts, note))
    conn.commit()
    conn.close()

def incomes_for_user(user, limit=20):
    conn = get_conn()
    c = conn.cursor()
    rows = c.execute("""
        SELECT amount, ts, note FROM incomes
        WHERE user=?
        ORDER BY ts DESC
        LIMIT ?
    """, (user, limit)).fetchall()
    conn.close()
    return rows

        ORDER BY ts DESC
        LIMIT ?
    """, (user, limit)).fetchall()
    conn.close()
    return rows
