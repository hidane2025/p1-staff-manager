"""領収書PDF v2 単体テスト（DB接続不要）"""

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


def test_pdf_without_invoice() -> None:
    """インボイスなしパターン（Pacific現状）"""
    pdf = generate_receipt_pdf_v2(
        receipt=ReceiptInput(
            receipt_no=build_receipt_no(99, 12345, today_jst_ymd()),
            recipient_name="山田 太郎",
            recipient_address="東京都渋谷区神南1-2-3",
            recipient_email="yamada@example.com",
            amount=87500,
            event_name="P1 Kyoto 2026 夏大会",
            issue_date=today_jst_ymd(),
        ),
        issuer=IssuerInfo(
            name="株式会社パシフィック",
            address="東京都港区XX",
            tel="03-0000-0000",
            invoice_number=None,   # 空→非表示
        ),
    )
    out = OUT / "test_receipt_no_invoice.pdf"
    out.write_bytes(pdf)
    assert len(pdf) > 2000
    print(f"  ✅ {out.name} ({len(pdf):,} bytes)")


def test_pdf_with_invoice() -> None:
    """インボイスあり（後日追加シナリオ）"""
    pdf = generate_receipt_pdf_v2(
        receipt=ReceiptInput(
            receipt_no=build_receipt_no(99, 67890, today_jst_ymd()),
            recipient_name="佐藤 花子",
            recipient_address="大阪府大阪市北区梅田1-1-1",
            recipient_email="sato@example.com",
            amount=154500,
            event_name="P1 Kyoto 2026 夏大会",
            issue_date=today_jst_ymd(),
        ),
        issuer=IssuerInfo(
            name="株式会社パシフィック",
            address="東京都港区XX",
            tel="03-0000-0000",
            invoice_number="T1234567890123",  # 登録後
        ),
    )
    out = OUT / "test_receipt_with_invoice.pdf"
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


def test_pdf_without_recipient_info() -> None:
    """住所・メールが空でも落ちない"""
    pdf = generate_receipt_pdf_v2(
        receipt=ReceiptInput(
            receipt_no="R-TEST-001",
            recipient_name="匿名 太郎",
            recipient_address="",
            recipient_email="",
            amount=3000,
            event_name="テスト大会",
            issue_date="2026-04-17",
        ),
        issuer=IssuerInfo(name="株式会社パシフィック"),
    )
    assert len(pdf) > 2000
    print(f"  ✅ 必須最小構成でもPDF生成OK ({len(pdf):,} bytes)")


if __name__ == "__main__":
    print("=== 領収書PDF v2 単体テスト ===")
    test_token()
    test_pdf_without_invoice()
    test_pdf_with_invoice()
    test_pdf_without_recipient_info()
    print("\n✅ すべてパス")
