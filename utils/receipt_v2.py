"""P1 Staff Manager — 領収書PDF生成 v2（デジタル発行版）

既存 utils/receipt.py を改変せず、自前で拡張版を実装したモジュール。

## 領収書の構造（2026-05-25 修正）

領収書は「お金を受け取った人」が「お金を支払った人」に対して発行する文書。
P1 のケースでは:

    お金の流れ:  PRT（イベント主催）── 業務委託費 ──▶ ディーラー（受領）

    領収書を発行するのは「受領した側＝ディーラー」。
    宛先は「支払った側＝PRT」。

PDF上の配置:
    宛名（上部）      = payer_name（PRT等の主催者）＋「御中」
    発行者（右下）    = receiver_name / address / email（ディーラー本人）

## 主な機能
- 発行者情報（IssuerInfo）は電子印影のみ実用（ディーラー個人印は通常未使用）
- 「電子発行につき印紙不要」注記
- 領収書番号の自動採番ヘルパー
- 2026-04-21 拡張:
    * 原本／控えの2バージョン生成（右上に縦書きでネイビー色明記）
    * 消費税額の内訳表示（10%固定・税抜は切り捨て）
- 2026-05-25 仕様変更:
    * 構造逆転（payer/receiver の意味を明確化）
    * インボイス番号欄を完全削除（IssuerInfo.invoice_number は無視）
    * 左下の住所/メール重複表示を削除（発行者欄に統合）
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from io import BytesIO
from typing import Literal, Optional, Tuple

from reportlab.lib.colors import HexColor, black
from reportlab.lib.pagesizes import A5, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


JST = timezone(timedelta(hours=9))
FONT_JP = "HeiseiKakuGo-W5"
_FONT_REGISTERED = False

# 文書種別の指定値
DocumentType = Literal["original", "copy"]

# 消費税率（固定10%。将来軽減税率対応するなら引数化）
TAX_RATE_PERCENT = 10

# 原本／控え表記のラベル（縦書きで描画）
_DOC_LABELS: dict[str, str] = {
    "original": "原　本",
    "copy": "控　え",
}

# 原本／控えの表示色（ネイビー）
_DOC_LABEL_COLOR = HexColor("#1F3A5F")


def _ensure_font() -> None:
    global _FONT_REGISTERED
    if not _FONT_REGISTERED:
        pdfmetrics.registerFont(UnicodeCIDFont(FONT_JP))
        _FONT_REGISTERED = True


def _format_jpy(amount: int) -> str:
    return f"{amount:,}"


def _compute_tax_breakdown(amount_incl_tax: int,
                            tax_rate_percent: int = TAX_RATE_PERCENT) -> Tuple[int, int]:
    """税込金額から（税抜本体, 消費税額）を返す。

    仕様:
        - 税抜 = 税込 × 100 / (100 + 税率)   ← 切り捨て（floor）
        - 消費税 = 税込 - 税抜
        これにより合計は必ず税込額と一致する。

    Args:
        amount_incl_tax: 税込金額（正の整数）
        tax_rate_percent: 税率（パーセント。10% なら 10）

    Returns:
        (税抜本体, 消費税額)
    """
    if amount_incl_tax <= 0:
        return (0, 0)
    denom = 100 + tax_rate_percent
    body = math.floor(amount_incl_tax * 100 / denom)
    tax = amount_incl_tax - body
    return (body, tax)


@dataclass(frozen=True)
class IssuerInfo:
    """発行者（＝ディーラー）の補助情報。

    2026-05-25 仕様変更:
        主要な発行者情報は ReceiptInput.receiver_* に移行。
        本クラスは「電子印影（seal_image_bytes）」のみ実用。
        他のフィールド（name/address/tel/invoice_number）は後方互換のため
        残置するが、PDF描画では使用しない。
    """
    name: str = ""                          # @deprecated: ReceiptInput.receiver_name を使用
    address: str = ""                       # @deprecated
    tel: str = ""                           # @deprecated
    invoice_number: Optional[str] = None    # @deprecated: 中野指示で完全非表示（2026-05-25）
    seal_image_bytes: Optional[bytes] = None  # 電子印影（PNG推奨・任意）


@dataclass(frozen=True)
class ReceiptInput:
    """領収書の内容

    Args:
        payer_name: 領収書の宛名（お金を支払った会社）。例: "株式会社 PACIFIC RACING TEAM"
                    PDFでは「{payer_name}  御中」として描画される。
        receiver_name: 発行者名（お金を受け取った個人＝ディーラー本名）。
                       PDF右下の発行者ブロックに描画される。
        receiver_address: 発行者（ディーラー）の住所。
        receiver_email: 発行者（ディーラー）のメールアドレス。
        amount: 領収金額（税込）。
        event_name: 大会名。但し書きに括弧付きで表示される。
        issue_date: 発行日（YYYY-MM-DD）。
        purpose: 但し書きの本文。
    """
    receipt_no: str
    # 宛名（お金を支払った会社）
    payer_name: str
    # 発行者（お金を受け取った個人＝ディーラー）
    receiver_name: str
    receiver_address: str
    receiver_email: str
    amount: int
    event_name: str
    issue_date: str                    # YYYY-MM-DD
    purpose: str = "ポーカー大会運営業務委託費として"


def build_receipt_no(event_id: int, staff_id: int, issue_date_ymd: str) -> str:
    """領収書No.を決定的に生成（E=eventId, S=staffId, D=issueDate）"""
    compact = issue_date_ymd.replace("-", "")
    return f"R-{compact}-E{event_id}-S{staff_id}"


def today_jst_ymd() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def _draw_document_type_label(
    c: canvas.Canvas,
    page_width: float,
    page_height: float,
    document_type: DocumentType,
) -> None:
    """PDF右上に「原　本」or「控　え」を縦書きで描画。

    ネイビー色、ややスペース広めの縦書き（2文字とも）。
    位置は右端から約 8mm 内側、上端から約 18mm 内側のボックスに収める。
    """
    label = _DOC_LABELS.get(document_type)
    if not label:
        return

    # 元色の退避
    c.saveState()
    try:
        c.setFillColor(_DOC_LABEL_COLOR)
        c.setFont(FONT_JP, 14)

        # 1文字あたり約 7mm 間隔で縦並び
        x = page_width - 10 * mm
        y_start = page_height - 14 * mm
        line_height = 7 * mm

        # 全角スペース含む2文字（"原　本" / "控　え"）を縦に
        for idx, ch in enumerate(label):
            c.drawRightString(x, y_start - idx * line_height, ch)
    finally:
        c.restoreState()


def _draw_amount_block(
    c: canvas.Canvas,
    page_width: float,
    y_amount: float,
    amount: int,
    tax_breakdown: bool,
) -> float:
    """金額ブロックを描画し、「但し書き」開始Y座標を返す。

    tax_breakdown=True のとき、金額ボックスを下方向に伸ばし、内訳2行を追加表示。
    y_amount は「金額」ラベル周辺の基準Y座標（通常はページ上端から 78mm）。
    """
    # 高さ: 通常 20mm、内訳あり 32mm（下方向に12mm伸ばす）
    extra_mm = 12 if tax_breakdown else 0
    box_height_mm = 20 + extra_mm
    box_bottom = y_amount - 5 * mm - extra_mm * mm
    # box_top は box_bottom + box_height。位置関係の明示用。
    # 既存レイアウトでは y_amount 周辺（金額・ラベル）は従来どおりの高さ。

    # 背景グレーのボックス
    c.setFillColor(HexColor("#F2F2F2"))
    c.rect(
        15 * mm,
        box_bottom,
        page_width - 30 * mm,
        box_height_mm * mm,
        fill=1,
        stroke=0,
    )

    # 「金 額」ラベル
    c.setFillColor(black)
    c.setFont(FONT_JP, 11)
    c.drawString(20 * mm, y_amount + 10 * mm, "金  額")

    # メイン金額
    c.setFont(FONT_JP, 22)
    c.drawString(58 * mm, y_amount + 5 * mm, f"¥ {_format_jpy(amount)} -")

    # （税込）
    c.setFont(FONT_JP, 9)
    c.drawString(58 * mm, y_amount - 1 * mm, "（税込）")

    if tax_breakdown:
        body, tax = _compute_tax_breakdown(amount)
        c.setFont(FONT_JP, 9)
        # 内訳1行目: 本体価格（（税込）のすぐ下、ボックス内）
        c.drawString(
            62 * mm, y_amount - 7 * mm,
            f"内 本体価格 ¥{_format_jpy(body)}",
        )
        # 内訳2行目: 消費税額
        c.drawString(
            62 * mm, y_amount - 13 * mm,
            f"内 消費税額 ¥{_format_jpy(tax)}（{TAX_RATE_PERCENT}%）",
        )

    # 「但し書き」の開始Y座標 = 金額ボックス下端から 5mm 下げた位置
    return box_bottom - 5 * mm


def generate_receipt_pdf_v2(
    receipt: ReceiptInput,
    issuer: IssuerInfo,
    include_stamp_free_note: bool = True,
    document_type: DocumentType = "copy",
    tax_breakdown: bool = False,
) -> bytes:
    """領収書PDFを生成しバイト列で返す

    Args:
        receipt: 領収書の内容
        issuer: 発行者情報
        include_stamp_free_note: 「電子発行につき印紙不要」注記を入れる
        document_type: "original"（発行者保管用）or "copy"（受領者配布用）
        tax_breakdown: True で消費税額の内訳を表示
    """
    _ensure_font()
    buf = BytesIO()
    width, height = landscape(A5)
    c = canvas.Canvas(buf, pagesize=landscape(A5))

    # --- 原本／控え 右上ラベル（縦書き・ネイビー） ---
    _draw_document_type_label(c, width, height, document_type)

    # --- タイトル ---
    c.setFont(FONT_JP, 24)
    c.drawCentredString(width / 2, height - 22 * mm, "領 収 書")

    # --- 右上: 領収書番号・発行日 ---
    # 縦書きラベルと被らないよう、少し左にずらす
    c.setFont(FONT_JP, 9)
    right_x = width - 22 * mm
    c.drawRightString(right_x, height - 32 * mm, f"No. {receipt.receipt_no}")
    c.drawRightString(right_x, height - 37 * mm, f"発行日: {receipt.issue_date}")

    # --- 宛名（支払者＝PRT等に「御中」） ---
    # 2026-05-25 仕様変更: 旧版はディーラー名 + 様 を描画していたが、
    # 領収書は受領側（ディーラー）が発行する文書なので、宛名は支払者側になる。
    y_name = height - 52 * mm
    c.setFont(FONT_JP, 13)
    c.drawString(15 * mm, y_name, f"{receipt.payer_name}  御中")
    c.setStrokeColor(black)
    c.setLineWidth(0.5)
    c.line(15 * mm, y_name - 2 * mm, 120 * mm, y_name - 2 * mm)

    # --- 金額ボックス（内訳表示に応じて可変） ---
    # 税額内訳ありの場合は金額ブロックを少し上げて、下段（但し書き・発行者情報）との
    # 重なりを防ぐ。
    y_amount = height - (70 * mm if tax_breakdown else 78 * mm)
    y_purpose = _draw_amount_block(
        c, width, y_amount, receipt.amount, tax_breakdown
    )

    # --- 但し書き ---
    c.setFillColor(black)
    c.setFont(FONT_JP, 11)
    c.drawString(15 * mm, y_purpose, "但し ")
    c.drawString(30 * mm, y_purpose, receipt.purpose)
    c.drawString(15 * mm, y_purpose - 6 * mm, f"      （{receipt.event_name}）")
    c.line(15 * mm, y_purpose - 10 * mm, width - 15 * mm, y_purpose - 10 * mm)
    c.drawString(15 * mm, y_purpose - 17 * mm, "上記金額を正に領収いたしました。")

    # --- 発行者ブロック（右下） = 受領者＝ディーラーの情報 ---
    # 2026-05-25 仕様変更:
    #   旧版は PRT（issuer_info）の情報を描画していたが、領収書を発行するのは
    #   受領した側（ディーラー本人）なので、ここにはディーラーの本名・住所・
    #   メールアドレスを表示する。
    #   インボイス番号は中野指示で完全削除（ディーラー個人は通常持たないため）。
    y_issuer = 37 * mm
    c.setFont(FONT_JP, 11)
    c.drawRightString(width - 15 * mm, y_issuer, f"{receipt.receiver_name}")
    c.setFont(FONT_JP, 8)
    if receipt.receiver_address:
        c.drawRightString(
            width - 15 * mm, y_issuer - 5 * mm,
            f"住所: {receipt.receiver_address}",
        )
    if receipt.receiver_email:
        c.drawRightString(
            width - 15 * mm, y_issuer - 10 * mm,
            f"E-mail: {receipt.receiver_email}",
        )

    # 電子印影（任意・通常は未使用）
    if issuer.seal_image_bytes:
        try:
            img = ImageReader(io.BytesIO(issuer.seal_image_bytes))
            seal_size = 22 * mm
            c.drawImage(img, width - 25 * mm - seal_size, y_issuer - 8 * mm,
                        seal_size, seal_size, mask='auto')
        except Exception:
            pass  # 印影エラーは無視（本体PDFは出す）

    # NOTE: 旧版にあった「左下の宛先情報（住所/E-mail）」表示は、
    #       発行者欄と完全重複するため削除（2026-05-25）。

    # --- 印紙不要注記（下端） ---
    if include_stamp_free_note:
        c.setFont(FONT_JP, 7)
        c.setFillColor(HexColor("#999999"))
        c.drawCentredString(
            width / 2, 8 * mm,
            "※ 本領収書は電子的に発行されたものです。電子領収書には収入印紙の貼付は不要です。",
        )

    c.setFillColor(black)
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()
