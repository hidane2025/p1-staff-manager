"""契約書 発行→署名 E2Eテスト（実DB接続）"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw

import db  # type: ignore
from utils import contract_db, contract_issuer, contract_storage


PASS: list[str] = []
FAIL: list[str] = []


def ok(m: str) -> None:
    PASS.append(m); print(f"  ✅ {m}")


def ng(m: str) -> None:
    FAIL.append(m); print(f"  ❌ {m}")


def make_sig_png() -> bytes:
    img = Image.new("RGBA", (400, 150), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.line([(20, 80), (100, 40), (180, 90), (260, 50), (340, 85)],
                fill=(0, 0, 0, 255), width=4)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def cleanup_test_contracts() -> None:
    client = db.get_client()
    rows = client.table("p1_contracts").select("id, contract_no, unsigned_pdf_path, signed_pdf_path, signature_image_path").execute().data
    for r in rows:
        if (r.get("contract_no") or "").startswith("C-") and "T999" in (r.get("contract_no") or ""):
            for path in [r.get("unsigned_pdf_path"), r.get("signed_pdf_path"), r.get("signature_image_path")]:
                if path:
                    try:
                        contract_storage._storage().from_(contract_storage.BUCKET).remove([path])
                    except Exception:
                        pass
            client.table("p1_contracts").delete().eq("id", r["id"]).execute()


def main() -> int:
    print("=== 契約書 E2Eテスト ===\n")

    # 0. 事前掃除
    cleanup_test_contracts()
    ok("事前掃除完了")

    # 1. テンプレート一覧取得
    print("\n--- 1. テンプレート確認 ---")
    templates = contract_db.list_templates()
    if not templates:
        ng("テンプレートが無い")
        return 1
    ok(f"テンプレート {len(templates)}件 取得")
    tpl = templates[0]
    print(f"  使用テンプレート: {tpl['name']} ({tpl['version']})")

    # 2. 既存スタッフ取得（1名）
    print("\n--- 2. テスト用スタッフ取得 ---")
    client = db.get_client()
    staff = client.table("p1_staff").select(
        "id, no, name_jp, real_name, address, email, role"
    ).gte("no", 100).lte("no", 199).limit(1).execute().data
    if not staff:
        # テストスタッフ作成
        r = client.table("p1_staff").insert({
            "no": 999,
            "name_jp": "契約テスト",
            "real_name": "契約 太郎",
            "address": "東京都新宿区テスト1-2-3",
            "email": "contract_test@example.com",
            "role": "Dealer",
            "employment_type": "contractor",
        }).execute()
        test_staff_id = r.data[0]["id"]
        ok(f"テストスタッフ作成 id={test_staff_id}")
    else:
        test_staff_id = staff[0]["id"]
        ok(f"既存スタッフ使用 {staff[0].get('name_jp')}")

    # 3. 契約発行
    print("\n--- 3. 契約発行 ---")
    t0 = time.time()
    result = contract_issuer.issue_contract(
        template_id=tpl["id"], staff_id=test_staff_id, valid_days=14,
    )
    dt = time.time() - t0
    if not result.get("ok"):
        ng(f"発行失敗: {result.get('error')}")
        return 2
    contract_id = result["contract_id"]
    contract_no = result["contract_no"]
    token = result["token"]
    ok(f"契約発行OK id={contract_id} No={contract_no} ({dt:.1f}秒)")

    # 4. トークン検索
    print("\n--- 4. トークン検索 ---")
    found = contract_db.find_contract_by_token(token)
    if found and found["id"] == contract_id:
        ok("トークン検索OK")
    else:
        ng(f"トークン検索失敗: {found}")

    # 5. 未署名PDF DL
    print("\n--- 5. 未署名PDF DL ---")
    pdf_bytes = contract_storage.download_bytes(found["unsigned_pdf_path"])
    if pdf_bytes and pdf_bytes[:4] == b"%PDF":
        ok(f"未署名PDF取得OK ({len(pdf_bytes):,} bytes)")
        out_path = Path(__file__).resolve().parent / "test_contract_e2e_unsigned.pdf"
        out_path.write_bytes(pdf_bytes)
    else:
        ng("PDF取得失敗")

    # 6. 閲覧マーク
    print("\n--- 6. 閲覧マーク ---")
    contract_db.mark_viewed(contract_id)
    after = client.table("p1_contracts").select("status, view_count").eq(
        "id", contract_id).execute().data[0]
    if after["status"] == "viewed" and after["view_count"] == 1:
        ok(f"閲覧マークOK (status=viewed, view_count=1)")
    else:
        ng(f"閲覧マーク失敗: {after}")

    # 7. 署名実行
    print("\n--- 7. 署名実行 ---")
    sig_png = make_sig_png()
    sign_result = contract_issuer.apply_signature(
        contract_id, sig_png,
        signer_ip="192.168.1.1", signer_ua="test-agent/1.0",
    )
    if sign_result.get("ok"):
        ok(f"署名OK hash={sign_result['content_hash'][:16]}")
    else:
        ng(f"署名失敗: {sign_result.get('error')}")
        return 3

    # 8. 署名済PDF DL
    print("\n--- 8. 署名済PDF DL ---")
    signed_pdf = contract_storage.download_bytes(sign_result["signed_pdf_path"])
    if signed_pdf and signed_pdf[:4] == b"%PDF":
        ok(f"署名済PDF取得OK ({len(signed_pdf):,} bytes)")
        out_path = Path(__file__).resolve().parent / "test_contract_e2e_signed.pdf"
        out_path.write_bytes(signed_pdf)
    else:
        ng("署名済PDF取得失敗")

    # 9. 二重署名防止
    print("\n--- 9. 二重署名防止 ---")
    dup = contract_issuer.apply_signature(contract_id, sig_png)
    if not dup.get("ok") and "すでに署名" in str(dup.get("error", "")):
        ok("二重署名拒否OK")
    else:
        ng(f"二重署名を拒否できず: {dup}")

    # 10. 掃除
    print("\n--- 10. 掃除 ---")
    cleanup_test_contracts()
    ok("事後掃除完了")

    print(f"\n=== 結果: PASS {len(PASS)} / FAIL {len(FAIL)} ===")
    return 0 if not FAIL else 4


if __name__ == "__main__":
    sys.exit(main())
