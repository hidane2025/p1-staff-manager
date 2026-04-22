"""本番DBにテストデータを完備させて、全URLを一覧出力する

前提: 7_setup_completed_event.py が事前に実行済みで、
      P1 Kyoto 2026 夏大会が存在し、40名の支払済み＋40件の領収書発行済み。

このスクリプトは追加で:
- 20名分の契約書を発行（業務委託契約）
- 5名分は契約を閲覧済み(viewed)状態に
- 3名分は契約を署名済み(signed)状態に
- 最後にテスト可能なURL一覧を整理して出力
"""

from __future__ import annotations

import io
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
import db
from utils import contract_db, contract_issuer


BASE_HOST = "https://hidane2025-p1-staff-manager-app-fw8ggg.streamlit.app"


def make_sig(name: str) -> bytes:
    img = Image.new("RGBA", (400, 150), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    # 手書き風の曲線
    random.seed(hash(name) & 0xFFFF)
    pts = []
    x, y = 20, 80
    for i in range(20):
        pts.append((x, y))
        x += 18
        y += random.randint(-25, 25)
        y = max(30, min(120, y))
    d.line(pts, fill=(0, 0, 20, 255), width=4)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main():
    client = db.get_client()

    # 1. 大会存在確認
    events = client.table("p1_events").select("id, name").ilike(
        "name", "%P1 Kyoto 2026%").execute().data
    if not events:
        print("❌ P1 Kyoto 2026 夏大会 が見つかりません。")
        print("   先に `python3 test_e2e/7_setup_completed_event.py` を実行してください。")
        return 1
    event_id = events[0]["id"]
    event_name = events[0]["name"]
    print(f"✅ 対象イベント: {event_name} (id={event_id})")

    # 2. 既存の契約をクリーンアップ（このイベント or event_id=None のテスト残骸）
    existing = client.table("p1_contracts").select("id, signed_pdf_path, unsigned_pdf_path, signature_image_path").or_(
        f"event_id.eq.{event_id},event_id.is.null").execute().data
    if existing:
        from utils import contract_storage
        for c in existing:
            for p in [c.get("unsigned_pdf_path"), c.get("signed_pdf_path"), c.get("signature_image_path")]:
                if p:
                    try:
                        contract_storage._storage().from_(contract_storage.BUCKET).remove([p])
                    except Exception:
                        pass
            client.table("p1_contracts").delete().eq("id", c["id"]).execute()
        print(f"🧹 既存契約 {len(existing)}件 クリーンアップ")

    # 3. テンプレート確認
    templates = contract_db.list_templates()
    if not templates:
        print("❌ テンプレートが無い")
        return 1
    tpl_outsourcing = next((t for t in templates if t.get("doc_type") == "outsourcing"), templates[0])
    print(f"✅ 使用テンプレ: {tpl_outsourcing['name']}")

    # 4. スタッフ抽出（このイベントで支払い発生している20名）
    payments = client.table("p1_payments").select(
        "staff_id"
    ).eq("event_id", event_id).limit(25).execute().data
    staff_ids = list({p["staff_id"] for p in payments})[:20]
    if not staff_ids:
        print("❌ 支払いレコードが無い")
        return 1
    print(f"✅ 対象スタッフ {len(staff_ids)}名")

    # 5. 契約発行
    print("\n=== 契約発行中 ===")
    result = contract_issuer.issue_contracts_bulk(
        tpl_outsourcing["id"], staff_ids,
        event_id=event_id, valid_days=30,
    )
    print(f"✅ 契約発行: 成功 {result['success']} / 失敗 {result['failure']}")
    contract_results = [r for r in result["results"] if r.get("ok")]

    # 6. 5名分を閲覧済み（viewed）に
    for c in contract_results[:5]:
        contract_db.mark_viewed(c["contract_id"])
    print(f"✅ 5名を viewed 状態に")

    # 7. 3名分を署名済み（signed）に
    signed_count = 0
    for c in contract_results[5:8]:
        cdetail = client.table("p1_contracts").select(
            "staff_id"
        ).eq("id", c["contract_id"]).execute().data
        if not cdetail:
            continue
        sid = cdetail[0]["staff_id"]
        staff = client.table("p1_staff").select("name_jp, real_name").eq(
            "id", sid).execute().data
        nm = staff[0].get("real_name") or staff[0].get("name_jp") or "署名者"
        sig = make_sig(nm)
        sign_res = contract_issuer.apply_signature(
            c["contract_id"], sig,
            signer_ip="192.168.0.100", signer_ua="TestAgent/1.0",
        )
        if sign_res.get("ok"):
            signed_count += 1
    print(f"✅ {signed_count}名を signed 状態に")

    # 8. URL一覧出力
    print("\n" + "=" * 80)
    print("📋 テスト可能なURL一覧")
    print("=" * 80)

    # 領収書URLs（既存）
    print("\n### 📄 領収書 DLリンク（有効期限内）\n")
    receipts = client.table("p1_payments").select(
        "id, staff_id, total_amount, receipt_token, receipt_no, "
        "receipt_token_expires_at, p1_staff(name_jp, real_name)"
    ).eq("event_id", event_id).not_.is_("receipt_token", "null").limit(10).execute().data
    for i, p in enumerate(receipts, 1):
        staff = p.get("p1_staff")
        if isinstance(staff, list):
            staff = staff[0] if staff else {}
        if not isinstance(staff, dict):
            staff = {}
        url = f"{BASE_HOST}/receipt_download?token={p['receipt_token']}"
        print(f"[{i}] {staff.get('real_name') or staff.get('name_jp', '')} "
              f"¥{p['total_amount']:,}")
        print(f"    {url}")
        print()

    # 契約URLs（未署名）
    print("\n### 📝 契約書 署名URL（draft/sent/viewed = 署名前）\n")
    pending = client.table("p1_contracts").select(
        "id, contract_no, status, signing_token, p1_staff(name_jp, real_name)"
    ).eq("event_id", event_id).in_("status", ["sent", "viewed"]).limit(10).execute().data
    for i, c in enumerate(pending, 1):
        staff = c.get("p1_staff")
        if isinstance(staff, list):
            staff = staff[0] if staff else {}
        if not isinstance(staff, dict):
            staff = {}
        url = f"{BASE_HOST}/contract_sign?token={c['signing_token']}"
        print(f"[{i}] {staff.get('real_name') or staff.get('name_jp', '')} "
              f"[{c['status']}] {c['contract_no']}")
        print(f"    {url}")
        print()

    # 契約URLs（署名済み）
    print("\n### ✍ 署名済み契約URL（開くと「既に署名済み」と表示される）\n")
    signed = client.table("p1_contracts").select(
        "id, contract_no, status, signing_token, p1_staff(name_jp, real_name)"
    ).eq("event_id", event_id).eq("status", "signed").limit(5).execute().data
    for i, c in enumerate(signed, 1):
        staff = c.get("p1_staff")
        if isinstance(staff, list):
            staff = staff[0] if staff else {}
        if not isinstance(staff, dict):
            staff = {}
        url = f"{BASE_HOST}/contract_sign?token={c['signing_token']}"
        print(f"[{i}] {staff.get('real_name') or staff.get('name_jp', '')} "
              f"{c['contract_no']}")
        print(f"    {url}")
        print()

    # 管理画面URLs
    print("\n### 🛠 管理画面URL\n")
    print(f"ホーム:       {BASE_HOST}/")
    print(f"領収書発行:    {BASE_HOST}/91_領収書発行")
    print(f"発行者設定:    {BASE_HOST}/92_発行者設定")
    print(f"契約書テンプレ: {BASE_HOST}/93_契約書テンプレ")
    print(f"契約書発行:    {BASE_HOST}/94_契約書発行")
    print(f"年間累計:     {BASE_HOST}/年間累計")

    print("\n" + "=" * 80)
    print("🧪 テストシナリオ")
    print("=" * 80)
    print("""
1. 【領収書DL】上記領収書URLをどれか1つ別タブで開く
   → 「PDFをダウンロード」ボタン → 実際にPDF取得

2. 【契約書閲覧（未署名）】上記契約書URLを開く
   → 契約内容が表示 → 署名パッドで手書き → 「署名して送信」

3. 【二重署名防止】一度署名したURLを再度開く
   → 「すでに署名済み」と表示＋署名済みPDF DLボタン

4. 【無効URL】URLのtoken部分を「xxx」等に変更して開く
   → 「このリンクは無効です」警告

5. 【管理者画面】91_領収書発行 でコピーボタンの動作確認
    """)
    return 0


if __name__ == "__main__":
    sys.exit(main())
