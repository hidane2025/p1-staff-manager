"""P1 Staff Manager — 支払い計算ページ v2
承認フロー: 計算 → 承認 → 支払い
領収書連動: 領収書未受領 → 支払い不可
"""

import streamlit as st
import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db
from utils.calculator import calculate_staff_payment
from utils.event_selector import select_event

st.set_page_config(page_title="支払い計算", page_icon="💰", layout="wide")
from utils.ui_helpers import hide_staff_only_pages
from utils.page_layout import apply_global_style, page_header, flow_bar
from utils.admin_guard import require_admin, admin_logout_button, operator_name, is_auth_enabled
apply_global_style()
hide_staff_only_pages()
require_admin(page_name="支払い計算")
admin_logout_button()

page_header("💰 支払い計算", "時給×時間＋深夜＋手当＋精勤を自動計算。承認すると封筒リスト・領収書に進めます。")
flow_bar(active="calc", done=["setup", "input"])

# PII閲覧監査ログ
db.log_action("view_payment_calc", "payments",
              detail="page=支払い計算", performed_by=operator_name())


def _is_same_operator(approved_by, operator) -> bool:
    """承認者文字列（"pit:xxx" 形式も含む）と現在の支払操作者が同一人物かを緩く判定。

    A-4 の職務分掌（SoD）牽制表示に使う。anonymous 同士は比較対象にしない。
    """
    if not approved_by or not operator or operator == "anonymous":
        return False
    a = str(approved_by)
    if a.startswith("pit:"):
        a = a[4:]
    return a.strip() == str(operator).strip()

# --- イベント選択（全ページ共通・session_state共有） ---
event_id = select_event(db.get_all_events(), "イベント選択")
event = db.get_event_by_id(event_id)

# レートと日数
rates = db.get_event_rates(event_id)
total_event_days = len(rates) if rates else 6

rates_by_date = {}
for r in rates:
    rates_by_date[r["date"]] = {
        "hourly": r["hourly_rate"],
        "night": r["night_rate"],
        "transport": r["transport_allowance"],
        "floor_bonus": r["floor_bonus"],
        "mix_bonus": r["mix_bonus"],
    }

# 休憩設定
break_6h = event.get("break_minutes_6h", 45) if event else 45
break_8h = event.get("break_minutes_8h", 60) if event else 60

# --- 計算実行 ---
st.divider()
st.markdown(f"**休憩控除:** 6h超={break_6h}分 / 8h超={break_8h}分")

# A-6: 端数処理（イベント単位）。ここで丸めた確定額が「封筒で渡す現金＝領収書の額面＝
# 年間累計」すべてに共通で反映される。封筒ページ側の個別トグルは廃止（正の二重化を防ぐ）。
_round_opts = {"なし（そのまま）": 0, "100円単位で切り上げ": 100,
               "500円単位で切り上げ": 500, "1000円単位で切り上げ": 1000}
_cur_ru = int((event or {}).get("rounding_unit") or 0)
_ru_labels = list(_round_opts.keys())
_cur_ru_label = next((k for k, v in _round_opts.items() if v == _cur_ru), "なし（そのまま）")
# マイグレ(20260601)未適用だと rounding_unit を保存できず無限リランになるため、
# 未適用環境ではセレクタを無効化し、適用を促す（false-success/rerun の防止）。
_rounding_ok = db.rounding_supported()
_picked_ru_label = st.selectbox(
    "端数処理（封筒・領収書・年間累計に共通反映）",
    _ru_labels, index=_ru_labels.index(_cur_ru_label),
    disabled=not _rounding_ok,
    help="選んだ単位で支払額を切り上げ、その確定額(payable_amount)を封筒・領収書・年間累計"
    "すべてに反映します。封筒で渡す現金と領収書の額面が常に一致します。",
)
if not _rounding_ok:
    st.caption(
        "⚠️ 端数処理を使うにはマイグレーション "
        "`20260601_add_payable_amount_and_rounding.sql` の適用が必要です（未適用のため無効）。"
    )
