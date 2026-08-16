"""P1 Staff Manager — 交通費ルール設定・事前見積"""

import streamlit as st
import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db
from utils import payment_recalc
from utils import transport_rules as transport_rules_mod
from utils.region import address_to_region
# 2026-08-16: 上限の鍵を地方名（近畿・東海…）から交通区分（近郊通勤・隣接・
# 中距離・遠方・特別遠方・海外）へ変更。同じ地方でも会場からの距離が違い
# （大阪開催なら香川=中距離／愛媛=遠方）、地方単位では上限を表現できない。
from utils import transport_zones as tz
REGIONS = list(tz.ZONES)
def default_regions_for_event():
    return tz.default_zone_rules()
from utils.event_selector import select_event

st.set_page_config(page_title="交通費", page_icon="🚃", layout="wide")
from utils.ui_helpers import hide_staff_only_pages
from utils.page_layout import apply_global_style, page_header, flow_bar
from utils.admin_guard import require_admin, admin_logout_button
apply_global_style()
hide_staff_only_pages()
require_admin(page_name="交通費")
admin_logout_button()

page_header("🚃 交通費ルール・事前見積", "イベントごとに交通区分別の交通費上限を設定し、領収書金額から精算額を算出します。")
flow_bar(active="setup")

# --- イベント選択（全ページ共通） ---
event_id = select_event(db.get_all_events(), "イベント")
event = db.get_event_by_id(event_id)
_VENUE_KEY = tz.venue_key(event)


def _zone_of(staff: dict) -> str:
    """スタッフの交通区分（住所の都道府県→会場別ゾーン）。未判定は空。"""
    return tz.zone_for_staff(staff, _VENUE_KEY)


# ============================================================
# セクション1: 交通費ルール設定
# ============================================================
st.divider()
st.subheader("① 交通区分別 交通費ルール")
st.markdown(
    "開催地（領収書不要・**出勤1日あたり一律**）とそれ以外（領収書必要・**往復総額の上限**）を"
    "交通区分別に設定します（区分は住所の都道府県から自動判定）。"
    "（交通費統一ルール 2026-07-22 TAKA起草・木村さん基本承認に準拠。個別具体例は都度相談）"
)

existing_rules = db.get_transport_rules(event_id)
if not existing_rules:
    # デフォルトテンプレートで初期化
    default_rules = default_regions_for_event()
    rules_for_edit = default_rules
else:
    # 不足地域を補完
    existing_regions = {r["region"] for r in existing_rules}
    rules_for_edit = list(existing_rules)
    for region in REGIONS:
        if region not in existing_regions:
            rules_for_edit.append({
                "region": region, "max_amount": 0,
                "receipt_required": 1, "is_venue_region": 0, "note": "",
            })

# 並び順を統一
# 未知の地域名でも落とさない（DB先行追加やリネームへの防御）
rules_for_edit = sorted(
    rules_for_edit,
    key=lambda r: (REGIONS.index(r["region"]) if r["region"] in REGIONS
                   else len(REGIONS)))

rules_df = pd.DataFrame([
    {
        "交通区分": r["region"],
        "開催地": bool(r.get("is_venue_region", 0)),
        "上限額(円)": int(r.get("max_amount", 0) or 0),
        "領収書必要": bool(r.get("receipt_required", 1)),
        "備考": r.get("note", "") or "",
    }
    for r in rules_for_edit
])

edited_rules = st.data_editor(
    rules_df,
    use_container_width=True,
    hide_index=True,
    disabled=["交通区分"],
    column_config={
        "交通区分": st.column_config.TextColumn("交通区分", width="small"),
        "開催地": st.column_config.CheckboxColumn(
            "開催地",
            help="チェックを入れた地域は、領収書不要で「上限額(円)×出勤日数」を一律支給（上限額欄＝1日あたりの金額）",
        ),
        "上限額(円)": st.column_config.NumberColumn(
            "上限額(円)", min_value=0, step=500,
            help="開催地=1日あたりの一律支給額／それ以外=イベント全体（往復）の上限。領収書金額が上限を超えた場合は自動で上限額に調整",
        ),
        "領収書必要": st.column_config.CheckboxColumn("領収書必要"),
        "備考": "備考",
    },
    key="transport_rules_editor",
)

