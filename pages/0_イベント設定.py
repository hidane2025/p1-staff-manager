"""P1 Staff Manager — イベント設定ウィザード

新規イベントを「JSONテンプレ一括投入」「プリセット適用」「手動入力」のいずれかで作成・編集する。
スタッフ／シフト／支払いより前段の「型」をここで完成させてから、シフト取込みに進む。
"""

from __future__ import annotations

import json
import sys
import os
from io import BytesIO

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import db
from utils import event_template as etpl
from utils.event_selector import select_event
from utils.ui_helpers import hide_staff_only_pages, friendly_error
from utils import db_schema


st.set_page_config(page_title="イベント設定", page_icon="📋", layout="wide")
hide_staff_only_pages()
st.title("📋 イベント設定")
st.caption("新しい大会の『型』を一画面で組み立てる。スタッフ・シフトを入れる前にここを完成させる。")


# ============================================================
# 共通: マイグレ警告
# ============================================================
if not db_schema.has_column("p1_events", "prefecture"):
    st.info(
        "ℹ️ DBマイグレーション `20260504_add_event_prefecture.sql` 未適用です。"
        "都道府県・テンプレID保存はスキップされます（基本機能は問題なく動作）。"
    )


# ============================================================
# テンプレートディレクトリの場所
# ============================================================
ROOT = os.path.dirname(os.path.dirname(__file__))
TEMPLATES_DIR = os.path.join(ROOT, "docs", "event_templates")


def _list_template_files() -> list[str]:
    if not os.path.isdir(TEMPLATES_DIR):
        return []
    return sorted([
        f for f in os.listdir(TEMPLATES_DIR)
        if f.endswith(".json") and not f.startswith("_")
    ])


def _read_template_file(name: str) -> dict:
    path = os.path.join(TEMPLATES_DIR, name)
    return etpl.load_template(path)


# ============================================================
# タブ構成
# ============================================================
tab_import, tab_create, tab_edit = st.tabs([
    "🚀 JSONテンプレから投入",
    "🆕 プリセットで新規作成",
    "✏️ 既存イベントを編集",
])


# ============================================================
# タブ1: JSONテンプレから投入
# ============================================================
with tab_import:
    st.subheader("JSONテンプレートから一括投入")
    st.caption(
        "中野さんが手元で編集した JSON、または "
        "`docs/event_templates/` のサンプルをそのまま投入できます。"
    )

    sample_files = _list_template_files()
    src_choice = st.radio(
        "ソース",
        ["📤 ファイルをアップロード", "📚 内蔵サンプルから選択"],
        horizontal=True,
    )

    tmpl: dict | None = None

    if src_choice == "📤 ファイルをアップロード":
        uploaded = st.file_uploader("event_template.json", type=["json"])
        if uploaded is not None:
            try:
                tmpl = etpl.load_template(uploaded)
            except Exception as e:
                friendly_error("JSONの読み込みに失敗しました", str(e))
    else:
        if not sample_files:
            st.warning("docs/event_templates/ にサンプルがありません。")
        else:
            choice = st.selectbox("内蔵サンプル", sample_files)
            if st.button("📖 読み込み"):
                try:
                    tmpl = _read_template_file(choice)
                    st.session_state["__import_tmpl__"] = tmpl
                except Exception as e:
                    friendly_error("サンプルの読み込みに失敗しました", str(e))
        # 直前のセッションを引き継ぎ表示
        if tmpl is None:
            tmpl = st.session_state.get("__import_tmpl__")

    if tmpl:
        st.divider()
        st.markdown("### プレビュー")
        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("イベント名", tmpl.get("name", "—"))
            st.write(f"📍 **会場:** {tmpl.get('venue', '—')}（{tmpl.get('venue_prefecture', '—')}）")
            st.write(
                f"📆 **期間:** {tmpl.get('start_date', '—')} 〜 "
                f"{tmpl.get('end_date', '—')}"
            )
            st.write(f"☕ **休憩:** 6h超 {tmpl.get('break_minutes_6h', 45)}分 / 8h超 {tmpl.get('break_minutes_8h', 60)}分")
            st.write(f"🏷 **テンプレID:** `{tmpl.get('rate_template_id', '—')}`")

        rates = tmpl.get("rates") or {}
        rules = tmpl.get("transport_rules") or []
        with col_b:
            st.metric("対象日数", len(rates))
            st.metric("地域別交通費ルール", len(rules))

        # 検証
        errs = etpl.validate_template(tmpl)
        if errs:
            st.error("テンプレ検証エラー（修正してください）:")
            for e in errs:
                st.markdown(f"- {e}")
        else:
            st.success("✅ 検証OK。投入できます。")

        with st.expander("📊 レート詳細"):
            if rates:
                rate_df = pd.DataFrame([
                    {"日付": d, **r} for d, r in sorted(rates.items())
                ])
                st.dataframe(rate_df, use_container_width=True, hide_index=True)
            else:
                st.caption("レート未指定（全日デフォルト ¥1,500/¥1,875 で計算されます）")

        with st.expander("🚃 地域別交通費ルール"):
            if rules:
                st.dataframe(pd.DataFrame(rules), use_container_width=True, hide_index=True)
            else:
                st.caption("ルール未指定")

        st.divider()
        if not errs and st.button("🚀 投入実行（新規イベントとして作成）", type="primary"):
            try:
                eid = etpl.apply_template(tmpl, mode="create")
                st.session_state["selected_event_id"] = eid
                st.success(f"✅ イベントを作成しました（event_id={eid}）")
                st.balloons()
                st.session_state.pop("__import_tmpl__", None)
            except Exception as e:
                friendly_error("投入に失敗しました", str(e))