_picked_ru = _round_opts[_picked_ru_label]
if _rounding_ok and _picked_ru != _cur_ru:
    db.update_event_meta(event_id, rounding_unit=_picked_ru)
    _res = db.recompute_payable_for_event(event_id, _picked_ru)
    _upd = _res.get("updated", 0) if isinstance(_res, dict) else _res
    _inv = _res.get("invalidated", 0) if isinstance(_res, dict) else 0
    _rev = _res.get("reverted", 0) if isinstance(_res, dict) else 0
    st.success(
        f"端数処理を「{_picked_ru_label}」に変更し、未払い {_upd}名 の確定額を更新しました。"
        "（支払済みは確定済みのため変更しません）"
    )
    if _rev:
        st.warning(
            f"⚠️ 確定額が変わった {_rev}名 を**未承認に差し戻しました**（再承認が必要です）。"
            "無承認のまま金額が変わるのを防ぐためです。"
        )
    if _inv:
        st.warning(
            f"⚠️ 確定額が変わった {_inv}名 の**発行済み領収書を無効化**しました。"
            "『領収書発行』ページで**再発行**し、新しいDLリンクを配布してください。"
        )
    st.rerun()

if st.button("🔄 支払い額を計算", type="primary"):
    shifts = db.get_shifts_for_event(event_id)
    if not shifts:
        st.warning("シフトが登録されていません。先にシフト取込を行ってください。")
        st.stop()

    # 支払済み・承認済みスタッフの確認
    existing_payments = db.get_payments_for_event(event_id)
    protected_ids = {p["staff_id"] for p in existing_payments if p["status"] in ("paid", "approved")}
    if protected_ids:
        st.warning(f"⚠️ {len(protected_ids)}名が承認済み/支払済みです。スキップします。")
    # A-5: 既存の臨時調整額を staff 単位で保持し、再計算で消えないよう引き継ぐ。
    adj_map = {p["staff_id"]: int(p.get("adjustment") or 0) for p in existing_payments}
    adjnote_map = {p["staff_id"]: (p.get("adjustment_note") or "") for p in existing_payments}

    # 全スタッフの雇用区分・個別時給をまとめて取得
    all_staff_map = {s["id"]: s for s in db.get_all_staff()}

    # 交通費ルール・領収書請求の取得
    transport_rules = {r["region"]: r for r in db.get_transport_rules(event_id)}
    transport_claims = {c["staff_id"]: c for c in db.get_transport_claims(event_id)}

    def _calc_transport(staff_info: dict, days: int) -> tuple[int | None, str]:
        """新交通費システムでスタッフの交通費を計算

        Returns: (交通費金額 or None, 説明メッセージ)
            Noneの場合は旧システム（rate.transportで日数分）を使う
        """
        if not transport_rules:
            return None, ""  # ルール未設定なら旧ロジック
        region = staff_info.get("region")
        if not region or region not in transport_rules:
            return 0, "住所未登録または圏外のため交通費0"
        rule = transport_rules[region]
        if rule.get("is_venue_region"):
            # 開催地: 一律 max_amount × 日数
            return int(rule.get("max_amount", 0) or 0) * days, "開催地一律"
        # 圏外: 領収書金額
        claim = transport_claims.get(staff_info.get("id"))
        if claim and claim.get("has_receipt"):
            return int(claim.get("approved_amount") or 0), "領収書確定"
        return 0, "領収書未提出のため0"

    # スタッフごとにグループ化
    staff_shifts = {}
    for s in shifts:
        key = s["staff_id"]
        if key not in staff_shifts:
            staff_info = all_staff_map.get(key, {})
            staff_shifts[key] = {
                "name": s["name_jp"],
                "role": s["role"],
                "shifts": [],
                "employment_type": staff_info.get("employment_type") or "contractor",
                "custom_hourly_rate": staff_info.get("custom_hourly_rate"),
                "staff_info": staff_info,
            }
        if s["status"] == "absent":
            continue
        if s["planned_start"] and s["planned_end"]:
            start = s.get("actual_start") or s["planned_start"]
            end = s.get("actual_end") or s["planned_end"]
            staff_shifts[key]["shifts"].append({
                "date": s["date"],
                "start": start,
                "end": end,
                "is_mix": bool(s.get("is_mix", 0)),
            })

    results = []
    skipped = 0
    for staff_id, data in staff_shifts.items():
        if staff_id in protected_ids:
            skipped += 1
            continue
        # 新交通費システム（あれば）
        days = len(data["shifts"])
        transport_override, _msg = _calc_transport(data["staff_info"], days)
        # Phase 3-I (2026-05-08): 個別手当を計算に含める
        indiv_allowances = db.get_individual_allowances(event_id, staff_id)
        payment = calculate_staff_payment(
            staff_id=staff_id, name=data["name"], role=data["role"],
            shifts=data["shifts"], rates_by_date=rates_by_date,
            total_event_days=total_event_days,
            break_6h=break_6h, break_8h=break_8h,
            employment_type=data["employment_type"],
            custom_hourly_rate=data["custom_hourly_rate"],
            transport_override=transport_override,
            individual_allowances=indiv_allowances,
            adjustment=adj_map.get(staff_id, 0),  # A-5: 既存の臨時調整を引き継ぐ
        )
        # Codex P2 fix #3: 個別手当合計をDBに保存（合計と内訳の整合性確保）
        _allowance_subtotal = getattr(payment, "individual_allowance_total", 0)
        results.append(payment)
        db.save_payment(
            event_id=event_id, staff_id=staff_id,
            base_pay=payment.base_pay, night_pay=payment.night_pay,
            transport_total=payment.transport_total,
            floor_bonus_total=payment.floor_bonus_total,
            mix_bonus_total=payment.mix_bonus_total,
            attendance_bonus=payment.attendance_bonus,
            break_deduction=payment.break_deduction,
            total_amount=payment.total_amount,
            adjustment=getattr(payment, "adjustment", 0),  # A-5
            adjustment_note=adjnote_map.get(staff_id, ""),
            individual_allowance_total=_allowance_subtotal,
        )

    msg = f"{len(results)}名の支払い額を計算・保存しました"
    if skipped:
        msg += f"（承認/支払済み{skipped}名はスキップ）"
    st.success(msg)

