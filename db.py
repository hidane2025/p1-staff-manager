"""P1 Staff Manager — データベース層 v2"""

import sqlite3
import os
from datetime import datetime
from typing import Optional

# Streamlit Cloud: /tmp に書き込む（アプリディレクトリは読み取り専用）
_LOCAL_DB = os.path.join(os.path.dirname(__file__), "p1_staff.db")
_CLOUD_DB = "/tmp/p1_staff.db"

def _get_db_path():
    """書き込み可能なDBパスを返す"""
    try:
        # ローカルに書き込めるならローカル
        with open(_LOCAL_DB, "a"):
            pass
        return _LOCAL_DB
    except (OSError, IOError):
        # Streamlit Cloud等: /tmpを使用
        return _CLOUD_DB

DB_PATH = _get_db_path()


def get_connection():
    """DB接続を取得"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """テーブル作成（初回のみ）"""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            no INTEGER,
            name_jp TEXT NOT NULL,
            name_en TEXT,
            role TEXT NOT NULL DEFAULT 'Dealer',
            contact TEXT,
            notes TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            venue TEXT,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            break_minutes_6h INTEGER NOT NULL DEFAULT 45,
            break_minutes_8h INTEGER NOT NULL DEFAULT 60,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS event_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            date_label TEXT DEFAULT 'regular',
            hourly_rate INTEGER NOT NULL DEFAULT 1500,
            night_rate INTEGER NOT NULL DEFAULT 1875,
            transport_allowance INTEGER NOT NULL DEFAULT 1000,
            floor_bonus INTEGER NOT NULL DEFAULT 3000,
            mix_bonus INTEGER NOT NULL DEFAULT 1500,
            FOREIGN KEY (event_id) REFERENCES events(id)
        );

        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            staff_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            planned_start TEXT,
            planned_end TEXT,
            actual_start TEXT,
            actual_end TEXT,
            is_mix INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'scheduled',
            FOREIGN KEY (event_id) REFERENCES events(id),
            FOREIGN KEY (staff_id) REFERENCES staff(id),
            UNIQUE(event_id, staff_id, date)
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            staff_id INTEGER NOT NULL,
            base_pay INTEGER NOT NULL DEFAULT 0,
            night_pay INTEGER NOT NULL DEFAULT 0,
            transport_total INTEGER NOT NULL DEFAULT 0,
            floor_bonus_total INTEGER NOT NULL DEFAULT 0,
            mix_bonus_total INTEGER NOT NULL DEFAULT 0,
            attendance_bonus INTEGER NOT NULL DEFAULT 0,
            break_deduction INTEGER NOT NULL DEFAULT 0,
            adjustment INTEGER NOT NULL DEFAULT 0,
            adjustment_note TEXT,
            total_amount INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            approved_by TEXT,
            approved_at TEXT,
            receipt_received INTEGER NOT NULL DEFAULT 0,
            paid_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (event_id) REFERENCES events(id),
            FOREIGN KEY (staff_id) REFERENCES staff(id)
        );

        CREATE TABLE IF NOT EXISTS petty_cash (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            description TEXT NOT NULL,
            amount INTEGER NOT NULL,
            requester TEXT,
            approver TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            receipt_received INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (event_id) REFERENCES events(id)
        );

        CREATE TABLE IF NOT EXISTS cash_pools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            pool_type TEXT NOT NULL,
            initial_amount INTEGER NOT NULL DEFAULT 0,
            current_amount INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (event_id) REFERENCES events(id)
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id INTEGER,
            detail TEXT,
            performed_by TEXT DEFAULT 'system',
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );
    """)
    conn.commit()
    conn.close()


# === Audit Log ===

