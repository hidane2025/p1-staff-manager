"""P1 Staff Manager — 領収書PDF生成 v2（デジタル発行版）

既存 utils/receipt.py を改変せず、自前で拡張版を実装したモジュール。

主な追加点:
- 発行者情報をイベント設定から動的取得
- インボイス番号（適格請求書発行事業者登録番号）欄
  空なら非表示、入れたら自動表示（後日追加OK）
- 電子印影（URLまたはbytes）オプション
- 「電子発行につき印紙不要」注記
- 領収書番号の自動採番ヘルパー
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from io import BytesIO
from typing import Optional

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


def _ensure_font() -> None:
    global _FONT_REGISTERED
    if not _FONT_REGISTERED:
        pdfmetrics.registerFont(UnicodeCIDFont(FONT_JP))
        _FONT_REGISTERED = True


def _format_jpy(amount: int) -> str:
    return f"{amount:,}"


@dataclass(frozen=True)
class IssuerInfo:
    """発行者（Pacific）情報"""
    name: str = "株式会社パシフィック"
    address: str = ""
    tel: str = ""
    invoice_number: Optional[str] = None   # 空ならインボイス欄を描画しない
    seal_image_bytes: Optional[bytes] = None  # 電子印影（PNG推奨）


@dataclass(frozen=True)
class ReceiptInput:
    """領収書の内容"""
    receipt_no: str
    recipient_name: str
    recipient_address: str
    recipient_email: str
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


def generate_receipt_pdf_v2(
    receipt: ReceiptInput,
    issuer: IssuerInfo,
    include_stamp_free_note: bool = True,
) -> bytes:
    """領収書PDFを生成しバイト列で返す

    Args:
        receipt: 領収書の内容
        issuer: 発行者情報
        include_stamp_free_note: 「電子発行につき印紙不要」注記を入れる
    """
    _ensure_font()
    buf = BytesIO()
    width, height = landscape(A5)
    c = canvas.Canvas(buf, pagesize=landscape(A5))

    # --- タイトル ---
    c.setFont(FONT_JP, 24)
    c.drawCentredString(width / 2, height - 22 * mm, "領 収 書")

    # --- 右上: 領収書番号・発行日 ---
    c.setFont(FONT_JP, 9)
    c.drawRightString(width - 10 * mm, height - 32 * mm, f"No. {receipt.receipt_no}")
    c.drawRightString(width - 10 * mm, height - 37 * mm, f"発行日: {receipt.issue_date}")

    # --- 宛名 ---
    y_name = height - 52 * mm
    c.setFont(FONT_JP, 13)
    c.drawString(15 * mm, y_name, f"{receipt.recipient_name}  様")
    c.setStrokeColor(black)
    c.setLineWidth(0.5)
    c.line(15 * mm, y_name - 2 * mm, 120 * mm, y_name - 2 * mm)

    # --- 金額ボックス ---
    y_amount = height - 78 * mm
    c.setFillColor(HexColor("#F2F2F2"))
    c.rect(15 * mm, y_amount - 5 * mm, width - 30 * mm, 20 * mm, fill=1, stroke=0)
    c.setFillColor(black)
    c.setFont(FONT_JP, 11)
    c.drawString(20 * mm, y_amount + 10 * mm, "金  額")
    c.setFont(FONT_JP, 22)
    c.drawString(58 * mm, y_amount + 5 * mm, f"¥ {_format_jpy(receipt.amount)} -")
    c.setFont(FONT_JP, 9)
    c.drawString(58 * mm, y_amount - 1 * mm, "（税込）")

    # --- 但し書き ---
    y_purpose = y_amount - 15 * mm
    c.setFont(FONT_JP, 11)
    c.drawString(15 * mm, y_purpose, "但し ")
    c.drawString(30 * mm, y_purpose, receipt.purpose)
    c.drawString(15 * mm, y_purpose - 6 * mm, f"      （{receipt.event_name}）")
    c.line(15 * mm, y_purpose - 10 * mm, width - 15 * mm, y_purpose - 10 * mm)
    c.drawString(15 * mm, y_purpose - 17 * mm, "上記金額を正に領収いたしました。")

    # --- 発行者ブロック（右下） ---
    y_issuer = 37 * mm
    c.setFont(FONT_JP, 10)
    c.drawRightString(width - 15 * mm, y_issuer, f"{issuer.name}")
    c.setFont(FONT_JP, 8)
    if issuer.address:
        c.drawRightString(width - 15 * mm, y_issuer - 5 * mm, issuer.address)
    if issuer.tel:
        c.drawRightString(width - 15 * mm, y_issuer - 10 * mm, f"TEL: {issuer.tel}")

    # インボイス番号（空でない場合のみ描画）
    if issuer.invoice_number:
        c.setFont(FONT_JP, 8)
        c.drawRightString(
            width - 15 * mm, y_issuer - 15 * mm,
            f"適格請求書発行事業者登録番号: {issuer.invoice_number}",
        )

    # 電子印影（あれば）
    if issuer.seal_image_bytes:
        try:
            img = ImageReader(io.BytesIO(issuer.seal_image_bytes))
            seal_size = 22 * mm
            c.drawImage(img, width - 25 * mm - seal_size, y_issuer - 8 * mm,
                        seal_size, seal_size, mask='auto')
        except Exception:
            pass  # 印影エラーは無視（本体PDFは出す）

    # --- 宛先情報（小さく左下） ---
    c.setFont(FONT_JP, 7)
    c.setFillColor(HexColor("#666666"))
    if receipt.recipient_address:
        c.drawString(15 * mm, y_issuer - 5 * mm, f"住所: {receipt.recipient_address}")
    if receipt.recipient_email:
        c.drawString(15 * mm, y_issuer - 10 * mm, f"E-mail: {receipt.recipient_email}")

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