# --- 結果表示 ---
payments = db.get_payments_for_event(event_id)

if not payments:
    st.info("支払いデータがありません。上の「支払い額を計算」ボタンを押してください。")
    st.stop()

# --- サマリー ---
st.subheader("支払い一覧")
# A-6: 表示金額は保存済みの確定額(payable_amount)に統一。端数処理は上の
# 「端数処理」セレクトボックス（イベント単位・save時に payable へ反映）が唯一の制御。
# 旧・表示専用の per-view 丸めUIは、封筒/領収書との不一致の原因だったため撤去。
total_all = sum(p["total_amount"] for p in payments)          # 丸め前の素の合計
total_payable = sum(db.get_payable(p) for p in payments)      # 確定額（封筒・領収書と一致）
pending_count = sum(1 for p in payments if p["status"] == "pending")
approved_count = sum(1 for p in payments if p["status"] == "approved")
paid_count = sum(1 for p in payments if p["status"] == "paid")

col1, col2, col3, col4 = st.columns(4)
col1.metric(
    "総支払額（確定）", f"¥{total_payable:,}",
    delta=f"端数調整 +¥{total_payable - total_all:,}" if total_payable != total_all else None,
    help="封筒で渡す現金・領収書の額面・年間累計と一致する確定額（端数処理反映後）。",
)
col2.metric("丸め前合計", f"¥{total_all:,}")
col3.metric("⏳ 未承認", f"{pending_count}名")
col4.metric("💴 支払済", f"{paid_count}名")

col5, col6 = st.columns(2)
col5.metric("✅ 承認済", f"{approved_count}名")
col6.metric("対象人数", f"{len(payments)}名")