def log_action(action: str, target_type: str, target_id: int = None,
               detail: str = "", event_id: int = None, performed_by: str = "system"):
    """監査ログを記録"""
    conn = get_connection()
    conn.execute(
        """INSERT INTO audit_log (event_id, action, target_type, target_id, detail, performed_by)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (event_id, action, target_type, target_id, detail, performed_by)
    )
    conn.commit()
    conn.close()


def get_audit_log(event_id: int = None, limit: int = 50):
    """監査ログ取得"""
    conn = get_connection()
    if event_id:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE event_id = ? ORDER BY created_at DESC LIMIT ?",
            (event_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# === Staff CRUD ===

def create_staff(no, name_jp, name_en="", role="Dealer", contact="", notes=""):
    """スタッフ登録"""
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO staff (no, name_jp, name_en, role, contact, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (no, name_jp, name_en, role, contact, notes)
    )
    staff_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return staff_id


def get_all_staff(role_filter=None, search=None):
    """スタッフ一覧取得"""
    conn = get_connection()
    query = "SELECT * FROM staff WHERE is_active = 1"
    params = []
    if role_filter:
        query += " AND role = ?"
        params.append(role_filter)
    if search:
        query += " AND (name_jp LIKE ? OR name_en LIKE ? OR CAST(no AS TEXT) LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    query += " ORDER BY role, no"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_staff_by_id(staff_id):
    """スタッフ1件取得"""
    conn = get_connection()
    row = conn.execute("SELECT * FROM staff WHERE id = ?", (staff_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_staff(staff_id, **kwargs):
    """スタッフ更新"""
    conn = get_connection()
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [staff_id]
    conn.execute(
        f"UPDATE staff SET {fields}, updated_at = datetime('now', 'localtime') WHERE id = ?",
        values
    )
    conn.commit()
    conn.close()


def find_or_create_staff(no, name_jp, name_en="", role="Dealer"):
    """NO.と名前で検索、なければ作成"""
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM staff WHERE no = ? AND name_jp = ?", (no, name_jp)
    ).fetchone()
    if row:
        conn.close()
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO staff (no, name_jp, name_en, role) VALUES (?, ?, ?, ?)",
        (no, name_jp, name_en, role)
    )
    staff_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return staff_id


# === Event CRUD ===

def create_event(name, venue, start_date, end_date,
                 break_minutes_6h=45, break_minutes_8h=60):
    """イベント作成"""
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO events (name, venue, start_date, end_date, break_minutes_6h, break_minutes_8h)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, venue, start_date, end_date, break_minutes_6h, break_minutes_8h)
    )
    event_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return event_id


def get_all_events():
    """イベント一覧"""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM events ORDER BY start_date DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_event_by_id(event_id):
    """イベント1件"""
    conn = get_connection()
    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# === Event Rates ===

def set_event_rate(event_id, date, hourly_rate=1500, night_rate=1875,
                   transport=1000, floor_bonus=3000, mix_bonus=1500,
                   date_label="regular"):
    """日別レート設定"""
    conn = get_connection()
    conn.execute("DELETE FROM event_rates WHERE event_id = ? AND date = ?", (event_id, date))
    conn.execute(
        """INSERT INTO event_rates
           (event_id, date, date_label, hourly_rate, night_rate,
            transport_allowance, floor_bonus, mix_bonus)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, date, date_label, hourly_rate, night_rate, transport, floor_bonus, mix_bonus)
    )
    conn.commit()
    conn.close()


def get_event_rates(event_id):
    """イベントのレート一覧"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM event_rates WHERE event_id = ? ORDER BY date", (event_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# === Shifts ===

def upsert_shift(event_id, staff_id, date, planned_start, planned_end, is_mix=0):
    """シフト登録（既存があれば更新）"""
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM shifts WHERE event_id = ? AND staff_id = ? AND date = ?",
        (event_id, staff_id, date)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE shifts SET planned_start = ?, planned_end = ?, is_mix = ? WHERE id = ?",
            (planned_start, planned_end, is_mix, existing["id"])
        )
    else:
        conn.execute(
            """INSERT INTO shifts (event_id, staff_id, date, planned_start, planned_end, is_mix)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event_id, staff_id, date, planned_start, planned_end, is_mix)
        )
    conn.commit()
    conn.close()


def get_shifts_for_event(event_id, date=None, staff_id=None):
    """イベントのシフト取得"""
    conn = get_connection()
    query = """
        SELECT s.*, st.name_jp, st.name_en, st.no, st.role
        FROM shifts s
        JOIN staff st ON s.staff_id = st.id
        WHERE s.event_id = ?
    """
    params = [event_id]
    if date:
        query += " AND s.date = ?"
        params.append(date)
    if staff_id:
        query += " AND s.staff_id = ?"
        params.append(staff_id)
    query += " ORDER BY st.role, st.no"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def checkin_staff(shift_id, actual_start):
    """チェックイン（既にcheckout済みならactual_endは保持）"""
    conn = get_connection()
    row = conn.execute("SELECT status, actual_end FROM shifts WHERE id = ?", (shift_id,)).fetchone()
    if row and row["actual_end"]:
        conn.execute("UPDATE shifts SET actual_start = ? WHERE id = ?", (actual_start, shift_id))
    else:
        conn.execute(
            "UPDATE shifts SET actual_start = ?, status = 'checked_in' WHERE id = ?",
            (actual_start, shift_id)
        )
    conn.commit()
    conn.close()


def checkout_staff(shift_id, actual_end):
    """チェックアウト"""
    conn = get_connection()
    conn.execute(
        "UPDATE shifts SET actual_end = ?, status = 'checked_out' WHERE id = ?",
        (actual_end, shift_id)
    )
    conn.commit()
    conn.close()


