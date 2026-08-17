"""精算対象外スタッフの判定（2026-08-17 中野さん指示で追加）

背景:
    社員（正社員・運営側スタッフ）は大会ごとの謝礼精算の対象ではないのに、
    シフトに入っている以上ずっと支払い一覧へ出続けていた。
    臨時調整で¥0にしても行は残り、一括計算を押せば計算し直される。
    NO.1 TAKA・NO.239 りんたろうで実際に発生。

しくみ:
    スタッフの notes 先頭に MARKER を置くだけで、支払い計算・再計算の
    両方から外れる（DDLを触れないため、支払い方法の〔振込〕と同じ方式）。
    出退勤・シフト・打刻はそのまま残るので、勤怠記録は失われない。
"""

from __future__ import annotations

MARKER = "〔精算対象外〕"


def is_excluded(staff: dict) -> bool:
    """このスタッフを大会精算の対象から外すか。"""
    return str((staff or {}).get("notes") or "").startswith(MARKER)


def free_note(staff: dict) -> str:
    """マーカーを除いた本来のメモ部分。"""
    n = str((staff or {}).get("notes") or "")
    return n[len(MARKER):].lstrip() if n.startswith(MARKER) else n


def build_notes(excluded: bool, note: str = "") -> str:
    note = (note or "").strip()
    return (MARKER + note) if excluded else note


def set_excluded(staff_id, excluded: bool, note: str = "",
                 performed_by: str = "") -> bool:
    """精算対象外フラグを切り替える（既存メモは保持）。

    対象外にした場合、その大会の支払いレコードは呼び出し側で消す想定。
    """
    import db
    row = db.get_client().table("p1_staff").select("id, notes").eq(
        "id", staff_id).execute().data
    if not row:
        return False
    keep = note or free_note(row[0])
    db.get_client().table("p1_staff").update(
        {"notes": build_notes(excluded, keep)}).eq("id", staff_id).execute()
    db.log_action("payroll_scope", "staff", staff_id,
                  detail=("精算対象外に設定" if excluded else "精算対象へ戻す")
                         + (f"（{keep}）" if keep else ""),
                  performed_by=performed_by or "system")
    return True
