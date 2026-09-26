#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pizza POS — Restaurant Management Suite (single-file desktop app)
PyQt5 + SQLite.  Default login:  admin / admin123
Prices in Lebanese Pound (LBP); USD shown as secondary at the configured rate.
Receipt printing is LOCAL (system printer by name, raw ESC/POS bytes).
Each receipt prints two copies: CUSTOMER COPY + RESTAURANT COPY.

Menu (v2):
  Pizza     → Small 750,000 / Medium 900,000 / Large 1,100,000
              (Large: pick 2 flavors; BBQ ⇒ 1,200,000)
  Cheese Garlic Fingers → Small 600,000 / Medium 700,000
  Chicken Wings         → 12pcs 600,000 / 12pcs+Fries 800,000 / 24pcs 1,100,000
  Chicken Strips        → 5pcs 700,000 / 10pcs 1,300,000 / 20pcs 2,400,000
  Special Offer         → 5pcs + Fries + Pepsi  1,000,000
  Fries                 → Small 300,000 / Medium 400,000 / XXL 600,000
  Soft Drink            → 300ml 100,000 / 1.25L 200,000
"""
import sys, os, json, sqlite3, secrets, hashlib
import urllib.request, urllib.error, ssl
import subprocess, tempfile
from datetime import datetime, date, timedelta

from PyQt5.QtCore import (Qt, QTimer, pyqtSignal, QSize, QDate)
from PyQt5.QtGui import (QFont, QColor, QDoubleValidator)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QDialog, QFrame, QLabel, QPushButton,
    QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox,
    QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QStackedWidget,
    QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QDateEdit, QSizePolicy, QButtonGroup, QAbstractItemView,
    QGraphicsDropShadowEffect, QInputDialog, QCompleter
)

# ════════════════════════════════════════════════════════════════
#  FIREBASE CONFIGURATION
# ════════════════════════════════════════════════════════════════
FIREBASE_CONFIG = {
    "apiKey":            "AIzaSyCmj9fwRLmiQU-g5zvd6XzE8i2X9eNr7TQ",
    "authDomain":        "hyperpos-12210.firebaseapp.com",
    "projectId":         "hyperpos-12210",
    "storageBucket":     "hyperpos-12210.firebasestorage.app",
    "messagingSenderId": "641877559339",
    "appId":             "1:641877559339:web:b95061f96efe5da489026e",
    "measurementId":     "G-HLZWW4DRY4",
}

# ════════════════════════════════════════════════════════════════
#  DATABASE / APP CONSTANTS
# ════════════════════════════════════════════════════════════════
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pizza_pos.db")

# ── Global options used by the six pizzas ──────────────────────
DEFAULT_OPTIONS = [
    {"name": "Size", "multi": False, "choices": [
        {"label": "Small",  "price":  750000},
        {"label": "Medium", "price":  900000},
        {"label": "Large",  "price": 1100000}]},
    {"name": "Flavor", "multi": True, "max_choices": 2, "large_only": True,
     "choices": [
        {"label": "Lebanese",    "price": 0},
        {"label": "Pepperoni",   "price": 0},
        {"label": "Vegetarian",  "price": 0},
        {"label": "Margherita",  "price": 0},
        {"label": "Plain",       "price": 0},
        {"label": "Chicken BBQ", "price": 0}]},
]

CHICKEN_BBQ_LARGE_PRICE = 1_200_000   # any BBQ + Large

DEFAULT_SETTINGS = {
    "restaurant_name": "Pizza POS",
    "tagline":         "Restaurant Management Suite",
    "address":         "123 Main Street",
    "phone":           "+961 1 234 567",
    "currency_symbol": "LBP ",
    "secondary_currency": "USD",
    "secondary_rate":  "90000",
    "delivery_fee":    "270000",
    "theme":           "light",
    "receipt_footer":  "Thank you for your visit!",
    "product_options": json.dumps(DEFAULT_OPTIONS),
    "low_stock_default": "5",
    # Local printer (system printer name / queue name)
    "printer_name":    "",
    "printer_auto":    "1",
    # Firebase cloud-sync
    "firebase_enabled":         "0",
    "firebase_collection_orders": "orders",
    "firebase_collection_customers": "customers",
    "firebase_collection_cash": "close_cash",
}

# ── Only these categories exist ────────────────────────────────
SEED_CATEGORIES = ["Pizza", "Sides", "Chicken", "Drinks"]

# ── Products (pizza base price is 0 — options provide absolute prices) ──
# tuple: (name, emoji, category, price, cost, stock, track, has_options)
SEED_PRODUCTS = [
    # Pizza
    ("Lebanese Pizza",    "🍕", "Pizza",   0, 0, 0, 0, 1),
    ("Pepperoni Pizza",   "🍕", "Pizza",   0, 0, 0, 0, 1),
    ("Vegetarian Pizza",  "🥬", "Pizza",   0, 0, 0, 0, 1),
    ("Margherita Pizza",  "🍕", "Pizza",   0, 0, 0, 0, 1),
    ("Plain Pizza",       "🍕", "Pizza",   0, 0, 0, 0, 1),
    ("Chicken BBQ Pizza", "🍕", "Pizza",   0, 0, 0, 0, 1),
    # Sides (options added by _migrate_products)
    ("Cheese Garlic Fingers", "🧄", "Sides",   0, 180000, 50, 1, 1),
    ("Fries",                 "🍟", "Sides",   0, 100000, 60, 1, 1),
    # Chicken (options added by _migrate_products)
    ("Chicken Wings",  "🍗", "Chicken",       0,       0,  0, 0, 1),
    ("Chicken Strips", "🍗", "Chicken",       0,       0,  0, 0, 1),
    ("Special Offer (5 pcs + Fries + Pepsi)", "🎁", "Chicken",
     1000000, 0, 0, 0, 0),
    # Drinks (options added by _migrate_products)
    ("Soft Drink", "🥤", "Drinks", 0, 55000, 120, 1, 1),
]

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL, full_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'cashier', active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT '🍕',
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    price REAL NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0,
    stock REAL NOT NULL DEFAULT 0, track_stock INTEGER NOT NULL DEFAULT 0,
    low_stock REAL NOT NULL DEFAULT 5, has_options INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    size_prices TEXT NOT NULL DEFAULT '',
    custom_options TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '',
    points INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, order_no TEXT UNIQUE NOT NULL,
    order_type TEXT NOT NULL DEFAULT 'Delivery',
    status TEXT NOT NULL DEFAULT 'open',
    customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    customer_name TEXT NOT NULL DEFAULT '',
    subtotal REAL NOT NULL DEFAULT 0, discount REAL NOT NULL DEFAULT 0,
    tax REAL NOT NULL DEFAULT 0, delivery REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    payment_method TEXT NOT NULL DEFAULT 'Cash',
    user_id INTEGER, note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, closed_at TEXT);
CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER, name TEXT NOT NULL, qty REAL NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL DEFAULT 0, options TEXT NOT NULL DEFAULT '',
    line_total REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL DEFAULT 'General',
    description TEXT NOT NULL DEFAULT '', amount REAL NOT NULL DEFAULT 0,
    spent_on TEXT NOT NULL, user_id INTEGER, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS stock_moves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    change REAL NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(name);
CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
"""


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    d = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"{salt}${d.hex()}"


def verify_password(password, stored):
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return secrets.compare_digest(hash_password(password, salt), stored)


# ════════════════════════════════════════════════════════════════
#  FIREBASE CLOUD SYNC (Firestore REST + anonymous Auth)
# ════════════════════════════════════════════════════════════════
def _firestore_value(v):
    if v is None:                return {"nullValue": None}
    if isinstance(v, bool):      return {"booleanValue": v}
    if isinstance(v, int):       return {"integerValue": str(v)}
    if isinstance(v, float):     return {"doubleValue": v}
    if isinstance(v, str):       return {"stringValue": v}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [_firestore_value(x) for x in v]}}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: _firestore_value(x)
                                        for k, x in v.items()}}}
    return {"stringValue": str(v)}


def _firestore_doc(d):
    return {"fields": {k: _firestore_value(v) for k, v in d.items()}}


