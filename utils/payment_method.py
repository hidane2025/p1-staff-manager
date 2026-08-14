"""支払い方法（現金／後日振込）の管理。

2026-08-14 中野さん指示「現金支払いの方、後日振込者などスタッフによって
バラバラなのでそこも経理側が管理できるようにしたい」。

DBに列を追加できない（SQLアクセスなし）ため、p1_payments.notes の先頭に
マーカー `〔振込〕` を置く方式にする。
- save_payment は既存 notes を保持するため、再計算でもマーカーは消えない
- notes の残り部分は従来どおり自由メモとして共存する
"""

from __future__ import annotations

MARKER = "〔振込〕"

# 状態表示（statusと方法の組み合わせ）
STATE_LABELS = {
    ("pending", "cash"): "⏳ 金額変動中（打刻待ち）",
    ("pending", "transfer"): "⏳ 金額変動中（振込予定）",
    ("approved", "cash"): "💴 現金支払い待ち（金額確定）",
    ("approved", "transfer"): "🏦 振込待ち（金額確定）",
    ("paid", "cash"): "✅ 現金支払い済み",
    ("paid", "transfer"): "✅ 振込済み",
}


def method_of(payment: dict) -> str:
    """'cash' | 'transfer'"""
    return "transfer" if (payment.get("notes") or "").startswith(MARKER) else "cash"


def state_label(payment: dict) -> str:
    return STATE_LABELS.get(
        (payment.get("status") or "pending", method_of(payment)),
        f"{payment.get('status')}")


def free_note(payment: dict) -> str:
    """マーカーを除いた自由メモ部分。"""
    n = payment.get("notes") or ""
    return n[len(MARKER):].lstrip() if n.startswith(MARKER) else n


def build_notes(method: str, note: str) -> str:
    note = (note or "").strip()
    return (MARKER + note) if method == "transfer" else note


def set_method(payment_id, method: str, performed_by: str = "") -> bool:
    """支払い方法を切り替える（notesの自由メモ部分は保持）。"""
    import db
    client = db.get_client()
    rows = client.table("p1_payments").select(
        "id, notes, status").eq("id", payment_id).execute().data
    if not rows:
        return False
    cur = rows[0]
    new_notes = build_notes(method, free_note(cur))
    client.table("p1_payments").update(
        {"notes": new_notes}).eq("id", payment_id).execute()
    try:
        db.log_action("payment_method_set", "payments", payment_id,
                      detail=f"支払い方法 → {'後日振込' if method == 'transfer' else '現金'}",
                      performed_by=performed_by or "system")
    except Exception:
        pass
    return True