# ============================================================
# タブ2: プリセットで新規作成（手動）
# ============================================================
with tab_create:
    st.subheader("プリセット適用＋手動調整で新規作成")
    st.caption("JSONを書くほどでもない場合の最短ルート。premium日だけチェックして作成。")

    with st.form("create_form_v2"):
        col1, col2 = st.columns(2)
        with col1:
            c_name = st.text_input("イベント名", placeholder="例: P1 Tokyo 2026 春大会")
            c_venue = st.text_input("会場", placeholder="例: 恵比寿スバル本社ビル")
            c_pref = st.selectbox(
                "都道府県",
                ["", "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
                 "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
                 "新潟県", "富山県", "石川県", "福井県",
                 "山梨県", "長野県", "岐阜県", "静岡県", "愛知県", "三重県",
                 "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
                 "鳥取県", "島根県", "岡山県", "広島県", "山口県",
                 "徳島県", "香川県", "愛媛県", "高知県",
                 "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"],
            )
        with col2:
            c_start = st.date_input("開始日")
            c_end = st.date_input("終了日")
            c_break6 = st.number_input("6時間超休憩（分）", value=45, step=5)
            c_break8 = st.number_input("8時間超休憩（分）", value=60, step=5)

        st.markdown("---")
        st.markdown("**レートプリセット**")
        preset_keys = list(etpl.RATE_PRESETS.keys())
        c_preset = st.selectbox(
            "プリセット",
            preset_keys,
            format_func=lambda k: f"{etpl.RATE_PRESETS[k]['label']} — {etpl.RATE_PRESETS[k]['description']}",
        )

        # プレビュー
        if c_preset:
            ps = etpl.RATE_PRESETS[c_preset]
            colp1, colp2 = st.columns(2)
            with colp1:
                st.caption("通常日")
                st.json(ps["regular"])
            with colp2:
                st.caption("プレミアム日")
                st.json(ps["premium"])

        st.markdown("---")
        st.markdown("**プレミアム指定日（チェックした日のみ premium レート）**")
        # フォーム内で動的に dates を作る
        try:
            dates_in_range = etpl.daterange(str(c_start), str(c_end))
        except (ValueError, TypeError):
            dates_in_range = []

        premium_dates: list = []
        if dates_in_range:
            cols = st.columns(min(len(dates_in_range), 7))
            for i, d in enumerate(dates_in_range):
                with cols[i % len(cols)]:
                    if st.checkbox(d, key=f"prem_{d}"):
                        premium_dates.append(d)
        else:
            st.caption("開始日 ≦ 終了日 になっていません")

        submitted = st.form_submit_button("✅ 作成", type="primary")
        if submitted:
            errors = []
            if not c_name:
                errors.append("イベント名は必須です")
            if not c_venue:
                errors.append("会場は必須です")
            if not dates_in_range:
                errors.append("開始日 ≦ 終了日 になるよう設定してください")
            if errors:
                for e in errors:
                    st.error(e)
            else:
                rates = etpl.build_rates_from_preset(c_preset, dates_in_range, premium_dates)
                tmpl = {
                    "name": c_name,
                    "venue": c_venue,
                    "venue_prefecture": c_pref,
                    "start_date": str(c_start),
                    "end_date": str(c_end),
                    "break_minutes_6h": int(c_break6),
                    "break_minutes_8h": int(c_break8),
                    "rate_template_id": c_preset,
                    "dates": dates_in_range,
                    "rates": rates,
                    "transport_rules": [],
                }
                try:
                    eid = etpl.apply_template(tmpl, mode="create")
                    st.session_state["selected_event_id"] = eid
                    st.success(
                        f"✅ 「{c_name}」を作成しました（event_id={eid}）。"
                        "次は『既存編集』タブで地域別交通費を設定してください。"
                    )
                    st.balloons()
                except Exception as e:
                    friendly_error("作成に失敗しました", str(e))