st.divider()
st.markdown("**支払い内訳合計:**")
row1 = st.columns(3)
row1[0].metric("基本給", f"¥{sum(p['base_pay'] for p in payments):,}")
row1[1].metric("深夜手当", f"¥{sum(p['night_pay'] for p in payments):,}")
row1[2].metric("交通費", f"¥{sum(p['transport_total'] for p in payments):,}")
row2 = st.columns(3)
row2[0].metric("フロア手当", f"¥{sum(p['floor_bonus_total'] for p in payments):,}")
row2[1].metric("MIX手当", f"¥{sum(p['mix_bonus_total'] for p in payments):,}")
row2[2].metric("精勤手当", f"¥{sum(p['attendance_bonus'] for p in payments):,}")

# Codex 4回目 P2 #10 fix (2026-05-09): 個別手当合計を内訳に表示
# （表示の一貫性確保。封筒リスト・精算レポートと同じ並び）
_total_allowance = sum(int(p.get("individual_allowance_total") or 0) for p in payments)
if _total_allowance > 0:
    st.metric("🎁 個別手当", f"¥{_total_allowance:,}",
              help="言語手当・人材確保手当 等の個別付与分。"
              "オフレコ含む合計（明細は『個別手当』ページで管理者のみ確認可）。")

# 休憩控除合計
total_break = sum(p.get("break_deduction", 0) for p in payments)
if total_break > 0:
    st.info(f"休憩控除合計: ¥{total_break:,}（基本給から控除済み）")

st.divider()

# --- 承認フロー ---
st.subheader("承認・支払い")
st.markdown("""
**フロー:** 計算（⏳未承認）→ 承認（✅承認済）→ 領収書受領 → 支払い（💴支払済）
""")

# 承認者 = ログイン中の認証オペレーター（A-4: 自由入力を廃し本人性を担保）
# 旧版は自由入力テキストで他人名を詐称でき、承認ログが実操作者を担保しなかった。
approver = operator_name()
# 監査証跡に残らない（実操作者を特定できない）セッションの判定。
# admin_guard はログイン時にオペレーター名未入力だと "anonymous_admin"、
# 未認証なら "anonymous" を返すため、両方を「実操作者なし」として扱う。
_NON_ATTRIBUTABLE_OPERATORS = {"", "anonymous", "anonymous_admin"}
# パスワードレス運用（ADMIN_PASSWORD 未設定の dev/fallback）ではログインフォーム
# 自体が無くオペレーター名を入力できない。その環境で gate すると承認・支払が
# 一切できなくなるため、認証が有効なときだけ実操作者を必須化する。
_auth_enabled = is_auth_enabled()
# 空白のみ等も非帰属として扱う（admin_guard 側でも strip 済みだが二重防御）。
operator_ok = (not _auth_enabled) or (
    (approver or "").strip() not in _NON_ATTRIBUTABLE_OPERATORS
)
if not operator_ok:
    st.warning(
        "⚠️ ログイン時に**オペレーター名**が未入力のため、承認者・支払実行者を"
        "監査ログに記録できません。内部統制のため、承認・支払ボタンは無効化しています。"
        "一度ログアウトし、**オペレーター名を入力して再ログイン**してください。"
    )
elif _auth_enabled:
    st.caption(f"承認者・支払実行者として記録される操作者: **{approver}**（ログインセッション）")
else:
    st.caption("（パスワードレス運用のため、操作者は記録されません。本番では ADMIN_PASSWORD を設定してください）")

col_approve, col_pay = st.columns(2)

with col_approve:
    pending_payments = [p for p in payments if p["status"] == "pending"]
    if pending_payments and operator_ok:
        if st.button(f"✅ 未承認{len(pending_payments)}名を一括承認", type="primary"):
            approved_n = sum(
                1 for p in pending_payments
                if db.approve_payment(p["id"], approver, event_id)
            )
            st.success(f"{approved_n}名を承認しました（承認者: {approver}）")
            if approved_n < len(pending_payments):
                st.warning(
                    f"{len(pending_payments) - approved_n}名は状態が変わりませんでした"
                    "（既に承認済み、または他の端末と競合した可能性）。"
                )
            st.rerun()
    elif pending_payments and not operator_ok:
        st.info("未承認の支払いがあります。オペレーター名を設定して再ログインすると承認できます。")

