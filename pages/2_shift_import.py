"""P1 Staff Manager — シフト取込ページ

役割: 完成済みイベント（基本情報・レート設定済み）に対してシフトCSVを流し込む。
イベント本体の作成・編集は pages/0_event_setup.py に集約。
"""

import streamlit as st
import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db
from utils.shift_parser import parse_shift_csv
from utils.calculator import parse_shift_time
from utils.event_selector import select_event

st.set_page_config(page_title="シフト取込", page_icon="📅", layout="wide")
from utils.ui_helpers import hide_staff_only_pages
from utils.page_layout import apply_global_style, page_header, flow_bar
from utils.admin_guard import require_admin, admin_logout_button
apply_global_style()
hide_staff_only_pages()
require_admin(page_name="シフト取込")
admin_logout_button()

page_header("📅 シフト取込", "完成済みイベントにシフトCSVを取り込む。新規イベントは『📋 イベント設定』で先に作成してください。")
flow_bar(active="input", done=["setup"])


# ============================================================
# 1. イベント選択
# ============================================================
st.subheader("1. イベントを選択")
events = db.get_all_events()

if not events:
    st.warning(
        "⚠️ イベントがまだありません。先に **「📋 イベント設定」** ページで "
        "イベントを作成してください。"
    )
    st.page_link("pages/0_event_setup.py", label="📋 イベント設定を開く", icon="📋")
    st.stop()

event_id = select_event(events, "対象イベント")
if not event_id:
    st.stop()

event = db.get_event_by_id(event_id)
if event:
    st.write(
        f"📍 **{event.get('name')}**　"
        f"会場: {event.get('venue', '—')}　"
        f"期間: {event.get('start_date', '—')} 〜 {event.get('end_date', '—')}"
    )


# ============================================================
# 2. 現行レート（読み取り専用） — 編集はイベント設定で
# ============================================================
st.divider()
st.subheader("2. 設定済みレートの確認")

current_rates = db.get_event_rates(event_id)
if current_rates:
    rate_df = pd.DataFrame(current_rates)
    display_cols = ["date", "date_label", "hourly_rate", "night_rate",
                    "transport_allowance", "floor_bonus", "mix_bonus"]
    available = [c for c in display_cols if c in rate_df.columns]
    st.dataframe(rate_df[available], use_container_width=True, hide_index=True)
    st.caption("レート編集は『📋 イベント設定』タブ『既存編集』で行ってください。")
else:
    st.info(
        "ℹ️ レート未設定です。シフトを取り込むと日付に対してデフォルト "
        "（時給¥1,500 / 深夜¥1,875）で自動補完されます。"
        "プリセットを適用するには『📋 イベント設定』を使ってください。"
    )
    st.page_link("pages/0_event_setup.py", label="📋 レート設定はこちら", icon="📋")


# ============================================================
# 3. シフトCSV取込
# ============================================================
st.divider()
st.subheader("3. シフト表を取り込み")

st.markdown("""
**対応フォーマット:** CSV / TSV / Excel（Googleスプレッドシートからダウンロード可）

見出し行と列の対応は**自動で判定**します。表の上にタイトルや注記の行があっても構いません。
判定結果は取り込む前に画面で確認・変更できます。
""")

uploaded = st.file_uploader("CSV / TSV / Excelファイル", type=["csv", "tsv", "txt", "xlsx"])

# 年指定: イベント開始年を初期値に
default_year = 2026
if event and event.get("start_date"):
    try:
        default_year = int(event["start_date"][:4])
    except Exception:
        pass

year_input = st.number_input(
    "年（最初の月の年を入力）",
    value=default_year, step=1,
    help="例: 12/29は入力年、1/4は翌年として処理します。8月開催なら開催年。",
)

