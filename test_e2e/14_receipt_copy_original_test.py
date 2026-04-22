"""領収書PDF v2 原本／控え + 消費税額内訳の単体テスト

DB接続不要。生成したPDFを test_e2e/ 直下に書き出し、
sips で PNG化して test_e2e/screenshots/ に保存することで、
視覚的にレイアウトを検証できる。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.receipt_v2 import (  # noqa: E402
    IssuerInfo,
    ReceiptInput,
    _compute_tax_breakdown,
    build_receipt_no,
    generate_receipt_pdf_v2,
    today_jst_ymd,
)


OUT = Path(__file__).resolve().parent
SCREENSHOTS = OUT / "screenshots"
SCREENSHOTS.mkdir(exist_ok=True)


def _sample_receipt() -> ReceiptInput:
    """テスト用の共通レシートデータ"""
    return ReceiptInput(
        receipt_no=build_receipt_no(99, 12345, today_jst_ymd()),
        recipient_name="山田 太郎",
        recipient_address="東京都渋谷区神南1-2-3",
        recipient_email="yamada@example.com",
        amount=100_000,
        event_name="P1 Kyoto 2026 夏大会",
        issue_date=today_jst_ymd(),
    )


def _sample_issuer() -> IssuerInfo:
    return IssuerInfo(
        name="株式会社パシフィック",
        address="東京都港区XX",
        tel="03-0000-0000",
        invoice_number="T1234567890123",
    )


def _pdf_to_png(pdf_path: Path) -> Path | None:
    """sips で PDF を PNG 化して screenshots/ に保存。

    sips が使えない環境ではスキップ（Noneを返す）。
    """
    sips = shutil.which("sips")
    if not sips:
        return None
    png_path = SCREENSHOTS / f"{pdf_path.stem}.png"
    try:
        subprocess.run(
            [sips, "-s", "format", "png", str(pdf_path), "--out", str(png_path)],
            check=True,
            capture_output=True,
        )
        return png_path
    except subprocess.CalledProcessError:
        return None


def test_tax_breakdown_calc() -> None:
    """税込→(本体, 消費税) の内訳計算が正しいこと"""
    # 100,000（税込10%）→ 本体 90,909 / 税 9,091  （floor）
    body, tax = _compute_tax_breakdown(100_000)
    assert body + tax == 100_000, f"合計不一致: {body}+{tax}"
    assert body == 90_909, f"本体価格が期待値と異なる: {body}"
    assert tax == 9_091, f"消費税額が期待値と異なる: {tax}"

    # 1,100（税込10%）→ 本体 1,000 / 税 100 （きれいな例）
    body2, tax2 = _compute_tax_breakdown(1_100)
    assert (body2, tax2) == (1_000, 100), f"(1000,100)期待 got ({body2},{tax2})"

    # 0円は (0,0)
    assert _compute_tax_breakdown(0) == (0, 0)
    assert _compute_tax_breakdown(-1) == (0, 0)

    print("  ✅ 税額内訳計算 OK")


def test_pdf_original_no_tax() -> None:
    """原本・税額内訳なし"""
    pdf = generate_receipt_pdf_v2(
        receipt=_sample_receipt(),
        issuer=_sample_issuer(),
        document_type="original",
        tax_breakdown=False,
    )
    out = OUT / "test_receipt_original.pdf"
    out.write_bytes(pdf)
    assert len(pdf) > 2000, f"PDFサイズ異常: {len(pdf)}"
    png = _pdf_to_png(out)
    print(f"  ✅ {out.name} ({len(pdf):,} bytes)"
          + (f" → {png.name}" if png else " (sipsなし→PNG化スキップ)"))


def test_pdf_copy_no_tax() -> None:
    """控え・税額内訳なし"""
    pdf = generate_receipt_pdf_v2(
        receipt=_sample_receipt(),
        issuer=_sample_issuer(),
        document_type="copy",
        tax_breakdown=False,
    )
    out = OUT / "test_receipt_copy.pdf"
    out.write_bytes(pdf)
    assert len(pdf) > 2000
    png = _pdf_to_png(out)
    print(f"  ✅ {out.name} ({len(pdf):,} bytes)"
          + (f" → {png.name}" if png else " (sipsなし→PNG化スキップ)"))


def test_pdf_original_with_tax() -> None:
    """原本・税額内訳あり"""
    pdf = generate_receipt_pdf_v2(
        receipt=_sample_receipt(),
        issuer=_sample_issuer(),
        document_type="original",
        tax_breakdown=True,
    )
    out = OUT / "test_receipt_original_with_tax.pdf"
    out.write_bytes(pdf)
    assert len(pdf) > 2000
    png = _pdf_to_png(out)
    print(f"  ✅ {out.name} ({len(pdf):,} bytes)"
          + (f" → {png.name}" if png else " (sipsなし→PNG化スキップ)"))


def test_pdf_copy_with_tax() -> None:
    """控え・税額内訳あり"""
    pdf = generate_receipt_pdf_v2(
        receipt=_sample_receipt(),
        issuer=_sample_issuer(),
        document_type="copy",
        tax_breakdown=True,
    )
    out = OUT / "test_receipt_copy_with_tax.pdf"
    out.write_bytes(pdf)
    assert len(pdf) > 2000
    png = _pdf_to_png(out)
    print(f"  ✅ {out.name} ({len(pdf):,} bytes)"
          + (f" → {png.name}" if png else " (sipsなし→PNG化スキップ)"))


def test_document_type_differs() -> None:
    """original と copy で生成されたPDFが異なること（ラベル差分）"""
    receipt = _sample_receipt()
    issuer = _sample_issuer()
    pdf_o = generate_receipt_pdf_v2(
        receipt=receipt, issuer=issuer,
        document_type="original", tax_breakdown=False,
    )
    pdf_c = generate_receipt_pdf_v2(
        receipt=receipt, issuer=issuer,
        document_type="copy", tax_breakdown=False,
    )
    assert pdf_o != pdf_c, "原本と控えが同一バイト列になっている（ラベル描画が効いていない）"
    print("  ✅ 原本／控えのバイト列差分を確認")


def test_tax_breakdown_changes_pdf() -> None:
    """tax_breakdown True/False でPDFが異なること"""
    receipt = _sample_receipt()
    issuer = _sample_issuer()
    pdf_no = generate_receipt_pdf_v2(
        receipt=receipt, issuer=issuer,
        document_type="copy", tax_breakdown=False,
    )
    pdf_yes = generate_receipt_pdf_v2(
        receipt=receipt, issuer=issuer,
        document_type="copy", tax_breakdown=True,
    )
    assert pdf_no != pdf_yes, "tax_breakdownフラグがPDFに反映されていない"
    # 内訳ありの方がコンテンツが多いので通常サイズも大きい
    assert len(pdf_yes) >= len(pdf_no) - 200, \
        "内訳表示時にサイズが著しく減少している（描画漏れの疑い）"
    print("  ✅ 税額内訳 ON/OFF のバイト列差分を確認")


if __name__ == "__main__":
    print("=== 領収書PDF v2 原本／控え + 税額内訳 テスト ===")
    test_tax_breakdown_calc()
    test_pdf_original_no_tax()
    test_pdf_copy_no_tax()
    test_pdf_original_with_tax()
    test_pdf_copy_with_tax()
    test_document_type_differs()
    test_tax_breakdown_changes_pdf()
    print("\n✅ すべてパス")
