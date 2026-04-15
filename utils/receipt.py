"""P1 Staff Manager — 領収書PDF生成"""

from io import BytesIO
from reportlab.lib.pagesizes import A5, landscape
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, black
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

_FONT_REGISTERED = False
FONT_JP = "HeiseiKakuGo-W5"


def _ensure_font() -> None:
    global _FONT_REGISTERED
    if not _FONT_REGISTERED:
        pdfmetrics.registerFont(UnicodeCIDFont(FONT_JP))
        _FONT_REGISTERED = True


def _format_jpy(amount: int) -> str:
    """金額を3桁カンマ区切りに"""
    return f"{amount:,}"


def generate_receipt_pdf(
    receipt_no: str,
    real_name: str,
    address: str,
    email: str,
    amount: int,
    event_name: str,
    issue_date: str,
    issuer_name: str = "株式会社パシフィック",
    issuer_address: str = "",
    purpose: str = "ポーカー大会運営業務委託費として",
) -> bytes:
    """領収書PDFをバイト列で返す

    Args:
        receipt_no: 領収書番号
        real_name: 宛名（本名）
        address: 宛先住所
        email: 宛先メール
        amount: 金額
        event_name: 大会名
        issue_date: 発行日 (YYYY-MM-DD)
        issuer_name: 発行者（P1側）
        issuer_address: 発行者住所
        purpose: 但し書き
    """
    _ensure_font()

    buf = BytesIO()
    # A5横向き
    width, height = landscape(A5)
    c = canvas.Canvas(buf, pagesize=landscape(A5))

    # タイトル
    c.setFont(FONT_JP, 24)
    c.drawCentredString(width / 2, height - 25 * mm, "領 収 書")

    # 領収書番号・発行日 右上
    c.setFont(FONT_JP, 9)
    c.drawRightString(width - 10 * mm, height - 35 * mm, f"No. {receipt_no}")
    c.drawRightString(width - 10 * mm, height - 40 * mm, f"発行日: {issue_date}")

    # 宛名
    c.setFont(FONT_JP, 12)
    y_name = height - 55 * mm
    c.drawString(15 * mm, y_name, f"{real_name}  様")
    # 下線
    c.setStrokeColor(black)
    c.setLineWidth(0.5)
    c.line(15 * mm, y_name - 2 * mm, 120 * mm, y_name - 2 * mm)

    # 金額ボックス
    y_amount = height - 80 * mm
    c.setFillColor(HexColor("#F0F2F5"))
    c.rect(15 * mm, y_amount - 5 * mm, width - 30 * mm, 20 * mm, fill=1, stroke=0)
    c.setFillColor(black)

    c.setFont(FONT_JP, 11)
    c.drawString(20 * mm, y_amount + 10 * mm, "金  額")

    c.setFont(FONT_JP, 22)
    c.drawString(60 * mm, y_amount + 5 * mm, f"¥ {_format_jpy(amount)} -")
    c.setFont(FONT_JP, 9)
    c.drawString(60 * mm, y_amount - 1 * mm, "（税込）")

    # 但し書き
    y_purpose = y_amount - 15 * mm
    c.setFont(FONT_JP, 11)
    c.drawString(15 * mm, y_purpose, "但し ")
    c.drawString(30 * mm, y_purpose, purpose)
    c.drawString(15 * mm, y_purpose - 6 * mm, f"      （{event_name}）")
    c.line(15 * mm, y_purpose - 10 * mm, width - 15 * mm, y_purpose - 10 * mm)

    c.drawString(15 * mm, y_purpose - 17 * mm, "上記金額を正に領収いたしました。")

    # 発行者情報 右下
    y_issuer = 25 * mm
    c.setFont(FONT_JP, 9)
    c.drawRightString(width - 15 * mm, y_issuer + 10 * mm, f"発行者: {issuer_name}")
    if issuer_address:
        c.drawRightString(width - 15 * mm, y_issuer + 5 * mm, issuer_address)

    # 宛先情報 左下（小さく）
    c.setFont(FONT_JP, 7)
    c.setFillColor(HexColor("#666666"))
    if address:
        c.drawString(15 * mm, y_issuer + 5 * mm, f"住所: {address}")
    if email:
        c.drawString(15 * mm, y_issuer, f"E-mail: {email}")

    c.setFillColor(black)
    c.showPage()
    c.save()

    buf.seek(0)
    return buf.read()