col_save, col_reset = st.columns([1, 1])
with col_save:
    if st.button("💾 交通費ルールを保存", type="primary"):
        new_rules = []
        for _, row in edited_rules.iterrows():
            is_venue = bool(row["開催地"])
            new_rules.append({
                "region": row["交通区分"],
                "max_amount": int(row["上限額(円)"]) if row["上限額(円)"] else 0,
                # 開催地は領収書不要を強制
                "receipt_required": 0 if is_venue else (1 if row["領収書必要"] else 0),
                "is_venue_region": 1 if is_venue else 0,
                "note": row["備考"] or "",
            })
        db.save_transport_rules(event_id, new_rules)
        st.success("交通費ルールを保存しました")
        st.rerun()

with col_reset:
    if st.button("🔄 デフォルトにリセット"):
        db.save_transport_rules(event_id, default_regions_for_event())
        st.info("デフォルトにリセットしました。開催地を指定し直してください。")
        st.rerun()

# ============================================================
# セクション2: 事前見積（銀行準備の目安）
# ============================================================
st.divider()
st.subheader("② 事前見積（銀行準備の目安）")

rules_map = {r["region"]: r for r in db.get_transport_rules(event_id)}
if not rules_map:
    st.info("先に①でルールを保存してください。")
    st.stop()

# イベントに参加する全スタッフ（シフトがあるスタッフ）
shifts = db.get_shifts_for_event(event_id)
unique_staff_ids = list({s["staff_id"] for s in shifts})
if not unique_staff_ids:
    st.info("シフト取込後に見積もりできます。")
    st.stop()

all_staff_map = {s["id"]: s for s in db.get_all_staff()}
participating = [all_staff_map[sid] for sid in unique_staff_ids if sid in all_staff_map]

# 2026-08-04: 開催地は「日額×出勤日数」で支給するため（支払い計算・ピット端末と同一式）、
# 見積・確定サマリーでもスタッフごとのシフト日数を使う（欠勤は除く）
_days_by_staff: dict = {}
for _s in shifts:
    if _s.get("status") != "absent":
        _days_by_staff.setdefault(_s["staff_id"], set()).add(_s["date"])

# 交通区分別集計
region_summary = {r: {"count": 0, "estimate": 0, "need_receipt": 0, "no_region": 0}
                   for r in REGIONS}
region_summary["未登録"] = {"count": 0, "estimate": 0, "need_receipt": 0, "no_region": 0}

for staff in participating:
    region = _zone_of(staff)
    if not region:
        region = "未登録"
    if region not in region_summary:
        region_summary[region] = {"count": 0, "estimate": 0, "need_receipt": 0, "no_region": 0}
    region_summary[region]["count"] += 1
    rule = rules_map.get(region)
    if rule:
        if rule.get("is_venue_region"):
            # 開催地: 日額 × シフト日数（式の正=utils/transport_rules.py）
            _amt = transport_rules_mod.venue_amount(
                rule["max_amount"], len(_days_by_staff.get(staff["id"], ())))
        else:
            _amt = int(rule["max_amount"])
        region_summary[region]["estimate"] += _amt
        if rule.get("receipt_required"):
            region_summary[region]["need_receipt"] += 1

# 合計
total_count = sum(v["count"] for v in region_summary.values())
total_estimate = sum(v["estimate"] for v in region_summary.values())
need_receipt_count = sum(v["need_receipt"] for v in region_summary.values())
no_address_count = region_summary["未登録"]["count"]

col_m1, col_m2, col_m3, col_m4 = st.columns(4)
col_m1.metric("参加スタッフ", f"{total_count}名")
col_m2.metric("見積総額（上限合計）", f"¥{total_estimate:,}")
col_m3.metric("領収書必要", f"{need_receipt_count}名")
col_m4.metric("住所未登録", f"{no_address_count}名",
              delta=f"⚠️要対応" if no_address_count else None,
              delta_color="inverse" if no_address_count else "off")