# ============================================================
# タブ3: 既存イベントを編集
# ============================================================
with tab_edit:
    st.subheader("既存イベントを編集")
    events = db.get_all_events()
    if not events:
        st.info("まだイベントがありません。上のタブで作成してください。")
    else:
        eid = select_event(events, "編集対象", required=False)
        if not eid:
            st.stop()

        ev = db.get_event_by_id(eid)
        if not ev:
            st.error(f"event_id={eid} が見つかりません")
            st.stop()

        # --- 基本情報 ---
        with st.expander("📝 基本情報", expanded=True):
            with st.form("edit_meta"):
                col1, col2 = st.columns(2)
                with col1:
                    e_name = st.text_input("イベント名", value=ev.get("name", ""))
                    e_venue = st.text_input("会場", value=ev.get("venue", ""))
                    e_pref = st.text_input("都道府県", value=ev.get("prefecture") or "")
                with col2:
                    e_start = st.text_input("開始日 YYYY-MM-DD", value=ev.get("start_date", ""))
                    e_end = st.text_input("終了日 YYYY-MM-DD", value=ev.get("end_date", ""))
                    e_break6 = st.number_input(
                        "6h超休憩（分）", value=int(ev.get("break_minutes_6h") or 45), step=5
                    )
                    e_break8 = st.number_input(
                        "8h超休憩（分）", value=int(ev.get("break_minutes_8h") or 60), step=5
                    )
                if st.form_submit_button("💾 基本情報を保存"):
                    db.update_event_meta(
                        eid,
                        name=e_name, venue=e_venue, prefecture=e_pref,
                        start_date=e_start, end_date=e_end,
                        break_minutes_6h=int(e_break6),
                        break_minutes_8h=int(e_break8),
                    )
                    st.success("保存しました")
                    st.rerun()

        # --- 日別レート ---
        with st.expander("💰 日別レート", expanded=True):
            current_rates = db.get_event_rates(eid)
            if current_rates:
                st.dataframe(
                    pd.DataFrame(current_rates)[
                        ["date", "date_label", "hourly_rate", "night_rate",
                         "transport_allowance", "floor_bonus", "mix_bonus"]
                    ],
                    use_container_width=True, hide_index=True,
                )
            else:
                st.caption("レート未設定。下の『プリセット一括適用』を使うか、シフトを取り込めば自動で日付が補完されます。")

            st.markdown("**プリセット一括適用**")
            with st.form("apply_preset"):
                colp1, colp2 = st.columns(2)
                with colp1:
                    p_id = st.selectbox(
                        "プリセット",
                        list(etpl.RATE_PRESETS.keys()),
                        format_func=lambda k: etpl.RATE_PRESETS[k]["label"],
                    )
                with colp2:
                    try:
                        target_dates = etpl.daterange(ev["start_date"], ev["end_date"])
                    except Exception:
                        target_dates = []
                    p_premium = st.multiselect("プレミアム日", target_dates, default=[])
                if st.form_submit_button("⚡ プリセットを一括適用（既存レートは上書き）"):
                    if not target_dates:
                        st.error("期間が無効です。基本情報の開始日／終了日を確認してください。")
                    else:
                        rates = etpl.build_rates_from_preset(p_id, target_dates, p_premium)
                        rates_list = [{"date": d, **r} for d, r in rates.items()]
                        n = db.bulk_set_event_rates(eid, rates_list)
                        st.success(f"✅ {n}日分のレートを適用しました")
                        st.rerun()

        # --- 地域別交通費 ---
        with st.expander("🚃 地域別交通費ルール", expanded=False):
            current_rules = db.get_transport_rules(eid)
            st.caption(
                "max_amount は領収書がある場合の上限。is_venue_region=1 は開催地（領収書不要・一律支給扱い）。"
            )
            base_rules = current_rules if current_rules else [
                {"region": r, "max_amount": 0, "receipt_required": 1,
                 "is_venue_region": 0, "note": ""}
                for r in etpl.JAPAN_REGIONS
            ]
            rules_df = pd.DataFrame(base_rules)
            edited = st.data_editor(
                rules_df,
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key=f"rules_editor_{eid}",
            )
            if st.button("💾 交通費ルールを保存"):
                rule_list = []
                for _, row in edited.iterrows():
                    region = (row.get("region") or "").strip()
                    if not region:
                        continue
                    rule_list.append({
                        "region": region,
                        "max_amount": int(row.get("max_amount") or 0),
                        "receipt_required": int(row.get("receipt_required") or 0),
                        "is_venue_region": int(row.get("is_venue_region") or 0),
                        "note": (row.get("note") or "") or "",
                    })
                db.save_transport_rules(eid, rule_list)
                st.success(f"✅ {len(rule_list)}地域分を保存しました")
                st.rerun()

        # --- エクスポート ---
        with st.expander("📤 このイベントを JSONテンプレとしてダウンロード", expanded=False):
            try:
                export_dict = etpl.export_event_to_template(eid)
                json_str = etpl.dump_template(export_dict)
                st.code(json_str, language="json")
                st.download_button(
                    "💾 ダウンロード",
                    data=json_str.encode("utf-8"),
                    file_name=f"event_{eid}_{ev.get('name', 'export').replace(' ', '_')}.json",
                    mime="application/json",
                )
            except Exception as e:
                friendly_error("エクスポートに失敗しました", str(e))