def bulk_checkout(shift_ids: list, actual_end: str, event_id: int = None):
    """一括退勤（凍結対応）"""
    conn = get_connection()
    for sid in shift_ids:
        conn.execute(
            """UPDATE shifts SET actual_end = ?,
               actual_start = COALESCE(actual_start, planned_start),
               status = 'checked_out' WHERE id = ?""",
            (actual_end, sid)
        )
    conn.commit()
    conn.close()
    if event_id:
        log_action("bulk_checkout", "shifts", detail=f"{len(shift_ids)}名を{actual_end}で一括退勤",
                   event_id=event_id)


def mark_absent(shift_id):
    """欠勤にする"""
    conn = get_connection()
    conn.execute(
        "UPDATE shifts SET status = 'absent', actual_start = NULL, actual_end = NULL WHERE id = ?",
        (shift_id,)
    )
    conn.commit()
    conn.close()


def set_shift_mix(shift_id: int, is_mix: int):
    """MIXフラグを切り替え"""
    conn = get_connection()
    conn.execute("UPDATE shifts SET is_mix = ? WHERE id = ?", (is_mix, shift_id))
    conn.commit()
    conn.close()


# === Payments ===

def save_payment(event_id, staff_id, base_pay, night_pay, transport_total,
                 floor_bonus_total, mix_bonus_total, attendance_bonus,
                 total_amount, break_deduction=0, adjustment=0, adjustment_note=""):
    """支払い情報保存（支払済みは上書きしない）"""
    conn = get_connection()
    existing = conn.execute(
        "SELECT id, status FROM payments WHERE event_id = ? AND staff_id = ?",
        (event_id, staff_id)
    ).fetchone()
    if existing and existing["status"] == "paid":
        conn.close()
        return  # 支払済みは上書きしない

    if existing:
        conn.execute("DELETE FROM payments WHERE id = ?", (existing["id"],))

    conn.execute(
        """INSERT INTO payments
           (event_id, staff_id, base_pay, night_pay, transport_total,
            floor_bonus_total, mix_bonus_total, attendance_bonus,
            break_deduction, adjustment, adjustment_note, total_amount)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, staff_id, base_pay, night_pay, transport_total,
         floor_bonus_total, mix_bonus_total, attendance_bonus,
         break_deduction, adjustment, adjustment_note, total_amount)
    )
    conn.commit()
    conn.close()
    log_action("calculate_payment", "payments", staff_id,
               f"合計¥{total_amount:,}", event_id)


def get_payments_for_event(event_id):
    """イベントの全支払い"""
    conn = get_connection()
    rows = conn.execute(
        """SELECT p.*, s.name_jp, s.name_en, s.no, s.role
           FROM payments p
           JOIN staff s ON p.staff_id = s.id
           WHERE p.event_id = ?
           ORDER BY s.role, s.no""",
        (event_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def approve_payment(payment_id: int, approved_by: str, event_id: int = None):
    """支払いを承認"""
    conn = get_connection()
    conn.execute(
        """UPDATE payments SET status = 'approved', approved_by = ?,
           approved_at = datetime('now', 'localtime') WHERE id = ?""",
        (approved_by, payment_id)
    )
    conn.commit()
    conn.close()
    log_action("approve_payment", "payments", payment_id,
               f"承認者: {approved_by}", event_id)


def mark_paid(payment_id: int, event_id: int = None):
    """支払済みにする"""
    conn = get_connection()
    conn.execute(
        "UPDATE payments SET status = 'paid', paid_at = datetime('now', 'localtime') WHERE id = ?",
        (payment_id,)
    )
    conn.commit()
    conn.close()
    log_action("mark_paid", "payments", payment_id, "", event_id)


def mark_receipt_received(payment_id: int, event_id: int = None):
    """領収書受領済み"""
    conn = get_connection()
    conn.execute("UPDATE payments SET receipt_received = 1 WHERE id = ?", (payment_id,))
    conn.commit()
    conn.close()
    log_action("receipt_received", "payments", payment_id, "", event_id)


# === Petty Cash ===

def add_petty_cash(event_id, date, description, amount, requester, approver=""):
    """小口経費追加"""
    conn = get_connection()
    conn.execute(
        """INSERT INTO petty_cash (event_id, date, description, amount, requester, approver)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (event_id, date, description, amount, requester, approver)
    )
    conn.commit()
    conn.close()
    log_action("add_petty_cash", "petty_cash", detail=f"¥{amount:,} {description}", event_id=event_id)


def get_petty_cash_for_event(event_id):
    """イベントの小口経費一覧"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM petty_cash WHERE event_id = ? ORDER BY date, created_at",
        (event_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


init_db()