# 交通区分別テーブル
summary_rows = []
for region in REGIONS + ["未登録"]:
    data = region_summary.get(region, {"count": 0, "estimate": 0, "need_receipt": 0})
    if data["count"] == 0:
        continue
    rule = rules_map.get(region, {})
    summary_rows.append({
        "交通区分": region,
        "人数": data["count"],
        "上限額/人": (
            (f"¥{rule.get('max_amount', 0):,}/日" if rule.get("is_venue_region")
             else f"¥{rule.get('max_amount', 0):,}")
            if rule else "—"
        ),
        "領収書": "必要" if rule.get("receipt_required") else "不要",
        "見積合計": f"¥{data['estimate']:,}",
    })

if summary_rows:
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

# ============================================================
# セクション3: 領収書金額入力
# ============================================================
st.divider()
st.subheader("③ 領収書金額入力（確定モード）")
st.markdown(
    "圏外スタッフの**片道**の領収書金額を入力します（自動で×2して往復精算・"
    "上限超過時は上限額に調整）。開催地（関西圏）在住者は入力不要で、"
    "領収書なし・出勤1日あたり一律の日額を自動支給します。"
)

# 既存の請求情報
existing_claims = {c["staff_id"]: c for c in db.get_transport_claims(event_id)}

# 領収書必要な地域のスタッフだけフィルタ
receipt_staff = []
venue_staff = []
unregistered_staff = []
for staff in sorted(participating, key=lambda s: (s.get("region") or "zzz", s.get("no") or 0)):
    region = _zone_of(staff)
    if not region:
        unregistered_staff.append(staff)
        continue
    rule = rules_map.get(region)
    if not rule:
        continue
    if rule.get("is_venue_region"):
        venue_staff.append((staff, rule))
    elif rule.get("receipt_required"):
        receipt_staff.append((staff, rule))

# 開催地在住者（自動支給）
if venue_staff:
    with st.expander(f"🏠 開催地在住・自動支給（{len(venue_staff)}名）"):
        for staff, rule in venue_staff:
            _d = len(_days_by_staff.get(staff["id"], ()))
            _auto = transport_rules_mod.venue_amount(rule["max_amount"], _d)
            col1, col2, col3 = st.columns([2, 1, 1])
            col1.write(f"{staff['name_jp']}（{staff.get('region', '')}）")
            col2.write(f"日額: ¥{rule['max_amount']:,} × {_d}日")
            col3.success(f"¥{_auto:,} 自動支給")

# 住所未登録者も手入力の対象に含める（上限なし・実費をそのまま支給）。
# 2026-08-13: 受付スタッフ等、地域ルールに乗らない人に実費を払う経路。
if unregistered_staff:
    st.info(
        f"ℹ️ 住所未登録 {len(unregistered_staff)}名は下の表で**手入力**できます"
        "（上限なし・入れた額をそのまま支給）。地域ルールで払う場合は"
        "スタッフ管理で住所を登録してください。"
    )