with col_pay:
    approved_payments = [p for p in payments if p["status"] == "approved"]
    payable = [p for p in approved_payments if p["receipt_received"]]
    not_payable = [p for p in approved_payments if not p["receipt_received"]]
    if payable:
        bulk_pay_key = "__confirm_bulk_paid"
        # A-4 SoD牽制: 承認者と支払実行者(=今の操作者)が同一になる件数を事前表示
        _self_pay = sum(
            1 for p in payable
            if _is_same_operator(p.get("approved_by"), approver)
        )
        if st.session_state.get(bulk_pay_key) and not operator_ok:
            # 確認フラグ設定後にオペレーター名なしへ変わった場合（ログアウト→再ログイン等）、
            # gate を迂回して支払確定しないよう、残留フラグを破棄する。
            st.session_state[bulk_pay_key] = False
        if st.session_state.get(bulk_pay_key):
            _sod_note = (
                f"\n\n⚠️ うち **{_self_pay}名** は承認者と支払実行者が同一（自己承認→自己支払）です。"
                "可能なら承認者と別の担当者が支払を実行してください（牽制）。"
                if _self_pay else ""
            )
            st.warning(
                f"⚠️ {len(payable)}名を **支払済み** に変更します。"
                f"支払済みにすると後から元に戻せません（DB直操作が必要）。"
                f"支払実行者として **{approver}** が記録されます。本当によろしいですか？"
                f"{_sod_note}"
            )
            cy, cn = st.columns(2)
            if cy.button("✅ 確定して支払済みにする", type="primary",
                          key="confirm_bulk_paid_yes"):
                paid_n, noop_n = 0, 0
                try:
                    for p in payable:
                        if db.mark_paid(p["id"], event_id, performed_by=approver):
                            paid_n += 1
                        else:
                            noop_n += 1
                    st.success(f"✅ {paid_n}名を支払済みにしました（支払実行者: {approver}）")
                    if noop_n:
                        st.warning(
                            f"{noop_n}名は状態が変わりませんでした"
                            "（既に支払済み、または他の端末と競合した可能性）。"
                        )
                except Exception as e:
                    st.error("💥 一部の更新に失敗しました。該当スタッフを手動で確認してください。")
                    with st.expander("🔧 技術詳細"):
                        st.code(str(e))
                st.session_state[bulk_pay_key] = False
                st.rerun()
            if cn.button("❌ キャンセル", key="confirm_bulk_paid_no"):
                st.session_state[bulk_pay_key] = False
                st.rerun()
        else:
            if operator_ok:
                if st.button(f"💴 承認済み＋領収書受領済みの{len(payable)}名を支払済みに"):
                    st.session_state[bulk_pay_key] = True
                    st.rerun()
            else:
                st.info(
                    f"支払い可能な{len(payable)}名がいます。"
                    "オペレーター名を設定して再ログインすると支払実行できます。"
                )
    if not_payable:
        st.warning(f"⚠️ {len(not_payable)}名が承認済みだが領収書未受領のため支払い不可")

st.divider()

# --- フィルタ ---
col_f1, col_f2, col_f3 = st.columns([2, 1, 1])
with col_f1:
    search = st.text_input("🔍 名前で検索", key="payment_search")
with col_f2:
    role_filter = st.selectbox("役職", ["すべて", "Dealer", "Floor", "TD", "DC", "Chip"], key="payment_role")
with col_f3:
    status_filter = st.selectbox("状態", ["すべて", "⏳ 未承認", "✅ 承認済", "💴 支払済"], key="payment_status")

filtered = payments
if search:
    filtered = [p for p in filtered if search.lower() in p["name_jp"].lower()]
if role_filter != "すべて":
    filtered = [p for p in filtered if p["role"] == role_filter]
status_map = {"⏳ 未承認": "pending", "✅ 承認済": "approved", "💴 支払済": "paid"}
if status_filter != "すべて":
    filtered = [p for p in filtered if p["status"] == status_map[status_filter]]

