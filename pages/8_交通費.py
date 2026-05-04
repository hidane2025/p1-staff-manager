"""P1 Staff Manager — 交通費ルール設定・事前見積"""

import streamlit as st
import pandas as pd
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import db
from utils.region import REGIONS, default_regions_for_event, address_to_region
from utils.event_selector import select_event

st.set_page_config(page_title="交通費", page_icon="🚃", layout="wide")
from utils.ui_helpers import hide_staff_only_pages
from utils.page_layout import apply_global_style, page_header, flow_bar
apply_global_style()
hide_staff_only_pages()

page_header("🚃 交通費ルール・事前見積", "イベントごとに地域別の交通費上限を設定し、領収書金額から精算額を算出します。")
flow_bar(active="setup")

# --- イベント選択（全ページ共通） ---
event_id = select_event(db.get_all_events(), "イベント")
event = db.get_event_by_id(event_id)

# ============================================================
# セクション1: 交通費ルール設定
# ============================================================
st.divider()
st.subheader("① 地域別 交通費ルール")
st.markdown(
    "開催地（領収書不要・一律支給）とそれ以外（領収書必要・上限あり）を地域別に設定します。"
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
rules_for_edit = sorted(rules_for_edit, key=lambda r: REGIONS.index(r["region"]))

rules_df = pd.DataFrame([
    {
        "地域": r["region"],
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
    disabled=["地域"],
    column_config={
        "地域": st.column_config.TextColumn("地域", width="small"),
        "開催地": st.column_config.CheckboxColumn(
            "開催地",
            help="チェックを入れた地域は、領収書不要で上限額を一律支給",
        ),
        "上限額(円)": st.column_config.NumberColumn(
            "上限額(円)", min_value=0, step=500,
            help="領収書金額がこの額を超えた場合、自動で上限額に調整",
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
                "region": row["地域"],
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

# 地域別集計
region_summary = {r: {"count": 0, "estimate": 0, "need_receipt": 0, "no_region": 0}
                   for r in REGIONS}
region_summary["未登録"] = {"count": 0, "estimate": 0, "need_receipt": 0, "no_region": 0}

for staff in participating:
    region = staff.get("region")
    if not region:
        region = "未登録"
    if region not in region_summary:
        region_summary[region] = {"count": 0, "estimate": 0, "need_receipt": 0, "no_region": 0}
    region_summary[region]["count"] += 1
    rule = rules_map.get(region)
    if rule:
        region_summary[region]["estimate"] += int(rule["max_amount"])
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

# 地域別テーブル
summary_rows = []
for region in REGIONS + ["未登録"]:
    data = region_summary.get(region, {"count": 0, "estimate": 0, "need_receipt": 0})
    if data["count"] == 0:
        continue
    rule = rules_map.get(region, {})
    summary_rows.append({
        "地域": region,
        "人数": data["count"],
        "上限額/人": f"¥{rule.get('max_amount', 0):,}" if rule else "—",
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
    "圏外スタッフの領収書金額を入力します。上限超過時は自動で上限額に調整されます。"
    "開催地在住者は入力不要（一律支給）。"
)

# 既存の請求情報
existing_claims = {c["staff_id"]: c for c in db.get_transport_claims(event_id)}

# 領収書必要な地域のスタッフだけフィルタ
receipt_staff = []
venue_staff = []
unregistered_staff = []
for staff in sorted(participating, key=lambda s: (s.get("region") or "zzz", s.get("no") or 0)):
    region = staff.get("region")
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
            col1, col2, col3 = st.columns([2, 1, 1])
            col1.write(f"{staff['name_jp']}（{staff.get('region', '')}）")
            col2.write(f"上限: ¥{rule['max_amount']:,}")
            col3.success(f"¥{rule['max_amount']:,} 自動支給")

# 住所未登録者
if unregistered_staff:
    with st.expander(f"⚠️ 住所未登録（{len(unregistered_staff)}名）"):
        for staff in unregistered_staff:
            st.warning(f"{staff['name_jp']}（NO.{staff.get('no', '-')}） — スタッフ管理で住所を登録してください")

# 領収書入力
if receipt_staff:
    st.markdown(f"**領収書入力（{len(receipt_staff)}名）:**")
    rows = []
    for staff, rule in receipt_staff:
        claim = existing_claims.get(staff["id"], {})
        rows.append({
            "_staff_id": staff["id"],
            "NO.": staff.get("no", ""),
            "名前": staff["name_jp"],
            "地域": staff.get("region", ""),
            "上限額": rule["max_amount"],
            "領収書金額(円)": int(claim.get("receipt_amount") or 0),
            "領収書あり": bool(claim.get("has_receipt", 0)),
            "備考": claim.get("note", "") or "",
        })

    claim_df = pd.DataFrame(rows)
    edited_claims = st.data_editor(
        claim_df,
        use_container_width=True,
        hide_index=True,
        disabled=["_staff_id", "NO.", "名前", "地域", "上限額"],
        column_config={
            "_staff_id": None,
            "上限額": st.column_config.NumberColumn("上限額", format="¥%d"),
            "領収書金額(円)": st.column_config.NumberColumn(
                "領収書金額(円)", min_value=0, step=100,
                help="上限超過時は自動で上限額に調整されます",
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
            if receipt > limit and limit > 0:
                approved = limit
                errors.append(f"{row['名前']}: ¥{receipt:,} → ¥{limit:,}（上限）に調整")
            else:
                approved = receipt
            # 領収書なし・金額0は支払いなし
            if not has_receipt:
                approved = 0
            db.upsert_transport_claim(
                event_id, staff_id, receipt_amount=receipt,
                approved_amount=approved, has_receipt=has_receipt,
                note=row["備考"] or "",
            )
            saved += 1
        st.success(f"{saved}件の領収書金額を保存しました")
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
    region = staff.get("region")
    rule = rules_map.get(region) if region else None
    if not rule:
        continue
    if rule.get("is_venue_region"):
        venue_total += int(rule["max_amount"])
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
