"""P1 Staff Manager — 個別手当管理（v3.9 Phase 3-I）

【役割】
スタッフごとに個別の手当（言語手当・人材確保手当・リーダー手当 等）を
イベント単位で付与・取消する画面。**管理者専用**。

【オフレコ運用】
is_off_record=1 の手当は、ピット端末では金額・件数が伏せられ、
給与支給時の管理画面（このページ）でのみ詳細が見える。

【支払い計算との連動】
支払い計算（pages/3_支払い計算.py）と ピット端末（pages/10_ピット端末.py）が、
calculate_staff_payment() の individual_allowances 引数に
本テーブルから取得した手当リストを渡して合算する。
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pandas as pd
import streamlit as st

import db
from utils.event_selector import select_event
from utils.ui_helpers import hide_staff_only_pages
from utils.page_layout import (
    apply_global_style, page_header, flow_bar, section_header, kpi_row,
)
from utils.admin_guard import require_admin, admin_logout_button, operator_name


st.set_page_config(page_title="個別手当", page_icon="🎁", layout="wide")
apply_global_style()
hide_staff_only_pages()
require_admin(page_name="個別手当管理")
admin_logout_button()

page_header(
    "🎁 個別手当 管理",
    "言語手当・人材確保手当・リーダー手当 等を、スタッフ×イベント単位で付与・取消。"
    "オフレコ手当はピット端末では金額が伏せられます。",
)
flow_bar(active="payout", done=["setup", "input", "calc"])

# 監査ログ（PII相当の閲覧）
db.log_action(
    "view_individual_allowances", "allowances",
    detail="page=個別手当", performed_by=operator_name(),
)


# ============================================================
# 1. イベント選択
# ============================================================
events = db.get_all_events()
if not events:
    st.warning("⚠️ イベントが未作成です。先に「📋 イベント設定」で作成してください。")
    st.stop()

event_id = select_event(events, "対象イベント")
event = db.get_event_by_id(event_id) or {}

st.markdown(
    f"📍 **{event.get('name', '—')}** "
    f"（{event.get('start_date', '—')} 〜 {event.get('end_date', '—')}）"
)

# マイグレ未実行警告
from utils import db_schema
if not db_schema.has_column("p1_staff_event_allowances", "id"):
    st.error(
        "❌ DBマイグレーション `20260508_add_individual_allowances.sql` が未実行です。"
        "Supabase SQL Editor で実行してから本ページを利用してください。"
        "未実行のままだと手当の追加・表示はできません。",
        icon="🛠",
    )
    st.stop()


# ============================================================
# 2. 既存手当の一覧
# ============================================================
section_header(
    "現在のイベントに付与済みの個別手当",
    f"このイベントで付与されている個別手当の一覧。誰がいくらの手当を持っているか確認できます。",
)

all_allowances = db.get_individual_allowances(event_id) or []
all_staff = {s["id"]: s for s in db.get_all_staff()}

if not all_allowances:
    st.info("まだ個別手当は付与されていません。下のフォームから追加できます。")
else:
    # 付与状況を一覧化
    rows = []
    for a in all_allowances:
        staff = all_staff.get(a.get("staff_id"), {})
        rows.append({
            "ID": a.get("id"),
            "NO.": staff.get("no", "?"),
            "名前": staff.get("name_jp", "—"),
            "種別": db._allowance_default_label(a.get("allowance_type", "other")),
            "ラベル": a.get("label", ""),
            "金額": f"¥{int(a.get('amount') or 0):,}",
            "オフレコ": "🔒" if a.get("is_off_record") else "",
            "メモ": a.get("note", ""),
            "付与者": a.get("created_by", ""),
            "付与日時": (a.get("created_at") or "")[:16],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # サマリ KPI
    total_amount = sum(int(a.get("amount") or 0) for a in all_allowances)
    open_amount = sum(int(a.get("amount") or 0)
                      for a in all_allowances if not a.get("is_off_record"))
    off_amount = total_amount - open_amount
    kpi_row([
        {"label": "合計手当額", "value": f"¥{total_amount:,}", "accent": True},
        {"label": "通常手当", "value": f"¥{open_amount:,}",
         "detail": f"{sum(1 for a in all_allowances if not a.get('is_off_record'))}件"},
        {"label": "オフレコ手当", "value": f"¥{off_amount:,}",
         "detail": f"{sum(1 for a in all_allowances if a.get('is_off_record'))}件"},
    ])


# ============================================================
# 3. 個別手当を追加
# ============================================================
section_header("✨ 新規追加", "スタッフを選んで手当を付与します。")

ALLOWANCE_TYPES = {
    "language": "言語手当（中国語・韓国語・英語等）",
    "recruitment": "人材確保手当",
    "leadership": "リーダー手当（シフトリーダー・TD補佐等）",
    "other": "その他（自由記入）",
}

with st.form("add_allowance_form", clear_on_submit=True):
    col_t1, col_t2 = st.columns([1, 1])
    with col_t1:
        # スタッフ選択
        staff_options_dict = {
            f"NO.{s.get('no', '?')} {s.get('name_jp', '')} ({s.get('role', '')})": s["id"]
            for s in all_staff.values()
        }
        if not staff_options_dict:
            st.error("登録スタッフがいません")
            st.stop()
        sel_staff_label = st.selectbox(
            "スタッフを選択",
            list(staff_options_dict.keys()),
        )
        sel_staff_id = staff_options_dict[sel_staff_label]

        sel_type = st.selectbox(
            "手当の種類",
            list(ALLOWANCE_TYPES.keys()),
            format_func=lambda k: ALLOWANCE_TYPES[k],
        )

    with col_t2:
        sel_label = st.text_input(
            "ラベル（任意）",
            placeholder="例: 中国語対応 / TDサブ",
            help="このスタッフ・この手当の具体的な名前。空欄なら種類のデフォルト名が入ります。",
        )
        sel_amount = st.number_input(
            "金額（円）",
            min_value=0, step=1000,
            help="このスタッフに加算する金額（イベント全期間の合計）",
        )
        sel_off_record = st.checkbox(
            "🔒 オフレコ扱いにする",
            value=False,
            help="チェックするとピット端末では金額が伏せられます。"
            "金額・内訳は本ページ（管理者専用）でのみ閲覧可能。",
        )

    sel_note = st.text_input(
        "メモ（任意）",
        placeholder="例: 中国人ディーラー対応で配置したため / 緊急の人材確保で参加",
    )

    submitted = st.form_submit_button("✅ この内容で追加", type="primary")

    if submitted:
        if sel_amount <= 0:
            st.error("金額は1円以上で入れてください。")
        else:
            aid = db.add_individual_allowance(
                event_id=event_id,
                staff_id=sel_staff_id,
                allowance_type=sel_type,
                amount=int(sel_amount),
                label=sel_label,
                is_off_record=int(sel_off_record),
                note=sel_note,
                created_by=operator_name(),
            )
            if aid:
                st.success(
                    f"✅ {sel_staff_label} に "
                    f"{ALLOWANCE_TYPES[sel_type]} ¥{int(sel_amount):,} を追加しました"
                    + (" 🔒 (オフレコ)" if sel_off_record else "")
                )
                # 該当する支払いがあれば未承認に戻す（再計算が必要）
                db.reset_payment_to_pending(
                    event_id, sel_staff_id, reason=f"個別手当追加: {sel_type}"
                )
                st.info(
                    "💡 該当スタッフの支払いがあれば未承認に戻しました。"
                    "「💰 支払い計算」で再計算してください。"
                )
                st.rerun()


# ============================================================
# 4. 個別手当を取消
# ============================================================
if all_allowances:
    section_header(
        "🗑 取消",
        "誤って追加した手当を取り消します（取消は監査ログに残ります）。",
    )
    remove_options = {
        f"ID {a['id']}: "
        f"NO.{all_staff.get(a.get('staff_id'), {}).get('no', '?')} "
        f"{all_staff.get(a.get('staff_id'), {}).get('name_jp', '?')} — "
        f"{db._allowance_default_label(a.get('allowance_type', 'other'))} "
        f"¥{int(a.get('amount') or 0):,}"
        + (" 🔒" if a.get("is_off_record") else ""): a
        for a in all_allowances
    }
    sel_remove = st.selectbox(
        "取消する手当",
        list(remove_options.keys()),
        key="remove_allowance_select",
    )
    if sel_remove and st.button("🗑 この手当を取消", key="remove_allowance_btn"):
        target = remove_options[sel_remove]
        db.remove_individual_allowance(
            target["id"], event_id=event_id, performed_by=operator_name()
        )
        # 該当の支払いがあれば未承認に戻す（再計算が必要）
        db.reset_payment_to_pending(
            event_id, target.get("staff_id"),
            reason=f"個別手当取消: {target.get('allowance_type')}",
        )
        st.success("🗑 手当を取消しました。該当の支払いを未承認に戻しました。")
        st.rerun()


# ============================================================
# 5. 運用ヒント
# ============================================================
with st.expander("💡 個別手当の運用ヒント"):
    st.markdown("""
**典型的な使い方:**
- **言語手当**: 中国語・韓国語対応のディーラーに ¥3,000〜¥5,000/イベント
- **人材確保手当**: 急遽入ってくれたスタッフに採用優遇枠として ¥10,000
- **リーダー手当**: シフトリーダー・TDサブ等の追加責任に ¥5,000〜¥10,000
- **その他（オフレコ）**: 特殊事情で個別交渉した手当（他のスタッフに見せたくない）

**支払い計算との連動:**
- ここで手当を追加・取消すると、該当スタッフの支払いは自動的に「未承認」に戻ります
- その後「💰 支払い計算」で再計算 → 承認 → 支払い の流れ
- ピット端末で計算するときも、この手当が自動加算されます

**オフレコ運用:**
- 🔒 オフレコ = ピット端末では金額・件数が伏せられる（合計には含まれる）
- 本ページ（管理者専用）でのみ詳細閲覧可
- ディーラーには「総額」しか見えないので、個別交渉の内訳は守られます
""")