if uploaded:
    # P2#8 (2026-05-04): アップロードサイズの上限チェック（5MB）
    MAX_UPLOAD_SIZE = 5 * 1024 * 1024
    if uploaded.size > MAX_UPLOAD_SIZE:
        st.error(
            f"❌ ファイルが大きすぎます（{uploaded.size / 1024 / 1024:.1f}MB）。"
            f"上限は {MAX_UPLOAD_SIZE / 1024 / 1024:.0f}MB です。"
        )
        st.stop()
    content = uploaded.read()
    # 2026-07-28: Excel(xlsx)対応。CSVに変換してから既存パーサーへ渡す
    if uploaded.name.lower().endswith(".xlsx"):
        import io
        _xdf = pd.read_excel(io.BytesIO(content), dtype=str).fillna("")
        content = _xdf.to_csv(index=False).encode("utf-8")
    # --- 読み取り条件（自動判定 → 必要なら手で直す） ---
    probe = parse_shift_csv(content, year=year_input)
    _cols = probe.get("columns") or []
    _auto_map = probe.get("mapping") or {}

    with st.expander("⚙️ 読み取り条件（自動判定済み・必要なときだけ開く）",
                     expanded=not probe.get("dates")):
        c1, c2 = st.columns(2)
        with c1:
            header_row = st.number_input(
                "見出し行（0始まり）", min_value=0, max_value=50,
                value=int(probe.get("header_row", 0)),
                help="日付が並んでいる行を指定します。通常は自動判定のままで構いません。",
            )
        with c2:
            paren_label = st.radio(
                "括弧つきの時刻（例 `12:00-21:00 (22:00)`）",
                ["手前の時刻を使う", "括弧の時刻を使う"],
                horizontal=True,
                help="どちらを選んでも、当日ピット端末で打刻すれば実績で上書きされます。",
            )
        paren_mode = "paren" if paren_label.startswith("括弧") else "first"

        st.caption("列の対応（自動判定を上書きしたいときだけ変更）")
        mc = st.columns(4)
        mapping = {}
        for i, (field, label) in enumerate(
                (("role", "役職"), ("no", "NO."), ("name_jp", "名前"), ("name_en", "英名"))):
            opts = ["（使わない）"] + _cols
            cur = _auto_map.get(field)
            idx = opts.index(cur) if cur in opts else 0
            with mc[i]:
                sel = st.selectbox(label, opts, index=idx, key=f"map_{field}")
            mapping[field] = None if sel == "（使わない）" else sel

        exclude_raw = st.text_input(
            "取り込まないNO.（カンマ区切り）",
            help="他社が支払いを管理するスタッフなど。例: 1001,1002,1007",
            placeholder="例: 1001,1002,1003",
        )

    exclude_nos = [x.strip() for x in (exclude_raw or "").replace("、", ",").split(",") if x.strip()]
    parsed = parse_shift_csv(content, year=year_input, header_row=int(header_row),
                             mapping=mapping, paren_mode=paren_mode,
                             exclude_nos=exclude_nos)

    # --- 判定結果のサマリ ---
    st.markdown("#### 読み取り結果")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("スタッフ", f"{len(parsed['staff'])}名")
    s2.metric("日付", f"{len(parsed['dates'])}日")
    s3.metric("シフト", f"{len(parsed['shifts'])}件")
    s4.metric("読めなかったセル", f"{len(parsed['skipped'])}件")
    st.caption(
        f"見出し行: {parsed['header_row']}行目 ／ "
        f"役職={parsed['mapping'].get('role') or '—'}・"
        f"NO.={parsed['mapping'].get('no') or '—'}・"
        f"名前={parsed['mapping'].get('name_jp') or '—'}・"
        f"英名={parsed['mapping'].get('name_en') or '—'}"
    )

    for w in parsed.get("warnings", []):
        st.warning(f"⚠️ {w}")

    if parsed.get("excluded"):
        with st.expander(f"🚫 取り込まない{len(parsed['excluded'])}名（NO.指定による除外）"):
            st.dataframe(pd.DataFrame(parsed["excluded"]),
                         use_container_width=True, hide_index=True)

    if parsed.get("skipped"):
        st.error(
            f"❌ 時刻として読めないセルが {len(parsed['skipped'])} 件あります。"
            "このままだと**その勤務は取り込まれません**。内容を確認してください。"
        )
        st.dataframe(pd.DataFrame(parsed["skipped"]),
                     use_container_width=True, hide_index=True)

    if parsed.get("paren_cells"):
        _used = "括弧の時刻" if paren_mode == "paren" else "手前の時刻"
        with st.expander(
                f"🔎 括弧つきの時刻が {len(parsed['paren_cells'])} 件（いま{_used}を採用中）"):
            st.dataframe(pd.DataFrame(parsed["paren_cells"]),
                         use_container_width=True, hide_index=True)

    if not parsed["shifts"]:
        st.error("シフトが1件も読み取れませんでした。上の『読み取り条件』を確認してください。")
        st.stop()

    # プレビュー
    with st.expander(f"👥 スタッフ {len(parsed['staff'])}名", expanded=False):
        st.dataframe(pd.DataFrame(parsed["staff"]), use_container_width=True, hide_index=True)
    with st.expander(f"📅 シフト {len(parsed['shifts'])}件（先頭50件）", expanded=False):
        st.dataframe(pd.DataFrame(parsed["shifts"][:50]),
                     use_container_width=True, hide_index=True)

    if st.button("🚀 取り込み実行", type="primary"):
        prog = st.progress(0.0, text="スタッフを登録中…")
        # スタッフを先に作り、(NO., 名前) → staff_id の対応表を持つ。
        # シフトごとに find_or_create を呼ぶと同じ問い合わせを何百回も繰り返すため。
        id_map = {}
        for i, s in enumerate(parsed["staff"]):
            id_map[(s["no"], s["name_jp"])] = db.find_or_create_staff(
                s["no"], s["name_jp"], s["name_en"], s["role"])
            prog.progress((i + 1) / max(1, len(parsed["staff"])) * 0.3,
                          text=f"スタッフを登録中… {i + 1}/{len(parsed['staff'])}")

        imported_shifts, failed = 0, []
        total = max(1, len(parsed["shifts"]))
        for i, shift in enumerate(parsed["shifts"]):
            staff_id = id_map.get((shift["no"], shift["name_jp"]))
            if not staff_id:
                staff_id = db.find_or_create_staff(
                    shift["no"], shift["name_jp"], role=shift["role"])
            time_parsed = parse_shift_time(shift["time_range"])
            if not time_parsed:
                failed.append(shift)
                continue
            start_min, end_min = time_parsed
            db.upsert_shift(
                event_id, staff_id, shift["date"],
                f"{start_min // 60:02d}:{start_min % 60:02d}",
                f"{end_min // 60:02d}:{end_min % 60:02d}",
            )
            imported_shifts += 1
            prog.progress(0.3 + (i + 1) / total * 0.7,
                          text=f"シフトを登録中… {i + 1}/{total}")

        # 日付からレートを自動設定（未設定の日のみ）
        existing_rate_dates = {r["date"] for r in db.get_event_rates(event_id)}
        for date in parsed["dates"]:
            if date not in existing_rate_dates:
                db.set_event_rate(event_id, date)
        prog.empty()

        st.success(
            f"取り込み完了: スタッフ {len(parsed['staff'])}名 / "
            f"シフト {imported_shifts}件を登録"
            + (f" ／ 除外 {len(parsed['excluded'])}名" if parsed.get("excluded") else "")
        )
        if failed:
            st.error(f"❌ {len(failed)}件は登録できませんでした")
            st.dataframe(pd.DataFrame(failed), use_container_width=True, hide_index=True)
        if parsed.get("skipped"):
            st.warning(
                f"⚠️ 読めなかった {len(parsed['skipped'])} 件は取り込まれていません。"
                "上の一覧を確認し、必要なら『出退勤』ページで手入力してください。"
            )
        st.balloons()


# ============================================================
# 4. 取り込み済みシフト
# ============================================================
st.divider()
st.subheader("4. 取り込み済みシフト")

shifts = db.get_shifts_for_event(event_id)
if shifts:
    st.write(f"合計: {len(shifts)} シフト")
    shift_display = pd.DataFrame(shifts)
    display_cols = ["name_jp", "role", "no", "date", "planned_start", "planned_end", "status"]
    available = [c for c in display_cols if c in shift_display.columns]
    st.dataframe(shift_display[available], use_container_width=True, hide_index=True)
else:
    st.info("シフトがまだ取り込まれていません。")
