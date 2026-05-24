"""領収書PDF v2 単体テスト（DB接続不要）

2026-05-25 仕様変更（構造逆転）に追随:
    - 宛名は支払者（PRT等）＋「御中」
    - 発行者欄はディーラー本人の本名・住所・メール
    - インボイス番号欄は完全削除（テストでも検証不要）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.receipt_v2 import (
    IssuerInfo,
    ReceiptInput,
    build_receipt_no,
    generate_receipt_pdf_v2,
    today_jst_ymd,
)
from utils.receipt_token import generate_token, expiry_iso, is_expired


OUT = Path(__file__).resolve().parent


def test_pdf_basic() -> None:
    """基本パターン（インボイス表示なし＝中野指示の現状運用）"""
    pdf = generate_receipt_pdf_v2(
        receipt=ReceiptInput(
            receipt_no=build_receipt_no(99, 12345, today_jst_ymd()),
            payer_name="株式会社 PACIFIC RACING TEAM",
            receiver_name="山田 太郎",
            receiver_address="東京都渋谷区神南1-2-3",
            receiver_email="yamada@example.com",
            amount=87500,
            event_name="P1 Kyoto 2026 夏大会",
            issue_date=today_jst_ymd(),
        ),
        issuer=IssuerInfo(),  # 印影なし
    )
    out = OUT / "test_receipt_basic.pdf"
    out.write_bytes(pdf)
    assert len(pdf) > 2000
    print(f"  ✅ {out.name} ({len(pdf):,} bytes)")


def test_pdf_long_payer_name() -> None:
    """支払者名が長いケース（折返し・はみ出し確認用）"""
    pdf = generate_receipt_pdf_v2(
        receipt=ReceiptInput(
            receipt_no=build_receipt_no(99, 67890, today_jst_ymd()),
            payer_name="株式会社 PACIFIC RACING TEAM（イベント主催）",
            receiver_name="佐藤 花子",
            receiver_address="大阪府大阪市北区梅田1-1-1",
            receiver_email="sato@example.com",
            amount=154500,
            event_name="P1 Kyoto 2026 夏大会",
            issue_date=today_jst_ymd(),
        ),
        issuer=IssuerInfo(),
    )
    out = OUT / "test_receipt_long_payer.pdf"
    out.write_bytes(pdf)
    assert len(pdf) > 2000
    print(f"  ✅ {out.name} ({len(pdf):,} bytes)")


def test_token() -> None:
    """トークン生成＋期限"""
    t1 = generate_token()
    t2 = generate_token()
    assert t1 != t2
    assert len(t1) > 30
    print(f"  ✅ トークン生成OK (length={len(t1)})")
    exp = expiry_iso(valid_days=7)
    assert not is_expired(exp)
    assert is_expired(None)
    assert is_expired("")
    # 過去日付
    past = expiry_iso(valid_days=-1)
    assert is_expired(past)
    print(f"  ✅ 期限検証OK")


def test_pdf_minimal_receiver_info() -> None:
    """受領者の住所・メールが空でも落ちない（最小構成）"""
    pdf = generate_receipt_pdf_v2(
        receipt=ReceiptInput(
            receipt_no="R-TEST-001",
            payer_name="株式会社 PACIFIC RACING TEAM",
            receiver_name="匿名 太郎",
            receiver_address="",
            receiver_email="",
            amount=3000,
            event_name="テスト大会",
            issue_date="2026-04-17",
        ),
        issuer=IssuerInfo(),
    )
    assert len(pdf) > 2000
    print(f"  ✅ 必須最小構成でもPDF生成OK ({len(pdf):,} bytes)")


def test_invoice_number_is_ignored() -> None:
    """IssuerInfo.invoice_number に値を入れても、PDFサイズが変わらない（描画されない）

    中野指示により、インボイス番号は完全に非表示。
    """
    common = dict(
        receipt_no="R-TEST-002",
        payer_name="株式会社 PACIFIC RACING TEAM",
        receiver_name="検証 太郎",
        receiver_address="",
        receiver_email="",
        amount=10000,
        event_name="テスト",
        issue_date="2026-05-25",
    )
    pdf_a = generate_receipt_pdf_v2(
        receipt=ReceiptInput(**common),
        issuer=IssuerInfo(invoice_number=None),
    )
    pdf_b = generate_receipt_pdf_v2(
        receipt=ReceiptInput(**common),
        issuer=IssuerInfo(invoice_number="T9999999999999"),
    )
    # 完全一致でなくてもよいが、明らかな差分は出ない想定。
    # （バイト単位の確定的同一性はreportlabに保証されないため、サイズ近似で確認）
    assert abs(len(pdf_a) - len(pdf_b)) < 200, (
        f"invoice_number が描画に影響している疑い: {len(pdf_a)} vs {len(pdf_b)}"
    )
    print(f"  ✅ invoice_number は描画されない（サイズ差 {abs(len(pdf_a) - len(pdf_b))}）")


if __name__ == "__main__":
    print("=== 領収書PDF v2 単体テスト ===")
    test_token()
    test_pdf_basic()
    test_pdf_long_payer_name()
    test_pdf_minimal_receiver_info()
    test_invoice_number_is_ignored()
    print("\n✅ すべてパス")