class FirebaseSync:
    def __init__(self, config=None):
        self.config     = dict(config or FIREBASE_CONFIG)
        self.project_id = self.config.get("projectId", "")
        self.api_key    = self.config.get("apiKey", "")
        self._id_token  = None

    def _sign_in_anonymous(self, timeout=8):
        url = (f"https://identitytoolkit.googleapis.com/v1/"
               f"accounts:signUp?key={self.api_key}")
        body = json.dumps({"returnSecureToken": True}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self._id_token = data.get("idToken")
            return self._id_token

    def _ensure_token(self):
        if not self._id_token:
            try:
                self._sign_in_anonymous()
            except Exception:
                self._id_token = None
        return self._id_token

    def push_document(self, collection, data, timeout=8):
        self._ensure_token()
        url = (f"https://firestore.googleapis.com/v1/projects/"
               f"{self.project_id}/databases/(default)/documents/"
               f"{collection}?key={self.api_key}")
        body = json.dumps(_firestore_doc(data)).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        if self._id_token:
            req.add_header("Authorization", f"Bearer {self._id_token}")
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return True, f"HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            return False, f"HTTP {e.code}: {detail[:220]}"
        except Exception as e:
            return False, str(e)


# ════════════════════════════════════════════════════════════════
#  DATABASE
# ════════════════════════════════════════════════════════════════
class Database:
    def __init__(self, path=DB_PATH):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(products)")}
        if "size_prices" not in cols:
            self.conn.execute(
                "ALTER TABLE products ADD COLUMN size_prices TEXT NOT NULL DEFAULT ''")
        if "custom_options" not in cols:
            self.conn.execute(
                "ALTER TABLE products ADD COLUMN custom_options TEXT NOT NULL DEFAULT ''")
        self.conn.commit()
        self._seed()
        self._reset_products_v2()
        self._migrate_options()
        self._migrate_products()

    def q(self, sql, args=()):       return self.conn.execute(sql, args).fetchall()
    def one(self, sql, args=()):     return self.conn.execute(sql, args).fetchone()
    def ex(self, sql, args=()):
        cur = self.conn.execute(sql, args); self.conn.commit(); return cur

    # ---------------------------------------------------------- seed
    def _seed(self):
        for k, v in DEFAULT_SETTINGS.items():
            self.conn.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        self.conn.commit()
        if (self.one("SELECT COUNT(*) c FROM users")["c"]) == 0:
            self.ex("INSERT INTO users(username,password,full_name,role,created_at) "
                    "VALUES(?,?,?,?,?)",
                    ("admin", hash_password("admin123"), "Administrator", "manager",
                     datetime.now().isoformat(timespec="seconds")))
        if (self.one("SELECT COUNT(*) c FROM categories")["c"]) == 0:
            for i, name in enumerate(SEED_CATEGORIES):
                self.conn.execute("INSERT INTO categories(name, sort_order) VALUES(?,?)",
                                  (name, i))
            self.conn.commit()

    # ------------------------------------------ one-time product reset
    def _reset_products_v2(self):
        """Wipe all products and re-seed from SEED_PRODUCTS (one time)."""
        if self.get_setting("products_v2_reset") == "1":
            return
        # Ensure every category exists first
        for i, name in enumerate(SEED_CATEGORIES):
            self.conn.execute(
                "INSERT OR IGNORE INTO categories(name, sort_order) VALUES(?,?)",
                (name, i))
        self.conn.commit()

        self.ex("DELETE FROM products")
        cats = {r["name"]: r["id"] for r in self.q("SELECT id,name FROM categories")}
        low = float(self.get_setting("low_stock_default", "5") or 5)
        for (n, e, c, p, co, s, t, o) in SEED_PRODUCTS:
            self.conn.execute(
                "INSERT INTO products(name,emoji,category_id,price,cost,stock,"
                "track_stock,low_stock,has_options,active,size_prices,custom_options) "
                "VALUES(?,?,?,?,?,?,?,?,?,1,'','')",
                (n, e, cats.get(c), p, co, s, t, low, o))
        self.conn.commit()
        self.set_setting("products_v2_reset", "1")

    # ------------------------------------------ options migration
    def _migrate_options(self):
        """Force the global product_options to the current defaults."""
        if self.get_setting("options_v2") == "1":
            return
        self.set_setting("product_options", json.dumps(DEFAULT_OPTIONS))
        self.set_setting("options_v2", "1")

    # ------------------------------------------ product options
    def _migrate_products(self):
        """Attach the correct custom_options to the side / chicken / drinks."""
        cats = {r["name"]: r["id"] for r in self.q("SELECT id,name FROM categories")}
        sides_id   = cats.get("Sides")
        chicken_id = cats.get("Chicken")
        drinks_id  = cats.get("Drinks")

        cgf_opts = json.dumps([
            {"name": "Size", "multi": False, "choices": [
                {"label": "Small",  "price": 600000},
                {"label": "Medium", "price": 700000}]}
        ])
        ff_opts = json.dumps([
            {"name": "Size", "multi": False, "choices": [
                {"label": "Small",  "price": 300000},
                {"label": "Medium", "price": 400000},
                {"label": "XXL",    "price": 600000}]}
        ])
        cw_opts = json.dumps([
            {"name": "Portion", "multi": False, "choices": [
                {"label": "12 pcs",         "price": 600000},
                {"label": "12 pcs + Fries", "price": 800000},
                {"label": "24 pcs",         "price": 1100000}]}
        ])
        cs_opts = json.dumps([
            {"name": "Portion", "multi": False, "choices": [
                {"label": "5 pcs",  "price":  700000},
                {"label": "10 pcs", "price": 1300000},
                {"label": "20 pcs", "price": 2400000}]}
        ])
        sd_opts = json.dumps([
            {"name": "Size", "multi": False, "choices": [
                {"label": "300ml", "price": 100000},
                {"label": "1.25L", "price": 200000}]}
        ])

        def ensure(name, emoji, cat_id, price, cost, stock, track, has_opts, opts_json):
            r = self.one("SELECT id, custom_options FROM products WHERE name=?", (name,))
            if not r:
                self.ex("""INSERT INTO products(name, emoji, category_id, price, cost,
                          stock, track_stock, low_stock, has_options, active,
                          size_prices, custom_options)
                          VALUES(?,?,?,?,?,?,?,?,?,1,?,?)""",
                        (name, emoji, cat_id, price, cost, stock, track,
                         float(self.get_setting("low_stock_default", "5") or 5),
                         1 if has_opts else 0, "", opts_json or ""))
                return
            # Update options to the latest version if they differ
            want = opts_json or ""
            current = (r["custom_options"] or "")
            if current != want or int(self.one(
                    "SELECT has_options FROM products WHERE id=?", (r["id"],))["has_options"]) \
                    != (1 if has_opts else 0):
                self.ex("""UPDATE products SET custom_options=?, has_options=?,
                          price=?, size_prices='' WHERE id=?""",
                        (want, 1 if has_opts else 0, price, r["id"]))

        if sides_id:
            ensure("Cheese Garlic Fingers", "🧄", sides_id, 0, 180000, 50, 1, True, cgf_opts)
            ensure("Fries",                 "🍟", sides_id, 0, 100000, 60, 1, True, ff_opts)
        if chicken_id:
            ensure("Chicken Wings",  "🍗", chicken_id, 0, 0, 0, 0, True, cw_opts)
            ensure("Chicken Strips", "🍗", chicken_id, 0, 0, 0, 0, True, cs_opts)
            ensure("Special Offer (5 pcs + Fries + Pepsi)", "🎁", chicken_id,
                   1000000, 0, 0, 0, False, "")
        if drinks_id:
            ensure("Soft Drink", "🥤", drinks_id, 0, 55000, 120, 1, True, sd_opts)

    # ----- settings -----
    def get_setting(self, key, default=None):
        r = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return r["value"] if r else default

    def set_setting(self, key, value):
        self.ex("INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def all_settings(self):
        return {r["key"]: r["value"] for r in self.q("SELECT key,value FROM settings")}

    def product_options(self):
        try:    return json.loads(self.get_setting("product_options") or "[]")
        except Exception: return []

    def size_choices(self):
        for grp in self.product_options():
            if grp.get("name") == "Size":
                return grp.get("choices", [])
        return []

    def product_options_for(self, product):
        custom_raw = (product or {}).get("custom_options") or ""
        if custom_raw.strip():
            try:
                custom = json.loads(custom_raw)
                if isinstance(custom, list) and custom:
                    return custom
            except Exception:
                pass
        import copy
        options = copy.deepcopy(self.product_options())
        try:
            custom = json.loads((product or {}).get("size_prices") or "{}")
        except Exception:
            custom = {}
        if not isinstance(custom, dict):
            custom = {}
        for grp in options:
            if grp.get("name") == "Size":
                for ch in grp.get("choices", []):
                    if ch["label"] in custom:
                        try:
                            ch["price"] = float(custom[ch["label"]])
                        except (TypeError, ValueError):
                            pass
        return options

    # ----- auth -----
    def authenticate(self, u, p):
        r = self.one("SELECT * FROM users WHERE username=? AND active=1", (u,))
        if r and verify_password(p, r["password"]):
            return dict(r)
        return None

    def users(self):    return self.q("SELECT * FROM users ORDER BY id")
    def add_user(self, u, p, n, r):
        self.ex("INSERT INTO users(username,password,full_name,role,created_at) "
                "VALUES(?,?,?,?,?)", (u, hash_password(p), n, r,
                                      datetime.now().isoformat(timespec="seconds")))
    def delete_user(self, uid):
        self.ex("DELETE FROM users WHERE id=? AND username<>'admin'", (uid,))

    # ----- categories -----
    def categories(self):
        return self.q("SELECT * FROM categories ORDER BY sort_order, name")
    def add_category(self, name):
        self.ex("INSERT OR IGNORE INTO categories(name, sort_order) VALUES(?,99)", (name,))

    # ----- products -----
    def products(self, search="", category_id=None, only_active=True):
        sql = ("SELECT p.*, c.name AS category FROM products p "
               "LEFT JOIN categories c ON c.id=p.category_id WHERE 1=1")
        args = []
        if only_active: sql += " AND p.active=1"
        if category_id: sql += " AND p.category_id=?"; args.append(category_id)
        if search:
            sql += " AND (p.name LIKE ? OR c.name LIKE ?)"
            args += [f"%{search}%", f"%{search}%"]
        sql += " ORDER BY c.sort_order, p.name"
        return self.q(sql, args)

    def get_product(self, pid):
        r = self.one("SELECT * FROM products WHERE id=?", (pid,))
        return dict(r) if r else None

    def save_product(self, d, pid=None):
        sp = d.get("size_prices", "") or ""
        co = d.get("custom_options", "") or ""
        price = d.get("price", 0)
        cost  = d.get("cost", 0)
        stock = d.get("stock", 0)
        track = d.get("track_stock", 0)
        low   = d.get("low_stock", 5)
        if pid:
            self.ex("UPDATE products SET name=?,emoji=?,category_id=?,price=?,cost=?,"
                    "stock=?,track_stock=?,low_stock=?,has_options=?,active=?,"
                    "size_prices=?,custom_options=? WHERE id=?",
                    (d["name"], d["emoji"], d["category_id"], price, cost,
                     stock, track, low, d["has_options"], d["active"], sp, co, pid))
            return pid
        cur = self.ex("INSERT INTO products(name,emoji,category_id,price,cost,stock,"
                      "track_stock,low_stock,has_options,active,size_prices,"
                      "custom_options) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (d["name"], d["emoji"], d["category_id"], price, cost,
                       stock, track, low, d["has_options"], d["active"], sp, co))
        return cur.lastrowid

    def delete_product(self, pid): self.ex("DELETE FROM products WHERE id=?", (pid,))

    def adjust_stock(self, pid, change, reason="Adjustment"):
        self.ex("UPDATE products SET stock=stock+? WHERE id=?", (change, pid))
        self.ex("INSERT INTO stock_moves(product_id,change,reason,created_at) "
                "VALUES(?,?,?,?)",
                (pid, change, reason, datetime.now().isoformat(timespec="seconds")))

    def low_stock_products(self):
        return self.q("SELECT * FROM products WHERE active=1 AND track_stock=1 "
                      "AND stock<=low_stock ORDER BY stock")

    # ----- customers -----
    def customers(self, search=""):
        if search:
            return self.q("SELECT * FROM customers WHERE name LIKE ? OR phone LIKE ? "
                          "ORDER BY name", (f"%{search}%", f"%{search}%"))
        return self.q("SELECT * FROM customers ORDER BY name")

    def save_customer(self, d, cid=None):
        pts = int(d.get("points", 0) or 0)
        if cid:
            self.ex("UPDATE customers SET name=?,phone=?,address=?,points=? WHERE id=?",
                    (d["name"], d["phone"], d["address"], pts, cid))
            return cid
        cur = self.ex("INSERT INTO customers(name,phone,address,points,created_at) "
                      "VALUES(?,?,?,?,?)", (d["name"], d["phone"], d["address"], pts,
                                           datetime.now().isoformat(timespec="seconds")))
        return cur.lastrowid

    def delete_customer(self, cid): self.ex("DELETE FROM customers WHERE id=?", (cid,))

    # ----- orders -----
    def next_order_no(self):
        today = date.today().strftime("%Y%m%d")
        r = self.one("SELECT COUNT(*) c FROM orders WHERE order_no LIKE ?",
                     (f"ORD-{today}-%",))
        return f"ORD-{today}-{(r['c'] if r else 0) + 1:04d}"

    def open_orders(self):
        rows = self.q("SELECT * FROM orders WHERE status='open' ORDER BY id")
        out = []
        for o in rows:
            d = dict(o)
            d["items"] = [dict(i) for i in self.q(
                "SELECT * FROM order_items WHERE order_id=? ORDER BY id", (o["id"],))]
            out.append(d)
        return out

    def save_order(self, o, status="open"):
        now = datetime.now().isoformat(timespec="seconds")
        oid = o.get("id")
        if oid:
            self.ex("""UPDATE orders SET order_type=?,status=?,customer_id=?,
                       customer_name=?,subtotal=?,discount=?,tax=?,delivery=?,
                       total=?,payment_method=?,note=? WHERE id=?""",
                    (o["type"], status, o.get("customer_id"), o.get("customer_name", ""),
                     o["subtotal"], o["discount"], o["tax"], o["delivery"], o["total"],
                     o.get("payment_method", "Cash"), o.get("note", ""), oid))
            self.ex("DELETE FROM order_items WHERE order_id=?", (oid,))
        else:
            cur = self.ex("""INSERT INTO orders(order_no,order_type,status,customer_id,
                             customer_name,subtotal,discount,tax,delivery,total,
                             payment_method,user_id,note,created_at)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (o["no"], o["type"], status, o.get("customer_id"),
                           o.get("customer_name", ""), o["subtotal"], o["discount"],
                           o["tax"], o["delivery"], o["total"],
                           o.get("payment_method", "Cash"), o.get("user_id"),
                           o.get("note", ""), now))
            oid = cur.lastrowid
            o["id"] = oid
        for it in o["items"]:
            opts = ", ".join(x["label"] for x in it.get("options", []))
            self.ex("""INSERT INTO order_items(order_id,product_id,name,qty,unit_price,
                       options,line_total) VALUES(?,?,?,?,?,?,?)""",
                    (oid, it.get("product_id"), it["name"], it["qty"], it["unit"],
                     opts, it["line"]))
        if status == "paid":
            self.ex("UPDATE orders SET closed_at=? WHERE id=?", (now, oid))
        return oid

    def close_order(self, oid, payment_method="Cash", user_id=None):
        now = datetime.now().isoformat(timespec="seconds")
        self.ex("UPDATE orders SET status='paid',payment_method=?,closed_at=?,"
                "user_id=COALESCE(?,user_id) WHERE id=?",
                (payment_method, now, user_id, oid))

    def delete_order(self, oid): self.ex("DELETE FROM orders WHERE id=?", (oid,))

    def deduct_stock_for_order(self, o):
        for it in o["items"]:
            pid = it.get("product_id")
            if not pid: continue
            p = self.get_product(pid)
            if p and p["track_stock"]:
                self.adjust_stock(pid, -float(it["qty"]), f"Order {o['no']}")

    # ----- expenses -----
    def expenses(self, start=None, end=None):
        sql = "SELECT * FROM expenses WHERE 1=1"; args = []
        if start: sql += " AND spent_on>=?"; args.append(start)
        if end:   sql += " AND spent_on<=?"; args.append(end)
        sql += " ORDER BY spent_on DESC, id DESC"
        return self.q(sql, args)

    def save_expense(self, d, eid=None):
        if eid:
            self.ex("UPDATE expenses SET category=?,description=?,amount=?,spent_on=? "
                    "WHERE id=?", (d["category"], d["description"], d["amount"],
                                   d["spent_on"], eid))
            return eid
        cur = self.ex("INSERT INTO expenses(category,description,amount,spent_on,"
                      "user_id,created_at) VALUES(?,?,?,?,?,?)",
                      (d["category"], d["description"], d["amount"], d["spent_on"],
                       d.get("user_id"), datetime.now().isoformat(timespec="seconds")))
        return cur.lastrowid

    def delete_expense(self, eid): self.ex("DELETE FROM expenses WHERE id=?", (eid,))

    # ----- reports -----
    def summary(self, start, end):
        r = self.one("""SELECT COUNT(*) orders, COALESCE(SUM(total),0) revenue,
                        COALESCE(SUM(discount),0) discount, COALESCE(SUM(tax),0) tax
                        FROM orders WHERE status='paid'
                        AND date(created_at) BETWEEN ? AND ?""", (start, end))
        e = self.one("SELECT COALESCE(SUM(amount),0) t FROM expenses "
                     "WHERE spent_on BETWEEN ? AND ?", (start, end))
        return {"orders": r["orders"] if r else 0, "revenue": r["revenue"] if r else 0,
                "discount": r["discount"] if r else 0, "tax": r["tax"] if r else 0,
                "expenses": e["t"] if e else 0}

    def top_products(self, start, end, limit=10):
        return self.q("""SELECT oi.name, SUM(oi.qty) qty, SUM(oi.line_total) revenue
                         FROM order_items oi JOIN orders o ON o.id=oi.order_id
                         WHERE o.status='paid' AND date(o.created_at) BETWEEN ? AND ?
                         GROUP BY oi.name ORDER BY revenue DESC LIMIT ?""",
                      (start, end, limit))

    def sales_by_day(self, start, end):
        return self.q("""SELECT date(created_at) day, COUNT(*) orders, SUM(total) revenue
                         FROM orders WHERE status='paid'
                         AND date(created_at) BETWEEN ? AND ?
                         GROUP BY day ORDER BY day DESC""", (start, end))

    def sales_by_category(self, start, end):
        return self.q("""SELECT COALESCE(c.name,'Other') category, SUM(oi.line_total) revenue
                         FROM order_items oi JOIN orders o ON o.id=oi.order_id
                         LEFT JOIN products p ON p.id=oi.product_id
                         LEFT JOIN categories c ON c.id=p.category_id
                         WHERE o.status='paid' AND date(o.created_at) BETWEEN ? AND ?
                         GROUP BY category ORDER BY revenue DESC""", (start, end))

    def sales_by_method(self, start, end):
        return self.q("""SELECT payment_method method, COUNT(*) c, SUM(total) revenue
                         FROM orders WHERE status='paid'
                         AND date(created_at) BETWEEN ? AND ?
                         GROUP BY method""", (start, end))

    def cash_summary(self, start, end):
        r = self.one("""SELECT COUNT(*) c, COALESCE(SUM(total),0) t
                        FROM orders WHERE status='paid'
                        AND payment_method='Cash'
                        AND date(created_at) BETWEEN ? AND ?""", (start, end))
        e = self.one("SELECT COALESCE(SUM(amount),0) t FROM expenses "
                     "WHERE spent_on BETWEEN ? AND ?", (start, end))
        cash_orders = r["c"] if r else 0
        cash_sales  = r["t"] if r else 0.0
        exp         = e["t"] if e else 0.0
        return {"cash_orders": cash_orders,
                "cash_sales":  cash_sales,
                "expenses":    exp,
                "expected":    cash_sales - exp}


# ════════════════════════════════════════════════════════════════
#  LOCAL PRINTER (system printer by name, raw ESC/POS bytes)
# ════════════════════════════════════════════════════════════════
RECEIPT_WIDTH = 42
CUT_FULL       = b"\x1d\x56\x41\x10"
CUT_PARTIAL    = b"\x1d\x56\x42\x10"


def _center(s, w=RECEIPT_WIDTH): return s.center(w)


def _lr(left, right, w=RECEIPT_WIDTH):
    gap = w - len(left) - len(right)
    if gap < 1: gap = 1
    return left + " " * gap + right


def _sep(ch="-", w=RECEIPT_WIDTH): return ch * w


def build_receipt_text(order, settings, copy_label=""):
    sym = settings.get("currency_symbol", "LBP ")
    lines = []
    name = settings.get("restaurant_name", "Pizza POS")
    tagline = settings.get("tagline", "")
    address = settings.get("address", "")
    phone = settings.get("phone", "")

    lines.append(_center(name))
    if tagline: lines.append(_center(tagline))
    if address: lines.append(_center(address))
    if phone:   lines.append(_center(phone))
    lines.append(_sep("-"))
    if copy_label:
        lines.append(_center(f"*** {copy_label} ***"))
        lines.append(_sep("-"))

    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(_lr(f"Order: {order['no']}", when))
    if order.get("customer_name"):
        lines.append(f"Customer: {order['customer_name']}")
    lines.append(f"Type: {order.get('type', 'Delivery')}")
    lines.append(_sep("-"))

    for it in order["items"]:
        lines.append(it["name"])
        opts = ", ".join(o["label"] for o in it.get("options", []))
        if opts: lines.append(f"  {opts}")
        left = f"  {it['qty']} x {fmt_money(it['unit'], sym)}"
        right = fmt_money(it["line"], sym)
        lines.append(_lr(left, right))

    lines.append(_sep("-"))
    lines.append(_lr("Subtotal", fmt_money(order["subtotal"], sym)))
    if order.get("discount"):
        lines.append(_lr("Discount", "-" + fmt_money(order["discount"], sym)))
    if order.get("delivery"):
        lines.append(_lr("Delivery", fmt_money(order["delivery"], sym)))
    lines.append(_sep("="))
    lines.append(_lr("TOTAL", fmt_money(order["total"], sym)))
    try:
        rate = float(settings.get("secondary_rate", "90000") or 90000)
    except (TypeError, ValueError):
        rate = 90000.0
    if rate:
        usd = float(order["total"]) / rate
        sec_sym = "$" if (settings.get("secondary_currency", "USD") or "USD").upper() == "USD" \
                  else (settings.get("secondary_currency", "USD") + " ")
        lines.append(_center(f"{sec_sym}{usd:,.2f}  @ {rate:,.0f}"))
    lines.append(_sep("="))
    lines.append(_lr("Payment", order.get("payment_method", "Cash")))
    lines.append(_sep("-"))
    footer = settings.get("receipt_footer", "Thank you!")
    if footer: lines.append(_center(footer))
    lines.append(""); lines.append("")
    return "\n".join(lines)


def _escpos_wrap(text):
    ESC = b"\x1b"
    data = b""
    data += ESC + b"@"
    data += ESC + b"a\x00"
    data += ESC + b"!\x00"
    data += text.encode("cp437", errors="replace")
    data += b"\n\n\n\n"
    data += CUT_FULL
    return data


def list_local_printers():
    """Best-effort list of locally installed printers / queues."""
    names = []
    try:
        if os.name == "nt":
            try:
                import win32print
                flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
                for entry in win32print.EnumPrinters(flags):
                    # entry: (flags, description, name, comment)
                    names.append(entry[2])
            except ImportError:
                try:
                    out = subprocess.run(
                        ["wmic", "printer", "get", "name"],
                        capture_output=True, text=True, timeout=6)
                    for line in out.stdout.splitlines()[1:]:
                        line = line.strip()
                        if line and line.lower() != "name":
                            names.append(line)
                except Exception:
                    pass
        else:
            try:
                out = subprocess.run(["lpstat", "-a"],
                                     capture_output=True, text=True, timeout=6)
                for line in out.stdout.splitlines():
                    parts = line.split()
                    if parts:
                        names.append(parts[0])
            except Exception:
                pass
    except Exception:
        pass
    # De-duplicate, keep order
    seen = set()
    uniq = []
    for n in names:
        if n and n not in seen:
            seen.add(n); uniq.append(n)
    return uniq


def _send_raw_to_local_printer(printer_name, payload):
    """Send raw bytes to a local printer.  Raises on failure."""
    if os.name == "nt":
        # Preferred: pywin32 (raw spooling) — works for ESC/POS thermal printers
        try:
            import win32print
            if printer_name:
                h = win32print.OpenPrinter(printer_name)
            else:
                h = win32print.OpenPrinter(win32print.GetDefaultPrinter())
            try:
                win32print.StartDocPrinter(h, 1, ("PizzaPOS Receipt", None, "RAW"))
                try:
                    win32print.StartPagePrinter(h)
                    win32print.WritePrinter(h, payload)
                    win32print.EndPagePrinter(h)
                finally:
                    win32print.EndDocPrinter(h)
            finally:
                win32print.ClosePrinter(h)
            return
        except ImportError:
            pass
        # Fallback: write raw file and use the OS "print" verb
        with tempfile.NamedTemporaryFile("wb", suffix=".prn",
                                         prefix="pizza_pos_", delete=False) as f:
            f.write(payload)
            path = f.name
        try:
            os.startfile(path, "print")
        except Exception:
            try: os.unlink(path)
            except Exception: pass
            raise
        # Don't delete immediately — the spooler may still need the file.
        return
    # Unix / macOS — use lp (CUPS)
    with tempfile.NamedTemporaryFile("wb", suffix=".prn",
                                     prefix="pizza_pos_", delete=False) as f:
        f.write(payload)
        path = f.name
    try:
        cmd = ["lp"]
        if printer_name:
            cmd += ["-d", printer_name]
        cmd.append(path)
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        try: os.unlink(path)
        except Exception: pass


def print_receipt_local(printer_name, text):
    _send_raw_to_local_printer(printer_name, _escpos_wrap(text))


def print_receipt_two_copies_local(printer_name, order, settings):
    customer   = build_receipt_text(order, settings, "CUSTOMER COPY")
    restaurant = build_receipt_text(order, settings, "RESTAURANT COPY")
    payload    = _escpos_wrap(customer) + _escpos_wrap(restaurant)
    _send_raw_to_local_printer(printer_name, payload)


def build_close_cash_text(db, start, end, settings):
    sym = settings.get("currency_symbol", "LBP ")
    cash = db.cash_summary(start, end)
    lines = []
    lines.append(_center(settings.get("restaurant_name", "Pizza POS")))
    lines.append(_center("CLOSE CASH REPORT"))
    lines.append(_sep("="))
    lines.append(_center(f"{start}  ->  {end}"))
    lines.append(_sep("-"))
    lines.append(_lr("Cash orders", str(cash["cash_orders"])))
    lines.append(_lr("Cash sales", fmt_money(cash["cash_sales"], sym)))
    lines.append(_lr("Expenses", fmt_money(cash["expenses"], sym)))
    lines.append(_sep("="))
    lines.append(_lr("EXPECTED DRAWER", fmt_money(cash["expected"], sym)))
    try:
        rate = float(settings.get("secondary_rate", "90000") or 90000)
    except (TypeError, ValueError):
        rate = 90000.0
    if rate:
        sec_sym = "$" if (settings.get("secondary_currency", "USD") or "USD").upper() == "USD" \
                  else (settings.get("secondary_currency", "USD") + " ")
        lines.append(_center(f"{sec_sym}{cash['expected'] / rate:,.2f}  @ {rate:,.0f}"))
    lines.append(_sep("="))
    lines.append("")
    lines.append(_lr("Opened by", "________________"))
    lines.append(_lr("Closed by", "________________"))
    lines.append(_lr("Signature", "________________"))
    lines.append("")
    lines.append(_center(datetime.now().strftime("%Y-%m-%d %H:%M")))
    lines.append("")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════
#  THEME / QSS
# ════════════════════════════════════════════════════════════════
def build_qss(theme="light"):
    if theme == "dark":
        c = {"bg": "#0a0f1c", "surface": "#111827", "surface2": "#161f31",
             "surface3": "#1d2739", "border": "#243049", "text": "#f1f5f9",
             "text2": "#a3b1c6", "text3": "#64748b", "primary": "#f8fafc",
             "onPrimary": "#0f172a"}
    else:
        c = {"bg": "#f4f6f9", "surface": "#ffffff", "surface2": "#f8fafc",
             "surface3": "#eef2f7", "border": "#e5e9f0", "text": "#0f172a",
             "text2": "#475569", "text3": "#94a3b8", "primary": "#0f172a",
             "onPrimary": "#ffffff"}
    return f"""
    * {{ font-family: 'Inter','Segoe UI','Helvetica Neue','Noto Color Emoji','Apple Color Emoji',sans-serif; }}
    QMainWindow, QDialog, QWidget#root {{ background:{c['bg']}; color:{c['text']}; }}
    QWidget {{ color:{c['text']}; }}
    QLabel {{ color:{c['text']}; background: transparent; }}
    QLabel#muted  {{ color:{c['text2']}; }}
    QLabel#faint  {{ color:{c['text3']}; }}
    QLabel#h1 {{ font-size:18px; font-weight:800; letter-spacing:-0.3px; }}
    QLabel#h2 {{ font-size:14px; font-weight:700; }}
    QLabel#h3 {{ font-size:12px; font-weight:700; color:{c['text2']}; }}

    QFrame#card, QFrame#sidebar, QFrame#topbar, QFrame#orderPanel {{
        background:{c['surface']}; border:1px solid {c['border']};
        border-radius:16px;
    }}
    QFrame#sidebar {{ border-radius:0; border-top:none; border-bottom:none; border-left:none; }}
    QFrame#topbar  {{ border-radius:0; border-top:none; border-left:none; border-right:none; }}
    QFrame#sep {{ background:{c['border']}; max-height:1px; min-height:1px; border:none; }}

    QPushButton {{
        background:{c['surface2']}; color:{c['text']};
        border:1px solid {c['border']}; border-radius:10px;
        padding:7px 14px; font-size:12px; font-weight:600;
    }}
    QPushButton:hover {{ background:{c['surface3']}; }}
    QPushButton:pressed {{ padding-top:8px; padding-bottom:6px; }}
    QPushButton:disabled {{ color:{c['text3']}; }}
    QPushButton#primary {{ background:{c['primary']}; color:{c['onPrimary']}; border:none; }}
    QPushButton#primary:hover {{ background:{c['primary']}; }}
    QPushButton#success {{ background:#16a34a; color:white; border:none; }}
    QPushButton#danger  {{ background:#ef4444; color:white; border:none; }}
    QPushButton#warn    {{ background:#f59e0b; color:white; border:none; }}
    QPushButton#ghost   {{ background:transparent; border:1px solid {c['border']}; }}
    QPushButton#chip {{
        background:{c['surface']}; border:1px solid {c['border']};
        border-radius:16px; padding:6px 14px; font-weight:600; color:{c['text2']};
    }}
    QPushButton#chip:hover {{ background:{c['surface2']}; }}
    QPushButton#chip:checked {{
        background:{c['primary']}; color:{c['onPrimary']}; border-color:{c['primary']};
    }}
    QPushButton#navItem {{
        background:transparent; border:none; border-radius:12px;
        font-size:20px; padding:0; color:{c['text3']};
    }}
    QPushButton#navItem:hover {{ background:{c['surface2']}; color:{c['text']}; }}
    QPushButton#navItem:checked {{ background:{c['primary']}; color:{c['onPrimary']}; }}
    QPushButton#iconBtn {{
        background:{c['surface2']}; border:1px solid {c['border']};
        border-radius:8px; padding:4px 8px; font-size:11px;
    }}

    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTextEdit {{
        background:{c['surface2']}; border:1px solid {c['border']};
        border-radius:9px; padding:6px 10px; font-size:12px;
        color:{c['text']}; selection-background-color:{c['primary']};
        selection-color:{c['onPrimary']};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QDateEdit:focus, QTextEdit:focus {{ border:1px solid {c['primary']}; }}
    QComboBox::drop-down {{ border:none; width:18px; }}
    QComboBox QAbstractItemView {{
        background:{c['surface']}; color:{c['text']};
        border:1px solid {c['border']}; border-radius:8px;
        selection-background-color:{c['primary']};
        selection-color:{c['onPrimary']};
    }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width:14px; }}

    QCheckBox {{ color:{c['text']}; font-size:12px; }}
    QCheckBox::indicator {{
        width:16px; height:16px; border:1px solid {c['border']};
        border-radius:4px; background:{c['surface2']};
    }}
    QCheckBox::indicator:checked {{ background:{c['primary']}; }}

    QTableWidget {{
        background:{c['surface']}; border:1px solid {c['border']};
        border-radius:12px; gridline-color:{c['border']};
        font-size:12px; color:{c['text']};
    }}
    QTableWidget::item {{ padding:6px 8px; }}
    QTableWidget::item:selected {{ background:{c['surface3']}; color:{c['text']}; }}
    QHeaderView::section {{
        background:{c['surface2']}; color:{c['text2']};
        padding:8px; border:none; border-bottom:1px solid {c['border']};
        font-size:11px; font-weight:700;
    }}

    QScrollArea {{ background:transparent; border:none; }}
    QScrollArea > QWidget > QWidget {{ background:transparent; }}

    QScrollBar:vertical {{ background:transparent; width:8px; margin:0; }}
    QScrollBar::handle:vertical {{
        background:{c['border']}; border-radius:4px; min-height:30px;
    }}
    QScrollBar::handle:vertical:hover {{ background:{c['text3']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}

    QToolTip {{
        background:{c['text']}; color:{c['bg']};
        border:none; padding:4px 8px; border-radius:6px; font-size:11px;
    }}

    QLabel#toast {{
        background:{c['surface']}; color:{c['text']};
        border:1px solid {c['border']}; border-left:3px solid {c['primary']};
        border-radius:12px; padding:10px 14px; font-size:12px; font-weight:600;
    }}
    QLabel#toast[ok="1"]   {{ border-left:3px solid #16a34a; }}
    QLabel#toast[err="1"]  {{ border-left:3px solid #ef4444; }}
    QLabel#toast[warn="1"] {{ border-left:3px solid #f59e0b; }}

    QLabel#productEmoji {{ font-size:26px; }}
    QFrame#productCard {{
        background:{c['surface']}; border:1px solid {c['border']};
        border-radius:14px;
    }}
    QFrame#productCard:hover {{ border:1px solid {c['text3']}; }}

    QFrame#lineItem {{ border-bottom:1px solid {c['border']}; }}

    QFrame#sizeBox {{
        background:{c['surface2']}; border:1px dashed {c['border']};
        border-radius:10px;
    }}
    QTextEdit#receipt {{
        font-family: 'Courier New', monospace;
        font-size: 12px;
    }}
    """


# ════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════
def fmt_money(v, sym="LBP "):
    try:    return f"{sym}{float(v):,.0f}"
    except Exception: return f"{sym}0"


def fmt_money_secondary(v, settings):
    try:    fv = float(v)
    except Exception: fv = 0.0
    sec = settings.get("secondary_currency", "USD") or "USD"
    sec_sym = "$" if sec.upper() == "USD" else (sec + " ")
    try:
        rate = float(settings.get("secondary_rate", "90000") or 90000)
    except (TypeError, ValueError):
        rate = 90000.0
    usd = fv / rate if rate else 0.0
    return f"{sec_sym}{usd:,.2f}"


def fmt_money_dual(v, settings):
    sym = settings.get("currency_symbol", "LBP ")
    return f"{fmt_money(v, sym)}  ({fmt_money_secondary(v, settings)})"


def _parse_opts_str(s):
    if not s: return []
    return [{"label": p.strip()} for p in s.split(",") if p.strip()]


def _compute_unit_price(product, chosen_options):
    """Return the unit price for a product with its chosen options.

    Special rule:  any Large pizza with 'Chicken BBQ' involved
    (either as the product itself or as one of the two chosen flavors)
    is charged CHICKEN_BBQ_LARGE_PRICE (1,200,000).
    """
    base = float(product.get("price", 0) or 0)
    total = base + sum(float(o.get("price", 0) or 0) for o in chosen_options)

    labels = {str(o.get("label", "")).strip().lower() for o in chosen_options}
    product_name = str(product.get("name", "")).lower()

    is_large  = "large" in labels
    has_bbq_flavor = any(("bbq" in l) or ("barbecue" in l) for l in labels)
    product_is_bbq = ("bbq" in product_name) or ("barbecue" in product_name)

    if is_large and (has_bbq_flavor or product_is_bbq):
        total = CHICKEN_BBQ_LARGE_PRICE
    return total


class Toast(QLabel):
    _stack = []

    def __init__(self, parent, text, kind="info", ms=2600):
        super().__init__(text, parent)
        self.setObjectName("toast")
        self.setProperty("ok",   "1" if kind == "success" else "0")
        self.setProperty("err",  "1" if kind == "error"   else "0")
        self.setProperty("warn", "1" if kind == "warning" else "0")
        self.setStyleSheet(build_qss(QApplication.instance().property("theme") or "light"))
        self.adjustSize()
        self.setMinimumWidth(220)
        self.show(); self.raise_()
        Toast._stack.append(self)
        self._reflow()
        QTimer.singleShot(ms, self._dismiss)

    def _reflow(self):
        p = self.parent()
        if not p: return
        x = p.width() - self.width() - 20
        y = p.height() - 20
        for t in reversed(Toast._stack):
            if not t.isVisible(): continue
            y -= t.height() + 8
            t.move(x, y)

    def _dismiss(self):
        if self in Toast._stack:
            Toast._stack.remove(self)
        self.deleteLater()
        for t in Toast._stack:
            t._reflow()


def info(parent, msg, title="Notice"): QMessageBox.information(parent, title, msg)
def warn(parent, msg, title="Warning"): QMessageBox.warning(parent, title, msg)
def confirm(parent, msg, title="Confirm"):
    return QMessageBox.question(parent, title, msg,
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes


# ════════════════════════════════════════════════════════════════
#  PRODUCT CARD
# ════════════════════════════════════════════════════════════════
class ProductCard(QFrame):
    clicked = pyqtSignal(dict)

    def __init__(self, product, sym="LBP "):
        super().__init__()
        self.setObjectName("productCard")
        product = dict(product)
        self.product = product
        self.sym = sym
        self.setFixedHeight(120)
        self.setCursor(Qt.PointingHandCursor)
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 10, 8, 8); v.setSpacing(2)

        emoji = QLabel(product.get("emoji") or "🍕")
        emoji.setObjectName("productEmoji")
        emoji.setAlignment(Qt.AlignCenter)
        v.addWidget(emoji)

        nm = QLabel(product.get("name", ""))
        nm.setAlignment(Qt.AlignCenter)
        nm.setWordWrap(True)
        nm.setStyleSheet("font-weight:600; font-size:11px;")
        v.addWidget(nm)

        if product.get("track_stock") and product.get("stock", 0) <= product.get("low_stock", 5):
            badge = QLabel(f"● {int(product['stock'])}")
            badge.setStyleSheet("color:#ef4444; font-size:9px; font-weight:700;")
            badge.setAlignment(Qt.AlignCenter)
            v.addWidget(badge)

    def mousePressEvent(self, ev):
        self.clicked.emit(self.product)
        super().mousePressEvent(ev)


# ════════════════════════════════════════════════════════════════
#  DIALOGS
# ════════════════════════════════════════════════════════════════
class LoginDialog(QDialog):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.user = None
        self.setWindowTitle("Pizza POS — Login")
        self.setFixedSize(420, 480)
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)

        v = QVBoxLayout(self); v.setContentsMargins(40, 40, 40, 30); v.setSpacing(14)
        v.addSpacing(10)

        logo = QLabel("🍕"); logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("font-size:60px;")
        v.addWidget(logo)

        title = QLabel("Pizza POS"); title.setObjectName("h1")
        title.setAlignment(Qt.AlignCenter)
        v.addWidget(title)

        sub = QLabel("Restaurant Management Suite")
        sub.setObjectName("faint"); sub.setAlignment(Qt.AlignCenter)
        v.addWidget(sub)
        v.addSpacing(20)

        self.user_in = QLineEdit(); self.user_in.setPlaceholderText("Username")
        self.user_in.setText("admin")
        v.addWidget(self.user_in)

        self.pw_in = QLineEdit(); self.pw_in.setPlaceholderText("Password")
        self.pw_in.setEchoMode(QLineEdit.Password)
        self.pw_in.setText("admin123")
        self.pw_in.returnPressed.connect(self.try_login)
        v.addWidget(self.pw_in)

        self.err = QLabel(""); self.err.setStyleSheet("color:#ef4444; font-size:11px;")
        self.err.setAlignment(Qt.AlignCenter)
        v.addWidget(self.err)

        btn = QPushButton("Sign In"); btn.setObjectName("primary")
        btn.setMinimumHeight(40)
        btn.clicked.connect(self.try_login)
        v.addWidget(btn)

        hint = QLabel("Default: admin / admin123")
        hint.setObjectName("faint"); hint.setAlignment(Qt.AlignCenter)
        v.addWidget(hint)
        v.addStretch()

    def try_login(self):
        u = self.user_in.text().strip()
        p = self.pw_in.text()
        if not u or not p:
            self.err.setText("Enter username and password"); return
        user = self.db.authenticate(u, p)
        if not user:
            self.err.setText("Invalid credentials"); return
        self.user = user
        self.accept()


class OptionDialog(QDialog):
    def __init__(self, parent, product, options, sym="LBP "):
        super().__init__(parent)
        product = dict(product)
        self.product = product
        self.sym = sym
        self.setWindowTitle(product.get("name", ""))
        self.setMinimumWidth(480)
        self.result_data = None

        v = QVBoxLayout(self); v.setContentsMargins(20, 20, 20, 20); v.setSpacing(12)

        hdr = QHBoxLayout()
        em = QLabel(product.get("emoji") or "🍕"); em.setStyleSheet("font-size:34px;")
        hdr.addWidget(em)
        col = QVBoxLayout()
        nm = QLabel(product.get("name", "")); nm.setObjectName("h2")
        col.addWidget(nm)
        hdr.addLayout(col); hdr.addStretch()
        v.addLayout(hdr)

        self.groups = []

        for grp in options:
            container = QWidget()
            cv = QVBoxLayout(container)
            cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(4)

            g = QLabel(grp["name"]); g.setObjectName("h3")
            cv.addWidget(g)

            chips = QGridLayout(); chips.setSpacing(6)
            chips.setContentsMargins(0, 0, 0, 0)
            btns = []
            for i, ch in enumerate(grp["choices"]):
                txt = ch["label"]
                if ch["price"]:
                    sign = "+" if ch["price"] > 0 else ""
                    txt += f"  {sign}{fmt_money(ch['price'], sym)}"
                b = QPushButton(txt)
                b.setObjectName("chip"); b.setCheckable(True)
                if not grp.get("multi"):
                    b.setAutoExclusive(True)
                chips.addWidget(b, i // 3, i % 3)
                btns.append((b, ch))
            cv.addLayout(chips)
            v.addWidget(container)

            gd = {"grp": grp, "btns": btns, "container": container}
            self.groups.append(gd)

            if btns:
                if not grp.get("multi"):
                    btns[0][0].setChecked(True)
                if grp.get("max_choices"):
                    for b, ch in btns:
                        b.toggled.connect(
                            lambda checked, g=gd, bb=b: self._enforce_max(g, bb))
            if grp.get("name") == "Size":
                for b, ch in btns:
                    b.toggled.connect(self._update_large_only_visibility)

        self._update_large_only_visibility()

        v.addSpacing(4)
        self.qty = QSpinBox(); self.qty.setRange(1, 99); self.qty.setValue(1)
        qrow = QHBoxLayout()
        qrow.addWidget(QLabel("Quantity"))
        qrow.addWidget(self.qty)
        qrow.addStretch()
        v.addLayout(qrow)

        foot = QHBoxLayout()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        ok = QPushButton("Add to Order"); ok.setObjectName("primary")
        ok.clicked.connect(self._accept)
        foot.addWidget(cancel); foot.addWidget(ok)
        v.addLayout(foot)

    def _size_is_large(self):
        for gd in self.groups:
            if gd["grp"].get("name") == "Size":
                for b, ch in gd["btns"]:
                    if b.isChecked() and str(ch["label"]).strip().lower() == "large":
                        return True
        return False

    def _update_large_only_visibility(self, *_):
        is_large = self._size_is_large()
        for gd in self.groups:
            if gd["grp"].get("large_only"):
                gd["container"].setVisible(is_large)
                if not is_large:
                    for b, ch in gd["btns"]:
                        if b.isChecked():
                            b.setChecked(False)
        try: self.adjustSize()
        except Exception: pass

    def _enforce_max(self, gd, just_clicked):
        if not just_clicked.isChecked(): return
        try:
            max_n = int(gd["grp"].get("max_choices", 0) or 0)
        except (TypeError, ValueError):
            max_n = 0
        if max_n <= 0: return
        checked = [b for b, ch in gd["btns"] if b.isChecked()]
        if len(checked) > max_n:
            for b in checked:
                if b is not just_clicked:
                    b.setChecked(False); break

    def _accept(self):
        chosen = []
        for gd in self.groups:
            if not gd["container"].isVisible():
                continue
            grp = gd["grp"]
            for b, ch in gd["btns"]:
                if b.isChecked():
                    chosen.append({"group": grp["name"], "label": ch["label"],
                                   "price": float(ch["price"])})
                    if not grp.get("multi"):
                        break
        # Large pizza → require exactly 2 flavors
        if self._size_is_large():
            flavors = [c for c in chosen if c["group"] == "Flavor"]
            if len(flavors) != 2:
                warn(self, "Please choose exactly 2 flavors for a Large pizza.")
                return
        self.result_data = {"options": chosen, "qty": self.qty.value()}
        self.accept()


class PaymentDialog(QDialog):
    def __init__(self, parent, total, settings):
        super().__init__(parent)
        self.setWindowTitle("Payment")
        self.setFixedWidth(400)
        self.method = "Cash"; self.tendered = 0.0
        self.total = total; self.settings = settings

        v = QVBoxLayout(self); v.setContentsMargins(22, 22, 22, 20); v.setSpacing(12)

        t = QLabel("Take Payment"); t.setObjectName("h1"); v.addWidget(t)
        tot = QLabel(f"Total: {fmt_money_dual(total, settings)}")
        tot.setObjectName("h2"); v.addWidget(tot)
        v.addSpacing(4)

        m = QLabel("Payment method: Cash"); m.setObjectName("h3"); v.addWidget(m)

        c = QLabel("Amount tendered (cash, LBP)"); c.setObjectName("h3"); v.addWidget(c)
        self.cash_in = QLineEdit(); self.cash_in.setPlaceholderText("0")
        self.cash_in.textChanged.connect(self._update_change)
        v.addWidget(self.cash_in)

        self.change_lbl = QLabel("Change: —")
        self.change_lbl.setObjectName("muted"); v.addWidget(self.change_lbl)

        v.addSpacing(6)
        foot = QHBoxLayout()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        ok = QPushButton("Confirm Payment"); ok.setObjectName("success")
        ok.clicked.connect(self._accept)
        foot.addWidget(cancel); foot.addWidget(ok)
        v.addLayout(foot)

        self.cash_in.setText(f"{int(round(total))}")

    def _update_change(self):
        try: v = float(self.cash_in.text() or 0)
        except ValueError:
            self.change_lbl.setText("Change: —"); return
        ch = v - self.total
        if ch >= 0:
            self.change_lbl.setText(f"Change: {fmt_money_dual(ch, self.settings)}")
        else:
            self.change_lbl.setText("Insufficient cash")

    def _accept(self):
        try: self.tendered = float(self.cash_in.text() or 0)
        except ValueError:
            warn(self, "Enter valid cash amount"); return
        if self.tendered < self.total:
            warn(self, "Cash tendered is less than total"); return
        self.accept()


class ReceiptDialog(QDialog):
    def __init__(self, parent, receipt_text, printer_name="",
                 order=None, settings=None):
        super().__init__(parent)
        self.setWindowTitle("Receipt")
        self.setMinimumSize(520, 640)
        self.receipt_text = receipt_text
        self.printer_name = printer_name
        self.order = order
        self.settings = settings

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20); v.setSpacing(10)

        t = QLabel("🧾  Receipt (customer copy shown)"); t.setObjectName("h1")
        v.addWidget(t)

        text = QTextEdit(); text.setObjectName("receipt"); text.setReadOnly(True)
        text.setFont(QFont("Courier New", 11))
        text.setPlainText(receipt_text)
        v.addWidget(text, 1)

        row = QHBoxLayout()
        status = QLabel(""); status.setObjectName("muted")
        row.addWidget(status); row.addStretch()

        if printer_name:
            pb = QPushButton("🖨  Print 2 copies"); pb.setObjectName("success")
            pb.clicked.connect(lambda: self._print(status))
            row.addWidget(pb)

        close = QPushButton("Close"); close.setObjectName("primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        v.addLayout(row)

    def _print(self, status_lbl):
        try:
            if self.order and self.settings:
                print_receipt_two_copies_local(self.printer_name,
                                               self.order, self.settings)
            else:
                print_receipt_local(self.printer_name, self.receipt_text)
            status_lbl.setText("Sent to printer (2 copies).")
            Toast(self.window(), "Sent to printer (2 copies)", "success")
        except Exception as e:
            status_lbl.setText("")
            warn(self, f"Printer error:\n{e}")


class ProductDialog(QDialog):
    def __init__(self, parent, db, product=None):
        super().__init__(parent)
        self.db = db
        self.product = dict(product) if product else None
        self.setWindowTitle("Edit Product" if self.product else "New Product")
        self.setMinimumWidth(520)
        self.sym = db.get_setting("currency_symbol", "LBP ")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        host = QWidget(); scroll.setWidget(host)
        v = QVBoxLayout(host); v.setContentsMargins(22, 22, 22, 20); v.setSpacing(12)

        t = QLabel("Edit Product" if self.product else "New Product"); t.setObjectName("h1")
        v.addWidget(t); v.addSpacing(4)

        form = QFormLayout(); form.setSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.name_in = QLineEdit(self.product["name"] if self.product else "")
        self.emoji_in = QLineEdit(self.product["emoji"] if self.product else "🍕")
        self.cat_cb = QComboBox()
        self.cat_cb.addItem("— none —", None)
        for c in db.categories():
            self.cat_cb.addItem(c["name"], c["id"])
        if self.product and self.product["category_id"]:
            idx = self.cat_cb.findData(self.product["category_id"])
            if idx >= 0: self.cat_cb.setCurrentIndex(idx)

        self.price_in = QDoubleSpinBox()
        self.price_in.setRange(0, 9_999_999_999); self.price_in.setDecimals(0)
        self.price_in.setSingleStep(50_000); self.price_in.setPrefix(self.sym)
        self.price_in.setValue(self.product["price"] if self.product else 0)

        self.cost_in = QDoubleSpinBox()
        self.cost_in.setRange(0, 9_999_999_999); self.cost_in.setDecimals(0)
        self.cost_in.setSingleStep(50_000); self.cost_in.setPrefix(self.sym)
        self.cost_in.setValue(self.product["cost"] if self.product else 0)

        self.stock_in = QDoubleSpinBox()
        self.stock_in.setRange(-99_999_999, 99_999_999); self.stock_in.setDecimals(0)
        self.stock_in.setValue(self.product["stock"] if self.product else 0)

        self.low_in = QDoubleSpinBox()
        self.low_in.setRange(0, 99_999_999); self.low_in.setDecimals(0)
        self.low_in.setValue(self.product["low_stock"] if self.product else 5)

        self.track_cb = QCheckBox("Track stock")
        self.track_cb.setChecked(bool(self.product["track_stock"]) if self.product else False)

        self.opts_cb  = QCheckBox("Has options")
        self.opts_cb.setChecked(bool(self.product["has_options"]) if self.product else False)
        self.active_cb = QCheckBox("Active")
        self.active_cb.setChecked(bool(self.product["active"]) if self.product else True)

        form.addRow("Name", self.name_in)
        form.addRow("Emoji", self.emoji_in)
        form.addRow("Category", self.cat_cb)
        form.addRow("Price", self.price_in)
        form.addRow("Cost", self.cost_in)
        form.addRow("Stock", self.stock_in)
        form.addRow("Low stock", self.low_in)
        form.addRow("", self.track_cb)
        form.addRow("", self.opts_cb)
        form.addRow("", self.active_cb)
        v.addLayout(form)

        co_title = QLabel("Custom options (JSON) — overrides global options")
        co_title.setObjectName("h3")
        v.addWidget(co_title)

        co_hint = QLabel(
            'Example: [{"name":"Size","multi":false,"choices":'
            '[{"label":"Small","price":300000},'
            '{"label":"Medium","price":400000}]}]'
        )
        co_hint.setObjectName("faint"); co_hint.setWordWrap(True)
        co_hint.setStyleSheet("font-size:10px;")
        v.addWidget(co_hint)

        self.custom_opts_edit = QTextEdit()
        self.custom_opts_edit.setMinimumHeight(120)
        self.custom_opts_edit.setPlaceholderText("Leave empty to use global options")
        if self.product and (self.product.get("custom_options") or "").strip():
            self.custom_opts_edit.setPlainText(self.product.get("custom_options"))
        v.addWidget(self.custom_opts_edit)

        v.addStretch(1)
        foot = QHBoxLayout()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        ok = QPushButton("Save"); ok.setObjectName("primary")
        ok.clicked.connect(self._save)
        foot.addStretch(); foot.addWidget(cancel); foot.addWidget(ok)
        v.addLayout(foot)

    def _save(self):
        if not self.name_in.text().strip():
            warn(self, "Name is required"); return

        custom_options = self.custom_opts_edit.toPlainText().strip()
        if custom_options:
            try:
                parsed = json.loads(custom_options)
                if not isinstance(parsed, list):
                    raise ValueError("Custom options must be a JSON array")
            except Exception as e:
                warn(self, f"Custom options JSON is invalid:\n{e}"); return
            custom_options = json.dumps(parsed)

        data = {
            "name": self.name_in.text().strip(),
            "emoji": self.emoji_in.text().strip() or "🍕",
            "category_id": self.cat_cb.currentData(),
            "price": self.price_in.value(),
            "cost": self.cost_in.value(),
            "stock": self.stock_in.value(),
            "track_stock": 1 if self.track_cb.isChecked() else 0,
            "low_stock": self.low_in.value(),
            "has_options": 1 if self.opts_cb.isChecked() else 0,
            "active": 1 if self.active_cb.isChecked() else 0,
            "size_prices": "",
            "custom_options": custom_options,
        }
        pid = self.product["id"] if self.product else None
        self.db.save_product(data, pid)
        self.accept()


class CustomerDialog(QDialog):
    def __init__(self, parent, db, customer=None):
        super().__init__(parent)
        self.db = db
        self.customer = dict(customer) if customer else None
        self.setWindowTitle("Edit Customer" if self.customer else "New Customer")
        self.setMinimumWidth(400)

        v = QVBoxLayout(self); v.setContentsMargins(22, 22, 22, 20); v.setSpacing(10)
        t = QLabel("Edit Customer" if self.customer else "New Customer"); t.setObjectName("h1")
        v.addWidget(t); v.addSpacing(6)

        form = QFormLayout(); form.setSpacing(8)
        self.name_in = QLineEdit(self.customer["name"] if self.customer else "")
        self.phone_in = QLineEdit(self.customer["phone"] if self.customer else "")
        self.addr_in = QLineEdit(self.customer["address"] if self.customer else "")
        form.addRow("Name", self.name_in)
        form.addRow("Phone", self.phone_in)
        form.addRow("Address", self.addr_in)
        v.addLayout(form)

        foot = QHBoxLayout()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        ok = QPushButton("Save"); ok.setObjectName("primary")
        ok.clicked.connect(self._save)
        foot.addWidget(cancel); foot.addWidget(ok)
        v.addLayout(foot)

    def _save(self):
        if not self.name_in.text().strip():
            warn(self, "Name is required"); return
        pts = int(self.customer["points"]) if self.customer else 0
        data = {"name": self.name_in.text().strip(),
                "phone": self.phone_in.text().strip(),
                "address": self.addr_in.text().strip(),
                "points": pts}
        cid = self.customer["id"] if self.customer else None
        self.db.save_customer(data, cid)
        self.accept()


class ExpenseDialog(QDialog):
    def __init__(self, parent, db, expense=None):
        super().__init__(parent)
        self.db = db
        self.expense = dict(expense) if expense else None
        self.setWindowTitle("Edit Expense" if self.expense else "New Expense")
        self.setMinimumWidth(400)
        sym = db.get_setting("currency_symbol", "LBP ")

        v = QVBoxLayout(self); v.setContentsMargins(22, 22, 22, 20); v.setSpacing(10)
        t = QLabel("Edit Expense" if self.expense else "New Expense"); t.setObjectName("h1")
        v.addWidget(t); v.addSpacing(6)

        form = QFormLayout(); form.setSpacing(8)
        self.cat_in = QComboBox(); self.cat_in.setEditable(True)
        for c in ["General", "Ingredients", "Rent", "Utilities", "Salaries",
                  "Marketing", "Maintenance", "Other"]:
            self.cat_in.addItem(c)
        if self.expense: self.cat_in.setCurrentText(self.expense["category"])
        self.desc_in = QLineEdit(self.expense["description"] if self.expense else "")
        self.amt_in = QDoubleSpinBox()
        self.amt_in.setRange(0, 9_999_999_999); self.amt_in.setDecimals(0)
        self.amt_in.setSingleStep(50_000); self.amt_in.setPrefix(sym)
        self.amt_in.setValue(self.expense["amount"] if self.expense else 0)
        self.date_in = QDateEdit(); self.date_in.setCalendarPopup(True)
        self.date_in.setDate(QDate.fromString(self.expense["spent_on"], "yyyy-MM-dd")
                             if self.expense else QDate.currentDate())
        self.date_in.setDisplayFormat("yyyy-MM-dd")
        form.addRow("Category", self.cat_in)
        form.addRow("Description", self.desc_in)
        form.addRow("Amount", self.amt_in)
        form.addRow("Date", self.date_in)
        v.addLayout(form)

        foot = QHBoxLayout()
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        ok = QPushButton("Save"); ok.setObjectName("primary")
        ok.clicked.connect(self._save)
        foot.addWidget(cancel); foot.addWidget(ok)
        v.addLayout(foot)

    def _save(self):
        data = {"category": self.cat_in.currentText().strip() or "General",
                "description": self.desc_in.text().strip(),
                "amount": self.amt_in.value(),
                "spent_on": self.date_in.date().toString("yyyy-MM-dd")}
        eid = self.expense["id"] if self.expense else None
        self.db.save_expense(data, eid)
        self.accept()


# ════════════════════════════════════════════════════════════════
#  CLOUD SYNC HELPER
# ════════════════════════════════════════════════════════════════
class CloudSync:
    def __init__(self, db):
        self.db = db
        self.client = FirebaseSync(FIREBASE_CONFIG)

    def enabled(self):
        return self.db.get_setting("firebase_enabled", "0") == "1"

    def _collection(self, key, default):
        return (self.db.get_setting(key, default) or default).strip() or default

    def push_order(self, order_snapshot):
        if not self.enabled(): return False, "disabled"
        doc = {
            "order_no":    order_snapshot.get("no"),
            "order_type":  order_snapshot.get("type"),
            "customer":    order_snapshot.get("customer_name", ""),
            "customer_id": order_snapshot.get("customer_id"),
            "subtotal":    float(order_snapshot.get("subtotal", 0)),
            "discount":    float(order_snapshot.get("discount", 0)),
            "delivery":    float(order_snapshot.get("delivery", 0)),
            "total":       float(order_snapshot.get("total", 0)),
            "currency":    self.db.get_setting("currency_symbol", "LBP ").strip(),
            "payment":     order_snapshot.get("payment_method", "Cash"),
            "created_at":  datetime.now().isoformat(timespec="seconds"),
            "items":       [
                {
                    "name":     i.get("name", ""),
                    "qty":      float(i.get("qty", 1) or 1),
                    "unit":     float(i.get("unit", 0) or 0),
                    "line":     float(i.get("line", 0) or 0),
                    "options":  [o.get("label", "") for o in i.get("options", [])],
                }
                for i in order_snapshot.get("items", [])
            ],
        }
        return self.client.push_document(self._collection(
            "firebase_collection_orders", "orders"), doc)

    def push_customer(self, customer):
        if not self.enabled(): return False, "disabled"
        doc = {
            "name":       customer.get("name", ""),
            "phone":      customer.get("phone", ""),
            "address":    customer.get("address", ""),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        return self.client.push_document(self._collection(
            "firebase_collection_customers", "customers"), doc)

    def push_close_cash(self, start, end):
        if not self.enabled(): return False, "disabled"
        cash = self.db.cash_summary(start, end)
        doc = {
            "from":         start,
            "to":           end,
            "cash_orders":  cash["cash_orders"],
            "cash_sales":   float(cash["cash_sales"]),
            "expenses":     float(cash["expenses"]),
            "expected":     float(cash["expected"]),
            "currency":     self.db.get_setting("currency_symbol", "LBP ").strip(),
            "created_at":   datetime.now().isoformat(timespec="seconds"),
        }
        return self.client.push_document(self._collection(
            "firebase_collection_cash", "close_cash"), doc)


# ════════════════════════════════════════════════════════════════
#  POS PAGE
# ════════════════════════════════════════════════════════════════
class POSPage(QWidget):
    def __init__(self, db, user):
        super().__init__()
        self.db = db; self.user = user
        self.current_order = None
        self.open_orders = []
        self.current_cat = None
        self._cat_btns = []
        self.cloud = CloudSync(db)
        self._build()
        self.refresh_categories()
        self.refresh_products()
        self.reload_customers()
        self.reload_open_orders()
        self.new_order(silent=True)

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14); root.setSpacing(14)

        left = QVBoxLayout(); left.setSpacing(10)

        srow = QHBoxLayout(); srow.setSpacing(8)
        self.search = QLineEdit(); self.search.setPlaceholderText("🔍  Search menu…")
        self.search.textChanged.connect(self.refresh_products)
        srow.addWidget(self.search, 1)
        left.addLayout(srow)

        self.cat_bar = QHBoxLayout(); self.cat_bar.setSpacing(6)
        cat_wrap = QWidget(); cat_wrap.setLayout(self.cat_bar)
        left.addWidget(cat_wrap)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(8); self.grid.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid_host)
        scroll.setFrameShape(QFrame.NoFrame)
        left.addWidget(scroll, 1)

        right = QFrame(); right.setObjectName("card")
        right.setFixedWidth(440)
        rv = QVBoxLayout(right); rv.setContentsMargins(14, 14, 14, 14); rv.setSpacing(10)

        self.tabs_bar = QHBoxLayout(); self.tabs_bar.setSpacing(6)
        tabs_wrap = QWidget(); tabs_wrap.setLayout(self.tabs_bar)
        rv.addWidget(tabs_wrap)

        h = QHBoxLayout()
        self.order_lbl = QLabel("New Order"); self.order_lbl.setObjectName("h2")
        h.addWidget(self.order_lbl); h.addStretch()
        rv.addLayout(h)

        tinfo = QLabel("Type: Delivery"); tinfo.setObjectName("h3")
        rv.addWidget(tinfo)

        # ── Customer picker (autocomplete dropdown) ─────────────
        cust_row = QHBoxLayout(); cust_row.setSpacing(6)
        cust_row.addWidget(QLabel("👤"))
        self.cust_cb = QComboBox()
        self.cust_cb.setEditable(True)
        self.cust_cb.setInsertPolicy(QComboBox.NoInsert)
        self.cust_cb.setMinimumHeight(32)
        self.cust_cb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        le = self.cust_cb.lineEdit()
        if le:
            le.setPlaceholderText("Customer (optional) — type or select…")
        self.cust_cb.setToolTip(
            "Pick an existing customer,\ntype a free-text name, or leave blank.")
        try:
            comp = QCompleter(self.cust_cb.model(), self.cust_cb)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            comp.setFilterMode(Qt.MatchContains)
            comp.setCompletionMode(QCompleter.PopupCompletion)
            self.cust_cb.setCompleter(comp)
        except Exception:
            pass
        cust_row.addWidget(self.cust_cb, 1)
        rv.addLayout(cust_row)

        self.items_host = QWidget()
        self.items_layout = QVBoxLayout(self.items_host)
        self.items_layout.setContentsMargins(0, 0, 0, 0); self.items_layout.setSpacing(0)
        self.items_layout.addStretch()
        items_scroll = QScrollArea(); items_scroll.setWidgetResizable(True)
        items_scroll.setWidget(self.items_host)
        items_scroll.setFrameShape(QFrame.NoFrame)
        items_scroll.setMinimumHeight(160)
        rv.addWidget(items_scroll, 1)

        tot_box = QFrame(); tot_box.setObjectName("card")
        tv = QVBoxLayout(tot_box); tv.setContentsMargins(10, 10, 10, 10); tv.setSpacing(2)
        self.sub_lbl  = self._total_row(tv, "Subtotal", "0")
        self.disc_row, self.disc_in = self._total_row_edit(tv, "Discount", "0")
        self.del_lbl  = self._total_row(tv, "Delivery", "0")
        sep = QFrame(); sep.setObjectName("sep"); tv.addWidget(sep)
        g = QHBoxLayout()
        gl = QLabel("Total"); gl.setStyleSheet("font-size:15px; font-weight:800;")
        self.grand_lbl = QLabel("LBP 0")
        self.grand_lbl.setStyleSheet("font-size:15px; font-weight:800;")
        self.grand_lbl.setAlignment(Qt.AlignRight)
        g.addWidget(gl); g.addWidget(self.grand_lbl)
        tv.addLayout(g)
        rv.addWidget(tot_box)

        act = QHBoxLayout(); act.setSpacing(6)
        clear = QPushButton("Clear"); clear.setObjectName("ghost")
        clear.clicked.connect(self.clear_order)
        hold = QPushButton("Hold"); hold.clicked.connect(self.hold_order)
        act.addWidget(clear); act.addWidget(hold)
        rv.addLayout(act)

        pay = QPushButton("💵  Pay (Cash)"); pay.setObjectName("success")
        pay.setMinimumHeight(42); pay.clicked.connect(self.pay_order)
        rv.addWidget(pay)

        root.addLayout(left, 1)
        root.addWidget(right)

        self.disc_in.textChanged.connect(self.recalc)

    def _total_row(self, layout, label, value):
        h = QHBoxLayout()
        l = QLabel(label); l.setObjectName("muted"); l.setStyleSheet("font-size:12px;")
        v = QLabel(value); v.setAlignment(Qt.AlignRight)
        v.setStyleSheet("font-size:12px; font-weight:600;")
        h.addWidget(l); h.addStretch(); h.addWidget(v)
        layout.addLayout(h)
        return v

    def _total_row_edit(self, layout, label, placeholder):
        h = QHBoxLayout()
        l = QLabel(label); l.setObjectName("muted"); l.setStyleSheet("font-size:12px;")
        e = QLineEdit(); e.setPlaceholderText(placeholder); e.setFixedWidth(110)
        e.setValidator(QDoubleValidator(0, 999_999_999, 0))
        h.addWidget(l); h.addStretch(); h.addWidget(e)
        layout.addLayout(h)
        return h, e

    # ---------- customers ----------
    def reload_customers(self):
        prev_text = ""
        try:
            prev_text = self.cust_cb.currentText().strip()
        except Exception:
            pass
        self.cust_cb.blockSignals(True)
        self.cust_cb.clear()
        self.cust_cb.addItem("— Walk-in / No customer —", None)
        for c in self.db.customers():
            c = dict(c)
            label = c["name"] + (f"   •   {c['phone']}" if c.get("phone") else "")
            self.cust_cb.addItem(label, c)
        self.cust_cb.setCurrentIndex(0)
        if prev_text and not prev_text.startswith("—"):
            self.cust_cb.setEditText(prev_text)
        else:
            self.cust_cb.setEditText("")
        self.cust_cb.blockSignals(False)

    def _select_customer_in_combo(self, cust_id=None, cust_name=""):
        self.cust_cb.blockSignals(True)
        found = False
        if cust_id:
            for i in range(self.cust_cb.count()):
                d = self.cust_cb.itemData(i)
                if isinstance(d, dict) and d.get("id") == cust_id:
                    self.cust_cb.setCurrentIndex(i); found = True; break
        if not found:
            self.cust_cb.setCurrentIndex(0)
            self.cust_cb.setEditText(cust_name or "")
        self.cust_cb.blockSignals(False)

    def _resolve_customer(self):
        text = self.cust_cb.currentText().strip()
        if not text or text.startswith("—"):
            return None, ""
        idx = self.cust_cb.currentIndex()
        if idx >= 0 and self.cust_cb.itemText(idx) == text:
            data = self.cust_cb.itemData(idx)
            if isinstance(data, dict):
                return data.get("id"), data.get("name", "")
        row = self.db.one(
            "SELECT id, name FROM customers WHERE name = ? COLLATE NOCASE", (text,))
        if row:
            return row["id"], row["name"]
        return None, text

    # ---------- categories / products ----------
    def refresh_categories(self):
        while self.cat_bar.count():
            it = self.cat_bar.takeAt(0)
            w = it.widget()
            if w: w.deleteLater()
        all_btn = QPushButton("All"); all_btn.setObjectName("chip")
        all_btn.setCheckable(True); all_btn.setChecked(True)
        all_btn.clicked.connect(lambda: self._select_cat(None, all_btn))
        self.cat_bar.addWidget(all_btn)
        self._cat_btns = [all_btn]
        for c in self.db.categories():
            b = QPushButton(c["name"]); b.setObjectName("chip"); b.setCheckable(True)
            b.clicked.connect(lambda _, cid=c["id"], bb=b: self._select_cat(cid, bb))
            self.cat_bar.addWidget(b); self._cat_btns.append(b)
        self.cat_bar.addStretch()
        self.current_cat = None

    def _select_cat(self, cid, btn):
        for b in self._cat_btns:
            b.setChecked(b is btn)
        self.current_cat = cid
        self.refresh_products()

    def refresh_products(self):
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w: w.deleteLater()
        sym = self.db.get_setting("currency_symbol", "LBP ")
        prods = self.db.products(self.search.text().strip(), self.current_cat)
        cols = 4
        row = col = 0
        for p in prods:
            p = dict(p)
            if p.get("track_stock") and p.get("stock", 0) <= 0:
                continue
            card = ProductCard(p, sym)
            card.clicked.connect(self.on_product)
            self.grid.addWidget(card, row, col)
            col += 1
            if col >= cols: col = 0; row += 1
        for r in range(row + 1):
            self.grid.setRowStretch(r, 0)
        self.grid.setRowStretch(row + 1, 1)

    def reload_open_orders(self):
        self.open_orders = self.db.open_orders()
        self._render_tabs()

    def _render_tabs(self):
        while self.tabs_bar.count():
            it = self.tabs_bar.takeAt(0)
            w = it.widget()
            if w: w.deleteLater()
        newb = QPushButton("+ New"); newb.setObjectName("chip")
        newb.clicked.connect(lambda: self.new_order())
        self.tabs_bar.addWidget(newb)
        for o in self.open_orders:
            active = self.current_order and self.current_order.get("id") == o["id"]
            b = QPushButton(f"#{o['order_no'].split('-')[-1]}")
            b.setObjectName("chip"); b.setCheckable(True); b.setChecked(bool(active))
            b.clicked.connect(lambda _, oo=o: self.load_order(oo))
            self.tabs_bar.addWidget(b)
        self.tabs_bar.addStretch()

    def load_order(self, o):
        self.current_order = {
            "id": o["id"], "no": o["order_no"], "type": "Delivery",
            "items": [{"key": i["id"], "product_id": i["product_id"], "name": i["name"],
                       "emoji": "", "qty": i["qty"], "unit": i["unit_price"],
                       "options": _parse_opts_str(i["options"]),
                       "line": i["line_total"]} for i in o["items"]],
            "customer_id": o.get("customer_id"),
            "customer_name": o.get("customer_name", ""),
            "discount": float(o["discount"]),
            "delivery": float(o["delivery"]),
        }
        self.order_lbl.setText(f"Order {o['order_no']}")
        self._select_customer_in_combo(o.get("customer_id"),
                                       o.get("customer_name", ""))
        self.disc_in.setText(f"{self.current_order['discount']:.0f}")
        self._render_items()
        self.recalc()
        self._render_tabs()

    def new_order(self, silent=False):
        self.current_order = {
            "id": None, "no": self.db.next_order_no(), "type": "Delivery",
            "items": [], "customer_id": None, "customer_name": "",
            "discount": 0.0, "delivery": 0.0,
        }
        self.order_lbl.setText(f"Order {self.current_order['no']}  (new)")
        self._select_customer_in_combo(None, "")
        self.disc_in.setText("0")
        self._render_items(); self.recalc(); self._render_tabs()

    def on_product(self, product):
        p = self.db.get_product(product["id"])
        if not p: return
        if p["track_stock"] and p["stock"] <= 0:
            Toast(self.window(), f"{p['name']} is out of stock", "warning"); return
        if p["has_options"]:
            opts = self.db.product_options_for(p)
            dlg = OptionDialog(self, p, opts,
                               self.db.get_setting("currency_symbol", "LBP "))
            if dlg.exec_() != QDialog.Accepted: return
            data = dlg.result_data
            unit = _compute_unit_price(p, data["options"])
            key = f"{p['id']}-{datetime.now().timestamp()}"
            self.current_order["items"].append({
                "key": key, "product_id": p["id"], "name": p["name"], "emoji": p["emoji"],
                "qty": data["qty"], "unit": unit, "options": data["options"],
                "line": unit * data["qty"]})
        else:
            key = f"{p['id']}-{datetime.now().timestamp()}"
            self.current_order["items"].append({
                "key": key, "product_id": p["id"], "name": p["name"], "emoji": p["emoji"],
                "qty": 1, "unit": float(p["price"]), "options": [],
                "line": float(p["price"])})
        self._render_items(); self.recalc()

    def _render_items(self):
        while self.items_layout.count() > 1:
            it = self.items_layout.takeAt(0)
            w = it.widget()
            if w: w.deleteLater()
        settings = self.db.all_settings()
        if not self.current_order["items"]:
            empty = QLabel("Cart is empty\nClick a product to add it")
            empty.setAlignment(Qt.AlignCenter); empty.setObjectName("faint")
            empty.setStyleSheet("padding:30px 10px; font-size:12px;")
            self.items_layout.insertWidget(0, empty)
            return
        for i, item in enumerate(self.current_order["items"]):
            w = self._make_line(item, settings)
            self.items_layout.insertWidget(i, w)

    def _make_line(self, item, settings):
        sym = settings.get("currency_symbol", "LBP ")
        f = QFrame(); f.setObjectName("lineItem")
        v = QHBoxLayout(f); v.setContentsMargins(0, 6, 0, 6); v.setSpacing(8)
        v1 = QVBoxLayout(); v1.setSpacing(1)
        nm = QLabel(f"{item['emoji']} {item['name']}")
        nm.setStyleSheet("font-weight:600; font-size:12px;")
        v1.addWidget(nm)
        if item["options"]:
            opt = QLabel(", ".join(o["label"] for o in item["options"]))
            opt.setObjectName("faint"); opt.setStyleSheet("font-size:10px;")
            opt.setWordWrap(True)
            v1.addWidget(opt)
        unit_lbl = QLabel(
            f"{fmt_money(item['unit'], sym)}  ({fmt_money_secondary(item['unit'], settings)})")
        unit_lbl.setObjectName("faint"); unit_lbl.setStyleSheet("font-size:9px;")
        v1.addWidget(unit_lbl)
        v.addLayout(v1, 1)

        q = QHBoxLayout(); q.setSpacing(2)
        minus = QPushButton("−"); minus.setObjectName("iconBtn"); minus.setFixedSize(22, 22)
        minus.clicked.connect(lambda _, k=item["key"]: self._change_qty(k, -1))
        plus = QPushButton("+"); plus.setObjectName("iconBtn"); plus.setFixedSize(22, 22)
        plus.clicked.connect(lambda _, k=item["key"]: self._change_qty(k, +1))
        ql = QLabel(str(item["qty"])); ql.setFixedWidth(18); ql.setAlignment(Qt.AlignCenter)
        ql.setStyleSheet("font-weight:700; font-size:12px;")
        q.addWidget(minus); q.addWidget(ql); q.addWidget(plus)
        v.addLayout(q)

        tot_col = QVBoxLayout(); tot_col.setSpacing(0)
        tot = QLabel(fmt_money(item["line"], sym))
        tot.setStyleSheet("font-weight:700; font-size:11px;")
        tot.setAlignment(Qt.AlignRight); tot.setMinimumWidth(100)
        usd = QLabel(fmt_money_secondary(item["line"], settings))
        usd.setObjectName("faint"); usd.setStyleSheet("font-size:9px;")
        usd.setAlignment(Qt.AlignRight)
        tot_col.addWidget(tot); tot_col.addWidget(usd)
        v.addLayout(tot_col)

        rm = QPushButton("✕"); rm.setObjectName("iconBtn"); rm.setFixedSize(22, 22)
        rm.clicked.connect(lambda _, k=item["key"]: self._remove_item(k))
        v.addWidget(rm)
        return f

    def _change_qty(self, key, delta):
        for it in self.current_order["items"]:
            if it["key"] == key:
                it["qty"] = max(1, it["qty"] + delta)
                it["line"] = it["unit"] * it["qty"]
                break
        self._render_items(); self.recalc()

    def _remove_item(self, key):
        self.current_order["items"] = [i for i in self.current_order["items"]
                                       if i["key"] != key]
        self._render_items(); self.recalc()

    def recalc(self):
        if not self.current_order: return
        settings = self.db.all_settings()
        subtotal = sum(i["line"] for i in self.current_order["items"])
        try: disc = float(self.disc_in.text() or 0)
        except ValueError: disc = 0.0
        base = max(0, subtotal - disc)
        tax = 0.0
        delivery = float(self.db.get_setting("delivery_fee", "0") or 0)
        grand = base + tax + delivery
        self.current_order.update({
            "subtotal": subtotal, "discount": disc,
            "tax": tax, "delivery": delivery, "total": grand,
        })
        self.sub_lbl.setText(fmt_money_dual(subtotal, settings))
        self.del_lbl.setText(fmt_money_dual(delivery, settings))
        self.grand_lbl.setText(fmt_money_dual(grand, settings))

    def clear_order(self):
        if not self.current_order: return
        if self.current_order["items"] and not confirm(self, "Clear this order?"): return
        self.current_order["items"] = []
        self.disc_in.setText("0")
        self._render_items(); self.recalc()

    def hold_order(self):
        if not self.current_order: return
        if not self.current_order["items"]:
            Toast(self.window(), "Nothing to hold", "warning"); return
        cid, cname = self._resolve_customer()
        self.current_order["customer_id"] = cid
        self.current_order["customer_name"] = cname
        self.db.save_order(self.current_order, status="open")
        Toast(self.window(), f"Order {self.current_order['no']} held", "success")
        self.reload_open_orders()
        self.new_order(silent=True)

    # ---------- payment + receipt ----------
    def pay_order(self):
        if not self.current_order or not self.current_order["items"]:
            Toast(self.window(), "Cart is empty", "warning"); return
        settings = self.db.all_settings()
        sym = settings.get("currency_symbol", "LBP ")
        dlg = PaymentDialog(self, self.current_order["total"], settings)
        if dlg.exec_() != QDialog.Accepted: return

        cid, cname = self._resolve_customer()
        self.current_order["customer_id"] = cid
        self.current_order["customer_name"] = cname
        self.current_order["payment_method"] = "Cash"
        self.current_order["user_id"] = self.user["id"]
        self.db.save_order(self.current_order, status="paid")
        self.db.deduct_stock_for_order(self.current_order)

        order_snapshot = {
            "id": self.current_order.get("id"),
            "no": self.current_order["no"],
            "type": self.current_order.get("type", "Delivery"),
            "customer_id": cid,
            "customer_name": cname,
            "items": [dict(i) for i in self.current_order["items"]],
            "subtotal": self.current_order["subtotal"],
            "discount": self.current_order["discount"],
            "tax": self.current_order["tax"],
            "delivery": self.current_order["delivery"],
            "total": self.current_order["total"],
            "payment_method": "Cash",
        }

        settings = self.db.all_settings()
        receipt = build_receipt_text(order_snapshot, settings, "CUSTOMER COPY")

        try:
            fname = f"receipt_{order_snapshot['no'].replace('-', '_')}.txt"
            with open(fname, "w", encoding="utf-8") as f:
                f.write(receipt)
        except Exception:
            pass

        # ── Firebase cloud sync ────────────────────────────────
        try:
            ok, info = self.cloud.push_order(order_snapshot)
            if not ok and self.cloud.enabled() and "disabled" not in info:
                if not getattr(self, "_cloud_warned", False):
                    self._cloud_warned = True
                    warn(self, f"Cloud sync failed:\n{info}", "Firebase")
        except Exception:
            pass

        printer_name = (settings.get("printer_name") or "").strip()
        auto = (settings.get("printer_auto", "1") == "1")

        printed = False
        print_err = ""
        if printer_name and auto:
            try:
                print_receipt_two_copies_local(printer_name,
                                               order_snapshot, settings)
                printed = True
            except Exception as e:
                print_err = str(e)

        if printed:
            Toast(self.window(),
                  f"Paid {fmt_money(order_snapshot['total'], sym)} — 2 copies printed",
                  "success")
        else:
            Toast(self.window(),
                  f"Paid {fmt_money(order_snapshot['total'], sym)}", "success")
            dlg2 = ReceiptDialog(self, receipt, printer_name,
                                 order=order_snapshot, settings=settings)
            if print_err:
                warn(dlg2, f"Auto-print failed:\n{print_err}", "Printer")
            dlg2.exec_()

        self.reload_open_orders()
        self.refresh_products()
        self.new_order(silent=True)


# ════════════════════════════════════════════════════════════════
#  PRODUCTS PAGE
# ════════════════════════════════════════════════════════════════
class ProductsPage(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        v = QVBoxLayout(self); v.setContentsMargins(18, 18, 18, 18); v.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("Products"); title.setObjectName("h1")
        head.addWidget(title); head.addStretch()
        add_cat = QPushButton("+ Category"); add_cat.clicked.connect(self.add_cat)
        add = QPushButton("+ New Product"); add.setObjectName("primary")
        add.clicked.connect(self.add_product)
        head.addWidget(add_cat); head.addWidget(add)
        v.addLayout(head)

        self.search = QLineEdit(); self.search.setPlaceholderText("🔍  Search…")
        self.search.textChanged.connect(self.refresh)
        v.addWidget(self.search)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Emoji", "Name", "Category", "Price", "Cost", "Stock", "Options", "Actions"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 55)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 120)
        self.table.setColumnWidth(4, 120)
        self.table.setColumnWidth(5, 70)
        self.table.setColumnWidth(6, 70)
        self.table.setColumnWidth(7, 120)
        v.addWidget(self.table, 1)

        self.refresh()

    def refresh(self):
        rows = self.db.products(self.search.text().strip(), only_active=False)
        sym = self.db.get_setting("currency_symbol", "LBP ")
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            p = dict(row)
            self.table.setItem(r, 0, QTableWidgetItem(p["emoji"]))
            self.table.setItem(r, 1, QTableWidgetItem(p["name"]))
            self.table.setItem(r, 2, QTableWidgetItem(p["category"] or "—"))
            self.table.setItem(r, 3, QTableWidgetItem(fmt_money(p["price"], sym)))
            self.table.setItem(r, 4, QTableWidgetItem(fmt_money(p["cost"], sym)))
            stock_txt = f"{p['stock']:.0f}" if p["track_stock"] else "—"
            self.table.setItem(r, 5, QTableWidgetItem(stock_txt))
            has_co = bool((p.get("custom_options") or "").strip())
            opts_txt = "Custom" if has_co else ("Yes" if p["has_options"] else "No")
            self.table.setItem(r, 6, QTableWidgetItem(opts_txt))
            self._install_actions(r, p)

    def _install_actions(self, r, p):
        w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
        edit = QPushButton("Edit"); edit.setObjectName("iconBtn")
        edit.clicked.connect(lambda _, pp=p: self.edit_product(pp))
        dele = QPushButton("Delete"); dele.setObjectName("iconBtn")
        dele.setStyleSheet("color:#ef4444;")
        dele.clicked.connect(lambda _, pp=p: self.del_product(pp))
        h.addWidget(edit); h.addWidget(dele)
        self.table.setCellWidget(r, 7, w)

    def add_product(self):
        if ProductDialog(self, self.db).exec_() == QDialog.Accepted:
            self.refresh()

    def edit_product(self, p):
        if ProductDialog(self, self.db, p).exec_() == QDialog.Accepted:
            self.refresh()

    def del_product(self, p):
        if confirm(self, f"Delete product '{p['name']}'?"):
            self.db.delete_product(p["id"]); self.refresh()

    def add_cat(self):
        name, ok = QInputDialog.getText(self, "New Category", "Category name:")
        if ok and name.strip():
            self.db.add_category(name.strip())
            Toast(self.window(), f"Category '{name}' added", "success")


# ════════════════════════════════════════════════════════════════
#  CUSTOMERS PAGE
# ════════════════════════════════════════════════════════════════
class CustomersPage(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        v = QVBoxLayout(self); v.setContentsMargins(18, 18, 18, 18); v.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("Customers"); title.setObjectName("h1")
        head.addWidget(title); head.addStretch()
        add = QPushButton("+ New Customer"); add.setObjectName("primary")
        add.clicked.connect(self.add_customer)
        head.addWidget(add)
        v.addLayout(head)

        self.search = QLineEdit(); self.search.setPlaceholderText("🔍  Search by name or phone…")
        self.search.textChanged.connect(self.refresh)
        v.addWidget(self.search)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Phone", "Address", "Actions"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 140)
        self.table.setColumnWidth(2, 260)
        self.table.setColumnWidth(3, 130)
        v.addWidget(self.table, 1)

        self.refresh()

    def refresh(self):
        rows = self.db.customers(self.search.text().strip())
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            c = dict(row)
            self.table.setItem(r, 0, QTableWidgetItem(c["name"]))
            self.table.setItem(r, 1, QTableWidgetItem(c["phone"]))
            self.table.setItem(r, 2, QTableWidgetItem(c["address"]))
            w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
            ed = QPushButton("Edit"); ed.setObjectName("iconBtn")
            ed.clicked.connect(lambda _, cc=c: self.edit_customer(cc))
            dl = QPushButton("Delete"); dl.setObjectName("iconBtn")
            dl.setStyleSheet("color:#ef4444;")
            dl.clicked.connect(lambda _, cc=c: self.del_customer(cc))
            h.addWidget(ed); h.addWidget(dl)
            self.table.setCellWidget(r, 3, w)

    def add_customer(self):
        if CustomerDialog(self, self.db).exec_() == QDialog.Accepted:
            self.refresh()
            try:
                rows = self.db.customers()
                if rows:
                    CloudSync(self.db).push_customer(dict(rows[-1]))
            except Exception:
                pass

    def edit_customer(self, c):
        if CustomerDialog(self, self.db, c).exec_() == QDialog.Accepted:
            self.refresh()

    def del_customer(self, c):
        if confirm(self, f"Delete customer '{c['name']}'?"):
            self.db.delete_customer(c["id"]); self.refresh()


# ════════════════════════════════════════════════════════════════
#  EXPENSES PAGE
# ════════════════════════════════════════════════════════════════
class ExpensesPage(QWidget):
    def __init__(self, db, user):
        super().__init__()
        self.db = db; self.user = user
        v = QVBoxLayout(self); v.setContentsMargins(18, 18, 18, 18); v.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel("Expenses"); title.setObjectName("h1")
        head.addWidget(title); head.addStretch()
        add = QPushButton("+ New Expense"); add.setObjectName("primary")
        add.clicked.connect(self.add_expense)
        head.addWidget(add)
        v.addLayout(head)

        self.total_lbl = QLabel(""); self.total_lbl.setObjectName("muted")
        v.addWidget(self.total_lbl)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Date", "Category", "Description", "Amount", "Actions"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(3, 150)
        self.table.setColumnWidth(4, 130)
        v.addWidget(self.table, 1)

        self.refresh()

    def refresh(self):
        rows = self.db.expenses()
        sym = self.db.get_setting("currency_symbol", "LBP ")
        total = sum(float(r["amount"]) for r in rows)
        self.total_lbl.setText(f"{len(rows)} entries  •  Total {fmt_money(total, sym)}")
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            e = dict(row)
            self.table.setItem(r, 0, QTableWidgetItem(e["spent_on"]))
            self.table.setItem(r, 1, QTableWidgetItem(e["category"]))
            self.table.setItem(r, 2, QTableWidgetItem(e["description"]))
            self.table.setItem(r, 3, QTableWidgetItem(fmt_money(e["amount"], sym)))
            w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
            ed = QPushButton("Edit"); ed.setObjectName("iconBtn")
            ed.clicked.connect(lambda _, ee=e: self.edit_expense(ee))
            dl = QPushButton("Delete"); dl.setObjectName("iconBtn")
            dl.setStyleSheet("color:#ef4444;")
            dl.clicked.connect(lambda _, ee=e: self.del_expense(ee))
            h.addWidget(ed); h.addWidget(dl)
            self.table.setCellWidget(r, 4, w)

    def add_expense(self):
        if ExpenseDialog(self, self.db).exec_() == QDialog.Accepted:
            self.refresh()

    def edit_expense(self, e):
        if ExpenseDialog(self, self.db, e).exec_() == QDialog.Accepted:
            self.refresh()

    def del_expense(self, e):
        if confirm(self, "Delete this expense?"):
            self.db.delete_expense(e["id"]); self.refresh()


# ════════════════════════════════════════════════════════════════
#  REPORTS PAGE
# ════════════════════════════════════════════════════════════════
class ReportsPage(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        v = QVBoxLayout(self); v.setContentsMargins(18, 18, 18, 18); v.setSpacing(12)

        title = QLabel("Reports"); title.setObjectName("h1"); v.addWidget(title)

        ctl = QHBoxLayout(); ctl.setSpacing(8)
        self.from_d = QDateEdit(QDate.currentDate().addDays(-7))
        self.from_d.setCalendarPopup(True); self.from_d.setDisplayFormat("yyyy-MM-dd")
        self.to_d = QDateEdit(QDate.currentDate())
        self.to_d.setCalendarPopup(True); self.to_d.setDisplayFormat("yyyy-MM-dd")
        ctl.addWidget(QLabel("From")); ctl.addWidget(self.from_d)
        ctl.addWidget(QLabel("To")); ctl.addWidget(self.to_d)
        apply = QPushButton("Apply"); apply.setObjectName("primary")
        apply.clicked.connect(self.refresh); ctl.addWidget(apply)
        for label, days in [("Today", 0), ("Week", 7), ("Month", 30)]:
            b = QPushButton(label); b.setObjectName("ghost")
            b.clicked.connect(lambda _, d=days: self._quick(d))
            ctl.addWidget(b)
        ctl.addStretch()
        v.addLayout(ctl)

        self.cards = QHBoxLayout(); self.cards.setSpacing(10)
        v.addLayout(self.cards)
        self.card_vals = {}
        for key, label in [("orders", "Orders"), ("revenue", "Revenue"),
                           ("discount", "Discount"),
                           ("expenses", "Expenses"), ("profit", "Net Profit")]:
            card = QFrame(); card.setObjectName("card")
            cv = QVBoxLayout(card); cv.setContentsMargins(14, 12, 14, 12); cv.setSpacing(2)
            l = QLabel(label); l.setObjectName("faint"); l.setStyleSheet("font-size:11px;")
            val = QLabel("—"); val.setStyleSheet("font-size:15px; font-weight:800;")
            cv.addWidget(l); cv.addWidget(val)
            self.cards.addWidget(card, 1)
            self.card_vals[key] = val

        tables = QHBoxLayout(); tables.setSpacing(12)

        tp_box = QFrame(); tp_box.setObjectName("card")
        tv = QVBoxLayout(tp_box); tv.setContentsMargins(12, 12, 12, 12)
        tv.addWidget(QLabel("🏆 Top Products"))
        self.top_table = QTableWidget(0, 3)
        self.top_table.setHorizontalHeaderLabels(["Product", "Qty", "Revenue"])
        self.top_table.verticalHeader().setVisible(False)
        self.top_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.top_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.top_table.setColumnWidth(1, 60)
        self.top_table.setColumnWidth(2, 130)
        tv.addWidget(self.top_table)
        tables.addWidget(tp_box, 1)

        sc_box = QFrame(); sc_box.setObjectName("card")
        scv = QVBoxLayout(sc_box); scv.setContentsMargins(12, 12, 12, 12)
        scv.addWidget(QLabel("📂 Sales by Category"))
        self.cat_table = QTableWidget(0, 2)
        self.cat_table.setHorizontalHeaderLabels(["Category", "Revenue"])
        self.cat_table.verticalHeader().setVisible(False)
        self.cat_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.cat_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.cat_table.setColumnWidth(1, 150)
        scv.addWidget(self.cat_table)
        tables.addWidget(sc_box, 1)

        pm_box = QFrame(); pm_box.setObjectName("card")
        pmv = QVBoxLayout(pm_box); pmv.setContentsMargins(12, 12, 12, 12)
        pmv.addWidget(QLabel("💵 Payment Methods"))
        self.pm_table = QTableWidget(0, 3)
        self.pm_table.setHorizontalHeaderLabels(["Method", "Count", "Revenue"])
        self.pm_table.verticalHeader().setVisible(False)
        self.pm_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pm_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.pm_table.setColumnWidth(1, 60)
        self.pm_table.setColumnWidth(2, 150)
        pmv.addWidget(self.pm_table)
        tables.addWidget(pm_box, 1)

        v.addLayout(tables, 1)

        ds_box = QFrame(); ds_box.setObjectName("card")
        dsv = QVBoxLayout(ds_box); dsv.setContentsMargins(12, 12, 12, 12)
        dsv.addWidget(QLabel("📅 Daily Sales"))
        self.day_table = QTableWidget(0, 3)
        self.day_table.setHorizontalHeaderLabels(["Date", "Orders", "Revenue"])
        self.day_table.verticalHeader().setVisible(False)
        self.day_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.day_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.day_table.setColumnWidth(1, 80)
        self.day_table.setColumnWidth(2, 180)
        dsv.addWidget(self.day_table)
        v.addWidget(ds_box, 1)

        cc_box = QFrame(); cc_box.setObjectName("card")
        ccv = QVBoxLayout(cc_box); ccv.setContentsMargins(14, 12, 14, 12)
        ccv.setSpacing(8)
        cch = QHBoxLayout()
        cch.addWidget(QLabel("💵 Close Cash"))
        cch.addStretch()
        self.cc_print_btn = QPushButton("🖨  Print Close Cash")
        self.cc_print_btn.setObjectName("primary")
        self.cc_print_btn.clicked.connect(self.print_close_cash)
        cch.addWidget(self.cc_print_btn)
        self.cc_sync_btn = QPushButton("☁  Sync to Firebase")
        self.cc_sync_btn.setObjectName("ghost")
        self.cc_sync_btn.clicked.connect(self.sync_close_cash)
        cch.addWidget(self.cc_sync_btn)
        ccv.addLayout(cch)
        self.cc_info = QLabel("")
        self.cc_info.setObjectName("muted")
        self.cc_info.setWordWrap(True)
        ccv.addWidget(self.cc_info)
        v.addWidget(cc_box)

        self.refresh()

    def _quick(self, days):
        self.from_d.setDate(QDate.currentDate().addDays(-days))
        self.to_d.setDate(QDate.currentDate())
        self.refresh()

    def refresh(self):
        s = self.from_d.date().toString("yyyy-MM-dd")
        e = self.to_d.date().toString("yyyy-MM-dd")
        settings = self.db.all_settings()
        sym = settings.get("currency_symbol", "LBP ")
        summ = self.db.summary(s, e)
        profit = summ["revenue"] - summ["expenses"]
        self.card_vals["orders"].setText(str(summ["orders"]))
        self.card_vals["revenue"].setText(fmt_money(summ["revenue"], sym))
        self.card_vals["discount"].setText(fmt_money(summ["discount"], sym))
        self.card_vals["expenses"].setText(fmt_money(summ["expenses"], sym))
        self.card_vals["profit"].setText(fmt_money(profit, sym))

        tp = self.db.top_products(s, e)
        self.top_table.setRowCount(len(tp))
        for r, row in enumerate(tp):
            self.top_table.setItem(r, 0, QTableWidgetItem(row["name"]))
            self.top_table.setItem(r, 1, QTableWidgetItem(f"{row['qty']:.0f}"))
            self.top_table.setItem(r, 2, QTableWidgetItem(fmt_money(row["revenue"], sym)))

        sc = self.db.sales_by_category(s, e)
        self.cat_table.setRowCount(len(sc))
        for r, row in enumerate(sc):
            self.cat_table.setItem(r, 0, QTableWidgetItem(row["category"]))
            self.cat_table.setItem(r, 1, QTableWidgetItem(fmt_money(row["revenue"], sym)))

        pm = self.db.sales_by_method(s, e)
        self.pm_table.setRowCount(len(pm))
        for r, row in enumerate(pm):
            self.pm_table.setItem(r, 0, QTableWidgetItem(row["method"]))
            self.pm_table.setItem(r, 1, QTableWidgetItem(str(row["c"])))
            self.pm_table.setItem(r, 2, QTableWidgetItem(fmt_money(row["revenue"], sym)))

        dd = self.db.sales_by_day(s, e)
        self.day_table.setRowCount(len(dd))
        for r, row in enumerate(dd):
            self.day_table.setItem(r, 0, QTableWidgetItem(row["day"]))
            self.day_table.setItem(r, 1, QTableWidgetItem(str(row["orders"])))
            self.day_table.setItem(r, 2, QTableWidgetItem(fmt_money(row["revenue"], sym)))

        cash = self.db.cash_summary(s, e)
        expected = cash["expected"]
        self.cc_info.setText(
            f"<b>Cash orders:</b> {cash['cash_orders']} &nbsp;•&nbsp; "
            f"<b>Cash sales:</b> {fmt_money(cash['cash_sales'], sym)} "
            f"<span style='color:#94a3b8;'>({fmt_money_secondary(cash['cash_sales'], settings)})</span> "
            f"&nbsp;•&nbsp; <b>Expenses:</b> {fmt_money(cash['expenses'], sym)} "
            f"<span style='color:#94a3b8;'>({fmt_money_secondary(cash['expenses'], settings)})</span><br>"
            f"<b>Expected in drawer:</b> {fmt_money(expected, sym)} "
            f"<span style='color:#94a3b8;'>({fmt_money_secondary(expected, settings)})</span>"
        )

    def print_close_cash(self):
        s = self.from_d.date().toString("yyyy-MM-dd")
        e = self.to_d.date().toString("yyyy-MM-dd")
        settings = self.db.all_settings()
        printer_name = (settings.get("printer_name") or "").strip()
        if not printer_name:
            warn(self, "Set the local printer in Settings first"); return
        text = build_close_cash_text(self.db, s, e, settings)
        try:
            print_receipt_local(printer_name, text)
            Toast(self.window(), "Close Cash report sent to printer", "success")
        except Exception as ex:
            warn(self, f"Printer error:\n{ex}")

    def sync_close_cash(self):
        s = self.from_d.date().toString("yyyy-MM-dd")
        e = self.to_d.date().toString("yyyy-MM-dd")
        cloud = CloudSync(self.db)
        if not cloud.enabled():
            warn(self, "Enable Cloud Sync in Settings first"); return
        ok, info = cloud.push_close_cash(s, e)
        if ok:
            Toast(self.window(), "Close Cash synced to Firebase", "success")
        else:
            warn(self, f"Firebase sync failed:\n{info}")


# ════════════════════════════════════════════════════════════════
#  SETTINGS PAGE
# ════════════════════════════════════════════════════════════════
class SettingsPage(QWidget):
    theme_changed = pyqtSignal(str)

    def __init__(self, db, user):
        super().__init__()
        self.db = db; self.user = user

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        host = QWidget(); scroll.setWidget(host)
        v = QVBoxLayout(host)
        v.setContentsMargins(18, 18, 18, 18); v.setSpacing(14)

        title = QLabel("Settings"); title.setObjectName("h1")
        v.addWidget(title)

        # General
        card = QFrame(); card.setObjectName("card")
        form = QFormLayout(card)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.fields = {}
        for key, label in [
            ("restaurant_name", "Restaurant name"),
            ("tagline", "Tagline"),
            ("address", "Address"),
            ("phone", "Phone"),
            ("currency_symbol", "Currency symbol"),
            ("secondary_currency", "Secondary currency"),
            ("secondary_rate", "LBP per 1 USD"),
            ("delivery_fee", "Delivery fee (LBP)"),
            ("receipt_footer", "Receipt footer"),
        ]:
            e = QLineEdit(self.db.get_setting(key, ""))
            e.setMinimumWidth(260)
            form.addRow(label, e)
            self.fields[key] = e

        self.theme_cb = QComboBox()
        self.theme_cb.addItems(["light", "dark"])
        self.theme_cb.setCurrentText(self.db.get_setting("theme", "light"))
        self.theme_cb.setMinimumWidth(140)
        form.addRow("Theme", self.theme_cb)

        save = QPushButton("Save Settings"); save.setObjectName("primary")
        save.setMinimumHeight(38); save.clicked.connect(self.save)
        form.addRow("", save)

        v.addWidget(card)

        # ── Local Printer ──────────────────────────────────────
        printer_card = QFrame(); printer_card.setObjectName("card")
        pv = QVBoxLayout(printer_card)
        pv.setContentsMargins(20, 20, 20, 20); pv.setSpacing(10)

        ptitle = QLabel("🖨  Local Printer")
        ptitle.setObjectName("h3")
        pv.addWidget(ptitle)

        phint = QLabel(
            "Select the local printer / queue name installed on this computer. "
            "Receipts are sent as <b>raw ESC/POS bytes</b>, so the printer must "
            "support ESC/POS commands directly (most thermal receipt printers do). "
            "On Windows, install the printer driver and pick its name from the list. "
            "Each receipt is printed as TWO copies (CUSTOMER COPY + RESTAURANT COPY) "
            "with an automatic paper cut between them.")
        phint.setObjectName("faint"); phint.setWordWrap(True)
        phint.setStyleSheet("font-size:10px;")
        pv.addWidget(phint)

        pform = QFormLayout(); pform.setSpacing(8)
        pform.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        printer_row = QHBoxLayout()
        self.printer_cb = QComboBox()
        self.printer_cb.setEditable(True)
        self.printer_cb.setMinimumWidth(300)
        self.printer_cb.setCurrentText(self.db.get_setting("printer_name", ""))
        refresh_btn = QPushButton("🔄  Refresh list")
        refresh_btn.setObjectName("ghost")
        refresh_btn.clicked.connect(self.refresh_printers)
        printer_row.addWidget(self.printer_cb, 1)
        printer_row.addWidget(refresh_btn)
        printer_row.addStretch()
        pform.addRow("Local printer", printer_row)

        self.printer_auto_cb = QCheckBox("Auto-print receipt (2 copies) after each payment")
        self.printer_auto_cb.setChecked(self.db.get_setting("printer_auto", "1") == "1")
        pform.addRow("", self.printer_auto_cb)
        pv.addLayout(pform)

        pbtn_row = QHBoxLayout()
        save_p = QPushButton("Save printer settings"); save_p.setObjectName("primary")
        save_p.clicked.connect(self.save)
        test_p = QPushButton("Test print (2 copies)"); test_p.setObjectName("ghost")
        test_p.clicked.connect(self.test_print)
        pbtn_row.addWidget(save_p); pbtn_row.addWidget(test_p)
        pbtn_row.addStretch()
        pv.addLayout(pbtn_row)

        v.addWidget(printer_card)

        # Preload the printer list
        self.refresh_printers()

        # Firebase Cloud Sync
        fb_card = QFrame(); fb_card.setObjectName("card")
        fv = QVBoxLayout(fb_card)
        fv.setContentsMargins(20, 20, 20, 20); fv.setSpacing(10)

        fb_title = QLabel("☁  Cloud Sync (Firebase Firestore)")
        fb_title.setObjectName("h3")
        fv.addWidget(fb_title)

        fb_hint = QLabel(
            f"Project: <b>{FIREBASE_CONFIG['projectId']}</b> &nbsp;|&nbsp; "
            f"Auth domain: {FIREBASE_CONFIG['authDomain']}<br>"
            "Each paid order, new customer and Close Cash snapshot is mirrored "
            "to Firestore via the REST API.  Make sure Anonymous sign-in is "
            "enabled in Firebase Authentication and Firestore rules allow "
            "authenticated writes."
        )
        fb_hint.setObjectName("faint"); fb_hint.setWordWrap(True)
        fb_hint.setStyleSheet("font-size:10px;")
        fv.addWidget(fb_hint)

        fform = QFormLayout(); fform.setSpacing(8)
        fform.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.fb_enabled_cb = QCheckBox("Enable cloud sync")
        self.fb_enabled_cb.setChecked(self.db.get_setting("firebase_enabled", "0") == "1")
        fform.addRow("", self.fb_enabled_cb)

        self.fb_orders_in = QLineEdit(
            self.db.get_setting("firebase_collection_orders", "orders"))
        fform.addRow("Orders collection", self.fb_orders_in)

        self.fb_customers_in = QLineEdit(
            self.db.get_setting("firebase_collection_customers", "customers"))
        fform.addRow("Customers collection", self.fb_customers_in)

        self.fb_cash_in = QLineEdit(
            self.db.get_setting("firebase_collection_cash", "close_cash"))
        fform.addRow("Close-cash collection", self.fb_cash_in)

        fv.addLayout(fform)

        fb_btns = QHBoxLayout()
        save_fb = QPushButton("Save cloud settings"); save_fb.setObjectName("primary")
        save_fb.clicked.connect(self.save)
        test_fb = QPushButton("Test connection"); test_fb.setObjectName("ghost")
        test_fb.clicked.connect(self.test_firebase)
        fb_btns.addWidget(save_fb); fb_btns.addWidget(test_fb)
        fb_btns.addStretch()
        fv.addLayout(fb_btns)

        v.addWidget(fb_card)

        # Users
        users_card = QFrame(); users_card.setObjectName("card")
        uv = QVBoxLayout(users_card)
        uv.setContentsMargins(20, 20, 20, 20); uv.setSpacing(10)

        uh = QHBoxLayout()
        uh_title = QLabel("👤 Users"); uh_title.setObjectName("h3")
        uh.addWidget(uh_title); uh.addStretch()
        add_btn = QPushButton("+ Add User"); add_btn.setObjectName("ghost")
        add_btn.clicked.connect(self.add_user)
        uh.addWidget(add_btn)
        uv.addLayout(uh)

        self.users_table = QTableWidget(0, 4)
        self.users_table.setHorizontalHeaderLabels(
            ["Username", "Full name", "Role", "Actions"])
        self.users_table.verticalHeader().setVisible(False)
        self.users_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.users_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.users_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.users_table.setColumnWidth(0, 160)
        self.users_table.setColumnWidth(2, 110)
        self.users_table.setColumnWidth(3, 130)
        self.users_table.setMinimumHeight(160)
        self.users_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        uv.addWidget(self.users_table)

        v.addWidget(users_card)
        v.addStretch(1)

        self.refresh_users()

    def refresh_printers(self):
        current = self.printer_cb.currentText().strip()
        names = list_local_printers()
        self.printer_cb.blockSignals(True)
        self.printer_cb.clear()
        for n in names:
            self.printer_cb.addItem(n)
        # Ensure the currently-saved printer appears even if not detected
        if current and current not in names:
            self.printer_cb.addItem(current)
        if current:
            self.printer_cb.setCurrentText(current)
        elif names:
            self.printer_cb.setCurrentText(names[0])
        self.printer_cb.blockSignals(False)

    def save(self):
        for key, e in self.fields.items():
            self.db.set_setting(key, e.text())
        self.db.set_setting("printer_name", self.printer_cb.currentText().strip())
        self.db.set_setting("printer_auto", "1" if self.printer_auto_cb.isChecked() else "0")

        self.db.set_setting("firebase_enabled",
                            "1" if self.fb_enabled_cb.isChecked() else "0")
        self.db.set_setting("firebase_collection_orders",
                            self.fb_orders_in.text().strip() or "orders")
        self.db.set_setting("firebase_collection_customers",
                            self.fb_customers_in.text().strip() or "customers")
        self.db.set_setting("firebase_collection_cash",
                            self.fb_cash_in.text().strip() or "close_cash")

        old_theme = self.db.get_setting("theme", "light")
        new_theme = self.theme_cb.currentText()
        self.db.set_setting("theme", new_theme)
        Toast(self.window(), "Settings saved", "success")
        if new_theme != old_theme:
            self.theme_changed.emit(new_theme)

    def test_firebase(self):
        client = FirebaseSync(FIREBASE_CONFIG)
        ok, info = client.push_document(
            self.fb_orders_in.text().strip() or "orders",
            {
                "test":       True,
                "message":    "Hello from Pizza POS",
                "created_at": datetime.now().isoformat(timespec="seconds"),
            })
        if ok:
            Toast(self.window(), f"Firebase OK ({info})", "success")
        else:
            warn(self, f"Firebase sync failed:\n{info}")

    def test_print(self):
        printer_name = self.printer_cb.currentText().strip()
        if not printer_name:
            warn(self, "Choose a local printer first"); return
        settings = self.db.all_settings()
        sample = {
            "id": None, "no": "TEST-0001", "type": "Delivery",
            "customer_name": "Test Customer",
            "items": [
                {"name": "Margherita Pizza", "emoji": "", "qty": 1,
                 "unit": 1100000, "line": 1100000,
                 "options": [{"label": "Large"},
                             {"label": "Margherita"},
                             {"label": "Pepperoni"}]},
                {"name": "Chicken BBQ Pizza", "emoji": "", "qty": 1,
                 "unit": 1200000, "line": 1200000,
                 "options": [{"label": "Large"},
                             {"label": "Chicken BBQ"},
                             {"label": "Margherita"}]},
                {"name": "Cheese Garlic Fingers", "emoji": "", "qty": 1,
                 "unit": 700000, "line": 700000,
                 "options": [{"label": "Medium"}]},
                {"name": "Chicken Wings", "emoji": "", "qty": 1,
                 "unit": 800000, "line": 800000,
                 "options": [{"label": "12 pcs + Fries"}]},
                {"name": "Chicken Strips", "emoji": "", "qty": 1,
                 "unit": 1300000, "line": 1300000,
                 "options": [{"label": "10 pcs"}]},
                {"name": "Special Offer (5 pcs + Fries + Pepsi)", "emoji": "",
                 "qty": 1, "unit": 1000000, "line": 1000000, "options": []},
                {"name": "Fries", "emoji": "", "qty": 1,
                 "unit": 600000, "line": 600000, "options": [{"label": "XXL"}]},
                {"name": "Soft Drink", "emoji": "", "qty": 2,
                 "unit": 100000, "line": 200000, "options": [{"label": "300ml"}]},
            ],
            "subtotal": 7000000, "discount": 0,
            "tax": 0, "delivery": 270000, "total": 7270000,
            "payment_method": "Cash",
        }
        try:
            print_receipt_two_copies_local(printer_name, sample, settings)
            Toast(self.window(), "Test sent to printer (2 copies)", "success")
        except Exception as e:
            warn(self, f"Printer error:\n{e}")

    def refresh_users(self):
        rows = self.db.users()
        self.users_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            u = dict(row)
            self.users_table.setItem(r, 0, QTableWidgetItem(u["username"]))
            self.users_table.setItem(r, 1, QTableWidgetItem(u["full_name"]))
            self.users_table.setItem(r, 2, QTableWidgetItem(u["role"]))
            w = QWidget(); h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0); h.setSpacing(4)
            if u["username"] != "admin":
                b = QPushButton("Delete"); b.setObjectName("iconBtn")
                b.setStyleSheet("color:#ef4444;")
                b.clicked.connect(lambda _, uid=u["id"]: self.del_user(uid))
                h.addWidget(b); h.addStretch()
            self.users_table.setCellWidget(r, 3, w)

        header_h = self.users_table.horizontalHeader().height() or 30
        row_h = self.users_table.verticalHeader().defaultSectionSize() or 30
        self.users_table.setFixedHeight(header_h + row_h * max(1, len(rows)) + 8)

    def add_user(self):
        u, ok = QInputDialog.getText(self, "New User", "Username:")
        if not ok or not u.strip(): return
        p, ok = QInputDialog.getText(self, "New User", "Password:", QLineEdit.Password)
        if not ok or not p: return
        n, ok = QInputDialog.getText(self, "New User", "Full name:")
        if not ok: return
        r, ok = QInputDialog.getItem(self, "New User", "Role:",
                                     ["cashier", "manager", "admin"], 0, False)
        if not ok: return
        try:
            self.db.add_user(u.strip(), p, n.strip(), r)
            self.refresh_users()
            Toast(self.window(), "User added", "success")
        except sqlite3.IntegrityError:
            warn(self, "Username already exists")

    def del_user(self, uid):
        if confirm(self, "Delete this user?"):
            self.db.delete_user(uid); self.refresh_users()


# ════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ════════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    def __init__(self, db, user):
        super().__init__()
        self.db = db; self.user = user
        self.setWindowTitle("Pizza POS — Restaurant Management Suite")
        self.resize(1360, 860)
        self.setMinimumSize(1080, 700)

        root = QWidget(); root.setObjectName("root")
        self.setCentralWidget(root)
        h = QHBoxLayout(root); h.setContentsMargins(0, 0, 0, 0); h.setSpacing(0)

        sb = QFrame(); sb.setObjectName("sidebar"); sb.setFixedWidth(76)
        sv = QVBoxLayout(sb); sv.setContentsMargins(10, 14, 10, 14); sv.setSpacing(6)
        logo = QLabel("🍕"); logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("font-size:30px; padding-bottom:10px;")
        sv.addWidget(logo)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        nav_items = [
            ("🍕", "POS"),
            ("📦", "Products"),
            ("👥", "Customers"),
            ("💸", "Expenses"),
            ("📊", "Reports"),
            ("⚙️", "Settings"),
        ]
        for icon, name in nav_items:
            b = QPushButton(icon); b.setObjectName("navItem")
            b.setCheckable(True); b.setFixedSize(52, 52)
            b.setToolTip(name)
            b.clicked.connect(lambda _, n=name: self.switch(n))
            sv.addWidget(b)
            self.nav_group.addButton(b)
        sv.addStretch()

        chip = QFrame(); chip.setObjectName("card")
        cv = QVBoxLayout(chip); cv.setContentsMargins(6, 8, 6, 8); cv.setSpacing(2)
        initials = "".join(w[0].upper() for w in (user["full_name"] or user["username"]).split()[:2])
        av = QLabel(initials); av.setAlignment(Qt.AlignCenter)
        av.setStyleSheet("background:#0f172a; color:#fff; border-radius:16px; "
                         "font-size:12px; font-weight:800;")
        av.setFixedSize(32, 32)
        cv.addWidget(av, alignment=Qt.AlignHCenter)
        sv.addWidget(chip)

        main = QVBoxLayout(); main.setContentsMargins(0, 0, 0, 0); main.setSpacing(0)

        top = QFrame(); top.setObjectName("topbar")
        th = QHBoxLayout(top); th.setContentsMargins(16, 10, 16, 10)
        self.page_title = QLabel("POS"); self.page_title.setObjectName("h1")
        th.addWidget(self.page_title)
        th.addStretch()
        theme_btn = QPushButton("🌓"); theme_btn.setObjectName("iconBtn")
        theme_btn.setToolTip("Toggle theme"); theme_btn.setFixedSize(34, 34)
        theme_btn.clicked.connect(self.toggle_theme)
        th.addWidget(theme_btn)
        who = QLabel(f"{user['full_name'] or user['username']}  •  {user['role']}")
        who.setObjectName("muted"); th.addWidget(who)
        main.addWidget(top)

        self.stack = QStackedWidget()
        self.pages = {}
        self.pages["POS"]       = POSPage(db, user)
        self.pages["Products"]  = ProductsPage(db)
        self.pages["Customers"] = CustomersPage(db)
        self.pages["Expenses"]  = ExpensesPage(db, user)
        self.pages["Reports"]   = ReportsPage(db)
        self.pages["Settings"]  = SettingsPage(db, user)
        self.pages["Settings"].theme_changed.connect(self.apply_theme)
        for p in self.pages.values():
            self.stack.addWidget(p)
        main.addWidget(self.stack, 1)

        h.addWidget(sb)
        h.addLayout(main, 1)

        self.nav_group.buttons()[0].setChecked(True)
        self.switch("POS")

        self.apply_theme(db.get_setting("theme", "light"))

    def switch(self, name):
        self.page_title.setText(name)
        self.stack.setCurrentWidget(self.pages[name])
        if name == "POS":
            self.pages["POS"].reload_customers()
            self.pages["POS"].reload_open_orders()
            self.pages["POS"].refresh_products()
        elif name == "Products":
            self.pages["Products"].refresh()
        elif name == "Customers":
            self.pages["Customers"].refresh()
        elif name == "Expenses":
            self.pages["Expenses"].refresh()
        elif name == "Reports":
            self.pages["Reports"].refresh()

    def apply_theme(self, theme):
        QApplication.instance().setProperty("theme", theme)
        QApplication.instance().setStyleSheet(build_qss(theme))

    def toggle_theme(self):
        cur = self.db.get_setting("theme", "light")
        new = "dark" if cur == "light" else "light"
        self.db.set_setting("theme", new)
        self.apply_theme(new)
        try:
            self.pages["Settings"].theme_cb.setCurrentText(new)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════
#  ENTRY
# ════════════════════════════════════════════════════════════════
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Pizza POS")
    app.setStyle("Fusion")

    base_font = QFont("Inter", 10)
    base_font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(base_font)

    db = Database()
    theme = db.get_setting("theme", "light")
    app.setProperty("theme", theme)
    app.setStyleSheet(build_qss(theme))

    login = LoginDialog(db)
    if login.exec_() != QDialog.Accepted:
        return 0

    win = MainWindow(db, login.user)
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())