"""P1 Staff Manager — 応募管理（採用判定・案A）

大会ごとの応募一覧を表示し、採用（p1_staff へ昇格）/不採用 を判定する。
採用時は住所から地域(region)を算出して昇格RPCに渡す（交通費・支払が region キーで動くため）。
スタッフの本名・連絡先などPIIを扱うため管理者ロール限定。
"""

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db
from utils.region import address_to_region, REGIONS

st.set_page_config(page_title="応募管理", page_icon="🗂", layout="wide")
from utils.ui_helpers import hide_staff_only_pages
from utils.page_layout import apply_global_style
from utils.admin_guard import (
    require_admin, admin_logout_button, operator_name, admin_login_at, is_auth_enabled,
)

apply_global_style()
hide_staff_only_pages()
require_admin(page_name="応募管理")
admin_logout_button()

# fail closed: 認証未設定（パスワードレスdev）では、service_role が応募PIIを露出しうるため開かない。
if not is_auth_enabled():
    st.error(
        "⛔ このページは認証が有効な環境でのみ利用できます。"
        "Streamlit Secrets に `[auth.users]`（推奨）または `ADMIN_PASSWORD` を設定してください。"
    )
    st.stop()

st.title("🗂 応募管理")
st.caption("ディーラー応募を確認し、採用（スタッフ登録）/不採用を判定します。")

_STATUS_LABEL = {
    "new": "未確認", "reviewed": "確認済", "accepted": "採用",
    "rejected": "不採用", "source_changed": "内容変更あり", "source_missing": "元行消失",
}

if not db.applications_enabled():
    st.info(
        "応募連動はまだ有効化されていません。"
        "「応募フォーム設定」での登録と、Supabase 側の準備（マイグレ適用＋"
        "`SUPABASE_SERVICE_KEY` 設定）が必要です。",
        icon="🔌",
    )
    st.stop()

# PII（本名・連絡先等）の閲覧を監査ログに残す。ログインした operator＋ログイン時刻ごとに
# 1回記録する（同一ブラウザで別管理者が再ログインした場合も各人の閲覧を残す）。
_audit_key = f"_apps_access_logged::{operator_name()}::{admin_login_at()}"
if not st.session_state.get(_audit_key):
    ok = False
    try:
        ok = db.log_action_service("access_applications", "application",
                                   detail="page=応募管理", performed_by=operator_name())
    except Exception:
        ok = False
    if ok:  # 記録成功時のみフラグを立てる（失敗時は次回リランで再試行）
        st.session_state[_audit_key] = True

events = db.get_all_events() or []
ev_name = {e["id"]: e.get("name", "(無題)") for e in events}

# --- フィルタ ---
col1, col2 = st.columns([2, 3])
with col1:
    # 同名大会（毎年同名の大会など）が潰れないよう、日付＋IDでラベルを一意化する。
    ev_opts = {"（全大会）": None}
    for e in events:
        lbl = f'{e.get("name","(無題)")}（{e.get("start_date","")} #{e["id"]}）'
        ev_opts[lbl] = e["id"]
    ev_choice = st.selectbox("大会で絞り込み", list(ev_opts.keys()))
    event_id = ev_opts[ev_choice]
with col2:
    status_choice = st.multiselect(
        "ステータス", list(_STATUS_LABEL.keys()),
        default=["new", "source_changed"],
        format_func=lambda s: _STATUS_LABEL.get(s, s),
    )

apps = db.get_dealer_applications(event_id=event_id, statuses=status_choice or None)
st.caption(f"{len(apps)} 件")

if not apps:
    st.success("対象の応募はありません。")
    st.stop()

for a in apps:
    with st.container(border=True):
        head = f'**{a.get("name_jp") or a.get("real_name") or "(名義不明)"}**'
        head += f'　<{_STATUS_LABEL.get(a.get("status"), a.get("status"))}>'
        st.markdown(head)
        c1, c2, c3 = st.columns(3)
        with c1:
            st.caption(f'本名: {a.get("real_name","")}')
            st.caption(f'性別/生年月日: {a.get("gender","")} / {a.get("birthday","")}')
            st.caption(f'大会: {ev_name.get(a.get("event_id"), "?")}')
        with c2:
            st.caption(f'メール: {a.get("email","")}')
            st.caption(f'電話: {a.get("phone","")}')
            st.caption(f'最寄り駅: {a.get("nearest_station","")}')
        with c3:
            mix = "可" if a.get("can_mix") else "不可"
            st.caption(f'業務種別: {a.get("role_hint","")}')
            st.caption(f'MIX: {mix}（{a.get("mix_games","")}）')
            dates = a.get("available_dates") or []
            st.caption(f'勤務可能: {", ".join(dates) if isinstance(dates, list) else dates}')

        if a.get("self_pr") or a.get("experience") or a.get("questions"):
            with st.expander("自己PR / 活動歴 / 質問"):
                if a.get("self_pr"):
                    st.write(a.get("self_pr", ""))
                if a.get("experience"):
                    st.write(a.get("experience", ""))
                if a.get("questions"):
                    st.write(a.get("questions", ""))

        if a.get("status") in ("new", "reviewed", "source_changed"):
            pref, region = address_to_region(a.get("address"))
            use_region = region
            if region is None:
                # 地域が判定できないと交通費が0で計算され過少支払になるため、
                # 黙って採用せず、地域を手動選択させてから採用する。
                st.warning(
                    f'住所から地域を判定できませんでした（住所: {a.get("address") or "未入力"}）。'
                    "交通費が正しく計算されるよう、地域を選んでから採用してください。"
                )
                _ph = "（地域を選択）"
                _sel = st.selectbox("地域を指定して採用", [_ph] + REGIONS, key=f"reg_{a['id']}")
                use_region = None if _sel == _ph else _sel
            b1, b2, _ = st.columns([1, 1, 4])
            with b1:
                if st.button("✅ 採用", key=f"acc_{a['id']}", type="primary"):
                    if use_region is None:
                        st.error("地域を選んでから採用してください（交通費の過少支払を防ぐため）。")
                    else:
                        try:
                            staff_id = db.promote_dealer_application(
                                a["id"], operator_name(), prefecture=pref, region=use_region,
                            )
                            st.success(f"採用しました（スタッフID: {staff_id} / 地域: {use_region}）。")
                            st.rerun()
                        except Exception as e:
                            st.error(f"採用処理に失敗しました: {e}")
            with b2:
                if st.button("🚫 不採用", key=f"rej_{a['id']}"):
                    try:
                        db.reject_dealer_application(a["id"], operator_name())
                        st.rerun()
                    except Exception as e:
                        st.error(f"処理に失敗しました: {e}")
        elif a.get("status") == "accepted":
            st.caption(f'→ 採用済み（スタッフID: {a.get("promoted_staff_id")} / 判定: {a.get("reviewed_by","")}）')
