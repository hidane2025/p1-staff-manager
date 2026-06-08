"""P1 Staff Manager — 領収書PDF生成（legacy・支払い計算ページのプレビュー用）

2026-05-25 仕様変更（構造逆転）:
    領収書はお金を「受け取った人」が「支払った人」に対して発行する文書。
    P1 のケース: PRT（イベント主催）→ ディーラー へ業務委託費を支払う。
    よって発行者はディーラー側、宛名は PRT 側になる。

    PDF配置:
        宛名（上部）     = payer_name + 「御中」
        発行者（右下）   = real_name / address / email （ディーラー本人）

    主要パスは utils/receipt_v2.py を推奨。本モジュールは
    pages/3_支払い計算.py のスタッフ毎クイックDL用に残置。
"""

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
    """日本語フォントを登録（IPAex埋め込み・無ければCIDにフォールバック）。"""
    global _FONT_REGISTERED, FONT_JP
    if not _FONT_REGISTERED:
        from utils.jp_fonts import ensure_jp_fonts
        gothic, _mincho = ensure_jp_fonts()
        FONT_JP = gothic
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
    payer_name: str = "株式会社 PACIFIC RACING TEAM",
    payer_address: str = "",
    purpose: str = "ポーカー大会運営業務委託費として",
) -> bytes:
    """領収書PDFをバイト列で返す

    Args:
        receipt_no: 領収書番号
        real_name: 発行者（受領者）の本名＝ディーラー本名
        address: 発行者（受領者）の住所
        email: 発行者（受領者）のメール
        amount: 金額
        event_name: 大会名
        issue_date: 発行日 (YYYY-MM-DD)
        payer_name: 支払者名（領収書の宛名・主催者側）。デフォルトは PRT。
        payer_address: 支払者住所（オプション）。
        purpose: 但し書き

    Note:
        2026-05-25 構造逆転対応。旧版の issuer_name/issuer_address 引数は
        payer_name/payer_address にリネーム済み（意味も入れ替わっている）。
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

    # 宛名（支払者＋御中）
    c.setFont(FONT_JP, 12)
    y_name = height - 55 * mm
    c.drawString(15 * mm, y_name, f"{payer_name}  御中")
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

    # 発行者情報 右下（＝受領者＝ディーラー本人）
    y_issuer = 25 * mm
    c.setFont(FONT_JP, 11)
    c.drawRightString(width - 15 * mm, y_issuer + 10 * mm, real_name)
    c.setFont(FONT_JP, 8)
    if address:
        c.drawRightString(width - 15 * mm, y_issuer + 5 * mm, f"住所: {address}")
    if email:
        c.drawRightString(width - 15 * mm, y_issuer, f"E-mail: {email}")

    # NOTE: 旧版にあった「左下の宛先情報（住所/E-mail）」表示は、
    #       発行者欄と完全重複するため削除（2026-05-25）。

    c.setFillColor(black)
    c.showPage()
    c.save()

    buf.seek(0)
    return buf.read()