# --- テーブル ---
# Codex 4回目 P2 #10 fix (2026-05-09): 個別手当列を追加して内訳と合計を一致させる
# （列が増えすぎないよう、誰かに個別手当があるイベントだけ列を出す）
_show_allowance_column = any(
    int(p.get("individual_allowance_total") or 0) > 0 for p in payments
)
_show_adjustment_column = any(int(p.get("adjustment") or 0) != 0 for p in payments)
# A-6: 端数処理が効いている（確定額≠丸め前）場合のみ「確定額」列を出す
_any_rounded = any(db.get_payable(p) != p["total_amount"] for p in payments)

display_data = []
for p in filtered:
    status_icon = {"pending": "⏳ 未承認", "approved": "✅ 承認済", "paid": "💴 支払済"}.get(p["status"], p["status"])
    row = {
        "NO.": p["no"], "名前": p["name_jp"], "役職": p["role"],
        "基本給": f"¥{p['base_pay']:,}", "深夜": f"¥{p['night_pay']:,}",
        "交通費": f"¥{p['transport_total']:,}", "Floor": f"¥{p['floor_bonus_total']:,}",
        "MIX": f"¥{p['mix_bonus_total']:,}", "精勤": f"¥{p['attendance_bonus']:,}",
    }
    if _show_allowance_column:
        row["個別手当"] = f"¥{int(p.get('individual_allowance_total') or 0):,}"
    if _show_adjustment_column:
        row["臨時調整"] = f"¥{int(p.get('adjustment') or 0):,}"
    row["合計"] = f"¥{p['total_amount']:,}"
    if _any_rounded:
        row["確定額"] = f"¥{db.get_payable(p):,}"
    row["状態"] = status_icon
    row["領収書"] = "✅" if p["receipt_received"] else "❌"
    display_data.append(row)

st.dataframe(pd.DataFrame(display_data), use_container_width=True, hide_index=True)

# 個別手当を CSV にも含める（精算レポート/封筒リストと整合）
if _show_allowance_column:
    st.caption(
        "💡 個別手当列が表示されています。詳細は『🎁 個別手当』ページで確認可（管理者のみ）。"
    )