# 領収書入力（圏外＋住所未登録）
_input_staff = receipt_staff + [(s, None) for s in unregistered_staff]
if _input_staff:
    st.markdown(f"**領収書・手入力（{len(_input_staff)}名）:**")
    rows = []
    for staff, rule in _input_staff:
        claim = existing_claims.get(staff["id"], {})
        rows.append({
            "_staff_id": staff["id"],
            "NO.": staff.get("no", ""),
            "名前": staff["name_jp"],
            "交通区分": _zone_of(staff) or "（未判定）",
            "上限額": rule["max_amount"] if rule else 0,
            "領収書金額(円)": int(claim.get("receipt_amount") or 0),
            "領収書あり": bool(claim.get("has_receipt", 0)),
            "備考": claim.get("note", "") or "",
        })

    claim_df = pd.DataFrame(rows)
    edited_claims = st.data_editor(
        claim_df,
        use_container_width=True,
        hide_index=True,
        disabled=["_staff_id", "NO.", "名前", "交通区分", "上限額"],
        column_config={
            "_staff_id": None,
            "上限額": st.column_config.NumberColumn(
                "上限額", format="¥%d", help="0=上限なし（手入力額をそのまま支給）"),
            "領収書金額(円)": st.column_config.NumberColumn(
                "領収書金額(片道・円)", min_value=0, step=100,
                help="片道の領収書額を入れてください。自動で×2（往復）にし、"
                     "上限超過時は上限額に調整します（2026-08-16 中野さん指示）",
            ),
            "領収書あり": st.column_config.CheckboxColumn("領収書あり"),
            "備考": "備考",
        },
        key="claim_editor",
    )

    if st.button("💾 領収書金額を保存", type="primary"):
        saved = 0
        errors = []
        for _, row in edited_claims.iterrows():
            staff_id = int(row["_staff_id"])
            receipt = int(row["領収書金額(円)"]) if row["領収書金額(円)"] else 0
            limit = int(row["上限額"])
            has_receipt = int(bool(row["領収書あり"]))
            # 片道×2→上限で頭打ち。式の正=utils/transport_rules.py（3画面共通）
            approved = transport_rules_mod.round_trip_amount(receipt, limit)
            _gross = receipt * transport_rules_mod.ROUND_TRIP_MULTIPLIER
            if approved != _gross:
                errors.append(
                    f"{row['名前']}: 片道¥{receipt:,}×2=¥{_gross:,} → ¥{approved:,}（上限）に調整")
            # 領収書なし・金額0は支払いなし
            if not has_receipt:
                approved = 0
            db.upsert_transport_claim(
                event_id, staff_id, receipt_amount=receipt,
                approved_amount=approved, has_receipt=has_receipt,
                note=row["備考"] or "",
            )
            # 2026-08-13: 交通費が変わったら金額もその場で追随させる
            # （差し戻しだけだと古い封筒額が清算デスクに出る）
            db.reset_payment_to_pending(
                event_id, staff_id, reason="交通費（領収書金額）変更")
            payment_recalc.recalc_staff_payment(event_id, staff_id)
            saved += 1
        st.success(f"{saved}件の領収書金額を保存しました（支払い額も再計算済み）")
        if errors:
            with st.expander(f"⚠️ 上限超過 {len(errors)}件を自動調整"):
                for e in errors:
                    st.info(e)
        st.rerun()
else:
    st.info("領収書入力対象のスタッフはいません。")

# ============================================================
# セクション4: 確定交通費サマリー
# ============================================================
st.divider()
st.subheader("④ 確定交通費サマリー")

claims_map = {c["staff_id"]: c for c in db.get_transport_claims(event_id)}
confirmed_total = 0
venue_total = 0
unconfirmed_count = 0

for staff in participating:
    region = _zone_of(staff)
    rule = rules_map.get(region) if region else None
    if not rule:
        continue
    if rule.get("is_venue_region"):
        # 開催地: 日額 × シフト日数（式の正=utils/transport_rules.py）
        venue_total += transport_rules_mod.venue_amount(
            rule["max_amount"], len(_days_by_staff.get(staff["id"], ())))
    else:
        claim = claims_map.get(staff["id"])
        if claim and claim.get("has_receipt"):
            confirmed_total += int(claim.get("approved_amount") or 0)
        elif rule.get("max_amount", 0) > 0:
            unconfirmed_count += 1

col_c1, col_c2, col_c3, col_c4 = st.columns(4)
col_c1.metric("開催地自動支給", f"¥{venue_total:,}")
col_c2.metric("領収書確定分", f"¥{confirmed_total:,}")
col_c3.metric("合計", f"¥{venue_total + confirmed_total:,}")
col_c4.metric("未確定（領収書待ち）", f"{unconfirmed_count}名",
              delta_color="inverse" if unconfirmed_count else "off")