# --- 個別操作 ---
st.divider()
st.subheader("個別スタッフ操作")
staff_opts = {f"NO.{p['no']} {p['name_jp']} ({p['role']}) — ¥{db.get_payable(p):,}": p for p in filtered}
if staff_opts:
    sel = st.selectbox("スタッフを選択", list(staff_opts.keys()))
    p = staff_opts[sel]

    col_d1, col_d2 = st.columns(2)
    with col_d1:
        # A-5/A-6: 個別手当・臨時調整を内訳行に出し、確定額(payable)も明示。
        # 内訳の総和 = 合計、合計 + 端数調整 = 確定額 が常に成立する。
        _allow = int(p.get("individual_allowance_total") or 0)
        _allow_row = f"| 個別手当 | ¥{_allow:,} |\n" if _allow else ""
        _adj = int(p.get("adjustment") or 0)
        _adj_row = (
            f"| 臨時調整 | {'+' if _adj >= 0 else '-'}¥{abs(_adj):,} |\n" if _adj else ""
        )
        _payable = db.get_payable(p)
        _payable_row = (
            f"| **確定額（端数処理後）** | **¥{_payable:,}**"
            f"（端数調整 +¥{_payable - p['total_amount']:,}） |\n"
            if _payable != p["total_amount"] else ""
        )
        st.markdown(f"""
**{p['name_jp']}** (NO.{p['no']}) — {p['role']}

| 項目 | 金額 |
|------|------|
| 基本給 | ¥{p['base_pay']:,} |
| 深夜手当 | ¥{p['night_pay']:,} |
| 休憩控除 | -¥{p.get('break_deduction', 0):,} |
| 交通費 | ¥{p['transport_total']:,} |
| フロア手当 | ¥{p['floor_bonus_total']:,} |
| MIX手当 | ¥{p['mix_bonus_total']:,} |
| 精勤手当 | ¥{p['attendance_bonus']:,} |
{_allow_row}{_adj_row}| **合計** | **¥{p['total_amount']:,}** |
{_payable_row}
承認者: {p.get('approved_by') or '未承認'}
""")

    with col_d2:
        # 承認（承認者はログイン中の operator に束縛済み）
        if p["status"] == "pending":
            if operator_ok:
                if st.button("✅ この人を承認", key=f"approve_{p['id']}"):
                    if db.approve_payment(p["id"], approver, event_id):
                        st.success(f"{p['name_jp']} を承認しました（承認者: {approver}）")
                    else:
                        st.warning(f"{p['name_jp']} は状態が変わりませんでした（既に承認済み/競合）")
                    st.rerun()
            else:
                st.caption("⚠️ 承認にはオペレーター名の設定（再ログイン）が必要です")

        # 領収書
        if not p["receipt_received"]:
            if st.button("🧾 領収書受領済み", key=f"receipt_{p['id']}"):
                db.mark_receipt_received(p["id"], event_id, performed_by=approver)
                st.success(f"{p['name_jp']} の領収書を受領しました")
                st.rerun()
        else:
            st.success("領収書受領済み ✅")

        # 支払い（承認済み＋領収書受領済みのみ）
        if p["status"] == "approved":
            if p["receipt_received"]:
                pay_conf_key = f"__confirm_pay_{p['id']}"
                if st.session_state.get(pay_conf_key) and not operator_ok:
                    # 残留した確認フラグで gate を迂回しないよう破棄（bulk と同様）。
                    st.session_state[pay_conf_key] = False
                if st.session_state.get(pay_conf_key):
                    _self = _is_same_operator(p.get("approved_by"), approver)
                    st.warning(
                        f"⚠️ {p['name_jp']} を支払済みにします。元に戻せません。"
                        f"支払実行者として **{approver}** が記録されます。"
                        + ("\n\n⚠️ 承認者と支払実行者が同一です（自己承認→自己支払）。"
                           if _self else "")
                    )
                    cy2, cn2 = st.columns(2)
                    if cy2.button("✅ 確定", key=f"y_{p['id']}", type="primary"):
                        try:
                            if db.mark_paid(p["id"], event_id, performed_by=approver):
                                st.success(f"{p['name_jp']} を支払済みにしました（支払実行者: {approver}）")
                            else:
                                st.warning(f"{p['name_jp']} は状態が変わりませんでした（既に支払済み/競合）")
                        except Exception as e:
                            st.error("更新失敗。もう一度お試しください。")
                        st.session_state[pay_conf_key] = False
                        st.rerun()
                    if cn2.button("❌ 取消", key=f"n_{p['id']}"):
                        st.session_state[pay_conf_key] = False
                        st.rerun()
                else:
                    if operator_ok:
                        if st.button("💴 支払済みにする", key=f"pay_{p['id']}"):
                            st.session_state[pay_conf_key] = True
                            st.rerun()
                    else:
                        st.caption("⚠️ 支払にはオペレーター名の設定（再ログイン）が必要です")
            else:
                st.error("❌ 領収書が未受領のため支払いできません")
        elif p["status"] == "paid":
            st.success("支払済み 💴")

        # A-5: 臨時調整額の編集（イレギュラー手当を正式な計算項目として記録）
        # 内部統制上、編集できるのは未承認(pending)のみ。承認後は再承認の牽制を効かせるため、
        # 変更したい場合は一旦未承認に戻す運用にする。
        st.divider()
        st.markdown("**➕ 臨時調整（±）**")
        _cur_adj = int(p.get("adjustment") or 0)
        if p["status"] != "pending":
            st.caption(
                f"現在の臨時調整: ¥{_cur_adj:,}"
                f"（{'支払済' if p['status'] == 'paid' else '承認済'}のため編集不可。"
                "変更するには未承認に戻してください）"
            )
        elif not operator_ok:
            st.caption("⚠️ 臨時調整の編集にはオペレーター名の設定（再ログイン）が必要です")
        else:
            with st.form(f"adj_form_{p['id']}"):
                _adj_val = st.number_input(
                    "臨時調整額（円・マイナス可）",
                    value=_cur_adj, step=500, format="%d",
                    help="深夜の急な残業・立替の戻し等。入れた額が合計・確定額・封筒・領収書に反映されます。",
                )
                _adj_note = st.text_input(
                    "調整理由（任意）", value=(p.get("adjustment_note") or ""),
                    placeholder="例: 深夜の急な残業代",
                )
                if st.form_submit_button("➕ 調整を適用", type="primary"):
                    if db.set_payment_adjustment(
                        p["id"], int(_adj_val), _adj_note,
                        event_id=event_id, performed_by=approver,
                    ):
                        st.success(
                            f"{p['name_jp']} の臨時調整を ¥{int(_adj_val):,} に更新しました"
                        )
                        st.rerun()
                    else:
                        st.warning("支払済みのため変更できません（または対象なし）")

        # 領収書PDF発行
        st.divider()
        st.markdown("**📄 領収書PDF**")
        staff_info = db.get_staff_by_id(p["staff_id"])
        if staff_info and staff_info.get("real_name") and staff_info.get("address"):
            from utils.receipt import generate_receipt_pdf
            from utils import receipt_db as _receipt_db
            event_info = db.get_event_by_id(event_id)
            _issuer_settings = _receipt_db.get_issuer_settings(event_id)
            try:
                pdf_bytes = generate_receipt_pdf(
                    receipt_no=f"P1-{event_id}-{p['id']}",
                    real_name=staff_info["real_name"],
                    address=staff_info["address"],
                    email=staff_info.get("email") or "",
                    amount=db.get_payable(p),  # A-6: 領収書額面＝確定額（封筒の現金と一致）
                    event_name=event_info["name"] if event_info else "P1大会",
                    issue_date=event_info["end_date"] if event_info else "",
                    # 2026-05-25 構造逆転対応: 宛名はイベント設定の「支払者」情報。
                    # legacy値・空値フォールバックは receipt_db.resolve_payer_name で処理。
                    payer_name=_receipt_db.resolve_payer_name(
                        _issuer_settings.get("issuer_name") or ""
                    ),
                    payer_address=_issuer_settings.get("issuer_address") or "",
                    purpose=(_issuer_settings.get("receipt_purpose")
                             or "ポーカー大会運営業務委託費として"),
                )
                st.download_button(
                    "📥 領収書PDFダウンロード",
                    pdf_bytes,
                    f"receipt_{p['name_jp']}_{p['id']}.pdf",
                    "application/pdf",
                    key=f"receipt_pdf_{p['id']}",
                )
            except Exception as e:
                st.warning(f"領収書生成エラー: {e}")
        else:
            missing = []
            if not (staff_info and staff_info.get("real_name")):
                missing.append("本名")
            if not (staff_info and staff_info.get("address")):
                missing.append("住所")
            col_warn, col_link = st.columns([3, 1])
            col_warn.warning(f"⚠️ {' と '.join(missing)}が未登録のため領収書PDFを発行できません")
            col_link.page_link("pages/1_スタッフ管理.py", label="▶ スタッフ管理へ", icon="📋")

    # --- 備考欄 ---
    st.divider()
    st.markdown("**📝 備考（イレギュラー対応等）**")
    current_note = p.get("notes") or p.get("adjustment_note") or ""
    new_note = st.text_area(
        "備考", value=current_note, key=f"note_{p['id']}",
        placeholder="例: 体調不良で早退、深夜急な残業代として+5,000円",
    )
    if st.button("💾 備考を保存", key=f"save_note_{p['id']}"):
        db.get_client().table("p1_payments").update({"notes": new_note}).eq("id", p["id"]).execute()
        st.success("備考を保存しました")
        st.rerun()

# --- 監査ログ ---
st.divider()
st.subheader("📝 操作ログ（直近20件）")
logs = db.get_audit_log(event_id=event_id, limit=20)
if logs:
    log_display = [{
        "日時": l["created_at"],
        "操作": l["action"],
        "対象": l["target_type"],
        "詳細": l["detail"] or "",
        "実行者": l["performed_by"],
    } for l in logs]
    st.dataframe(pd.DataFrame(log_display), use_container_width=True, hide_index=True)
else:
    st.info("操作ログはまだありません")
