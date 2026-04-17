"""P1 Staff Manager — 契約書PDF生成

Markdownテンプレート + 変数埋め込み + 電子署名画像を合成して
最終的な署名済みPDFを生成する。

- 署名前PDF: テンプレートを埋め込み変数でレンダリング
- 署名後PDF: 署名前PDFに署名画像を合成し、ハッシュ値をメタデータとして保存
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Optional

from reportlab.lib.colors import HexColor, black
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


JST = timezone(timedelta(hours=9))
FONT_JP_REG = "HeiseiKakuGo-W5"
FONT_JP_MIN = "HeiseiMin-W3"
_FONT_REGISTERED = False


def _ensure_font() -> None:
    global _FONT_REGISTERED
    if not _FONT_REGISTERED:
        pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
        pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
        _FONT_REGISTERED = True


def today_jst_ymd() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def build_contract_no(template_id: int, staff_id: int, issue_date_ymd: str) -> str:
    compact = issue_date_ymd.replace("-", "")
    return f"C-{compact}-T{template_id}-S{staff_id}"


@dataclass(frozen=True)
class ContractVariables:
    """契約書に埋め込む変数"""
    staff_name: str
    staff_address: str = ""
    staff_email: str = ""
    role: str = ""
    event_name: str = ""
    issuer_name: str = "株式会社パシフィック"
    issuer_address: str = ""
    issue_date: str = ""
    confidentiality_years: str = "3"

    def to_dict(self) -> dict[str, str]:
        return {
            "staff_name": self.staff_name,
            "staff_address": self.staff_address,
            "staff_email": self.staff_email,
            "role": self.role or "スタッフ",
            "event_name": self.event_name or "大会全般",
            "issuer_name": self.issuer_name,
            "issuer_address": self.issuer_address,
            "issue_date": self.issue_date or today_jst_ymd(),
            "confidentiality_years": self.confidentiality_years,
        }


def render_template(body_markdown: str, variables: ContractVariables) -> str:
    """{{変数}} をvariablesの値で置換"""
    rendered = body_markdown
    for k, v in variables.to_dict().items():
        rendered = rendered.replace(f"{{{{{k}}}}}", v or "")
    return rendered


# ==========================================================================
# PDF描画
# ==========================================================================
PAGE_W, PAGE_H = A4
MARGIN_X = 20 * mm
MARGIN_TOP = 22 * mm
MARGIN_BOTTOM = 22 * mm


def _draw_text_block(c: canvas.Canvas, text: str, x: float, y: float,
                      max_w: float, font: str, size: int, leading: float = 1.6) -> float:
    """複数行テキスト描画。改ページが必要な場合は新ページ作成。残Y座標を返す。"""
    lines = _wrap(text, c, font, size, max_w)
    for ln in lines:
        if y < MARGIN_BOTTOM + size * 0.5:
            c.showPage()
            _draw_page_header(c)
            y = PAGE_H - MARGIN_TOP
        c.setFont(font, size)
        c.drawString(x, y, ln)
        y -= size * leading
    return y


def _wrap(text: str, c: canvas.Canvas, font: str, size: int, max_w: float) -> list[str]:
    """日本語含む文字単位折り返し"""
    out = []
    for line in text.split("\n"):
        if line == "":
            out.append("")
            continue
        cur = ""
        for ch in line:
            test = cur + ch
            if c.stringWidth(test, font, size) > max_w and cur:
                out.append(cur)
                cur = ch
            else:
                cur = test
        if cur:
            out.append(cur)
    return out


def _draw_page_header(c: canvas.Canvas) -> None:
    """各ページ共通ヘッダー"""
    c.setFillColor(HexColor("#1F3A5F"))
    c.rect(0, PAGE_H - 10 * mm, PAGE_W, 10 * mm, fill=1, stroke=0)
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont(FONT_JP_REG, 8)
    c.drawString(MARGIN_X, PAGE_H - 7 * mm, "P1 Staff Manager｜契約書")
    c.setFillColor(black)


def generate_contract_pdf(
    rendered_body: str,
    contract_no: str,
    issuer_name: str,
    signature_image_bytes: Optional[bytes] = None,
    signed_at_iso: Optional[str] = None,
) -> bytes:
    """契約書PDFを生成

    Args:
        rendered_body: Markdownの変数埋め込み済み本文
        contract_no: 契約書番号
        issuer_name: 発行者名（ヘッダーに表示）
        signature_image_bytes: 署名画像（PNG bytes）。あれば末尾に署名欄描画
        signed_at_iso: 署名日時ISO文字列
    """
    _ensure_font()
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    # ========== 1ページ目ヘッダー ==========
    _draw_page_header(c)

    # 契約書番号・発行日
    c.setFont(FONT_JP_REG, 8)
    c.setFillColor(HexColor("#666666"))
    c.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 16 * mm,
                       f"契約書No. {contract_no}")
    c.setFillColor(black)

    # ========== 本文を描画 ==========
    y = PAGE_H - MARGIN_TOP - 5 * mm
    max_w = PAGE_W - MARGIN_X * 2

    for raw_line in rendered_body.split("\n"):
        line = raw_line.rstrip()
        if line.startswith("# "):   # h1
            y -= 4 * mm
            if y < MARGIN_BOTTOM + 15 * mm:
                c.showPage()
                _draw_page_header(c)
                y = PAGE_H - MARGIN_TOP
            c.setFont(FONT_JP_MIN, 18)
            c.setFillColor(HexColor("#1F3A5F"))
            c.drawString(MARGIN_X, y, line[2:].strip())
            c.setStrokeColor(HexColor("#C8381E"))
            c.setLineWidth(1)
            c.line(MARGIN_X, y - 3 * mm, MARGIN_X + 30 * mm, y - 3 * mm)
            c.setFillColor(black)
            y -= 10 * mm
        elif line.startswith("## "):  # h2
            y -= 2 * mm
            if y < MARGIN_BOTTOM + 12 * mm:
                c.showPage()
                _draw_page_header(c)
                y = PAGE_H - MARGIN_TOP
            c.setFont(FONT_JP_MIN, 12)
            c.setFillColor(HexColor("#1F3A5F"))
            c.drawString(MARGIN_X, y, line[3:].strip())
            c.setFillColor(black)
            y -= 7 * mm
        elif line.startswith("---"):  # 区切り
            y -= 2 * mm
            c.setStrokeColor(HexColor("#D0D0D0"))
            c.setLineWidth(0.4)
            c.line(MARGIN_X, y, PAGE_W - MARGIN_X, y)
            y -= 5 * mm
        elif line.startswith("- "):   # 箇条書き
            if y < MARGIN_BOTTOM + 8 * mm:
                c.showPage()
                _draw_page_header(c)
                y = PAGE_H - MARGIN_TOP
            c.setFont(FONT_JP_REG, 10)
            c.drawString(MARGIN_X + 2 * mm, y, "●")
            y = _draw_text_block(c, line[2:].strip(),
                                   MARGIN_X + 8 * mm, y,
                                   max_w - 8 * mm, FONT_JP_REG, 10, leading=1.5)
            y -= 1 * mm
        elif line.startswith("**") and line.endswith("**"):   # 強調（単独行）
            if y < MARGIN_BOTTOM + 8 * mm:
                c.showPage()
                _draw_page_header(c)
                y = PAGE_H - MARGIN_TOP
            c.setFont(FONT_JP_MIN, 10)
            c.setFillColor(HexColor("#1F3A5F"))
            c.drawString(MARGIN_X, y, line.strip("*").strip())
            c.setFillColor(black)
            y -= 6 * mm
        elif line.startswith("_") and line.endswith("_"):   # イタリック→斜体の代わりに小さな注記
            if y < MARGIN_BOTTOM + 8 * mm:
                c.showPage()
                _draw_page_header(c)
                y = PAGE_H - MARGIN_TOP
            c.setFont(FONT_JP_REG, 9)
            c.setFillColor(HexColor("#555555"))
            y = _draw_text_block(c, line.strip("_").strip(),
                                   MARGIN_X, y, max_w,
                                   FONT_JP_REG, 9, leading=1.5)
            c.setFillColor(black)
        elif line == "":
            y -= 3 * mm
        else:
            # 通常本文
            y = _draw_text_block(c, line, MARGIN_X, y, max_w,
                                   FONT_JP_REG, 10, leading=1.6)

    # ========== 署名欄 ==========
    if signature_image_bytes:
        # 余白が足りなければ新ページ
        if y < MARGIN_BOTTOM + 60 * mm:
            c.showPage()
            _draw_page_header(c)
            y = PAGE_H - MARGIN_TOP

        y -= 10 * mm
        c.setStrokeColor(HexColor("#1F3A5F"))
        c.setLineWidth(1)
        c.line(MARGIN_X, y, PAGE_W - MARGIN_X, y)
        y -= 8 * mm

        c.setFont(FONT_JP_MIN, 12)
        c.setFillColor(HexColor("#1F3A5F"))
        c.drawString(MARGIN_X, y, "電子署名")
        c.setFillColor(black)
        y -= 6 * mm

        c.setFont(FONT_JP_REG, 9)
        if signed_at_iso:
            c.drawString(MARGIN_X, y, f"署名日時: {signed_at_iso}")
            y -= 5 * mm

        # 署名画像を配置
        try:
            img = ImageReader(io.BytesIO(signature_image_bytes))
            iw, ih = img.getSize()
            target_w = 60 * mm
            target_h = target_w * ih / iw
            if target_h > 30 * mm:
                target_h = 30 * mm
                target_w = target_h * iw / ih
            c.drawImage(img, MARGIN_X, y - target_h,
                        target_w, target_h,
                        preserveAspectRatio=True, mask="auto")
            y -= target_h + 5 * mm
        except Exception:
            c.setFont(FONT_JP_REG, 9)
            c.setFillColor(HexColor("#999999"))
            c.drawString(MARGIN_X, y, "[署名画像の埋め込みに失敗しました]")
            y -= 5 * mm

        # タイムスタンプ（改ざん検知のための表示用）
        content_hash = hashlib.sha256(
            (rendered_body + (signed_at_iso or "")).encode("utf-8")
        ).hexdigest()[:16]
        c.setFont(FONT_JP_REG, 7)
        c.setFillColor(HexColor("#888888"))
        c.drawString(MARGIN_X, y, f"Content-Hash (SHA-256 first 16): {content_hash}")
        c.drawString(MARGIN_X, y - 4 * mm,
                     f"Contract No: {contract_no}")
        c.setFillColor(black)

    # フッター
    c.setFont(FONT_JP_REG, 8)
    c.setFillColor(HexColor("#888888"))
    c.drawCentredString(PAGE_W / 2, 10 * mm,
                         "本契約書は電子的に発行・署名されたものです。電子契約法に基づき、紙の契約書と同等の効力を有します。")
    c.setFillColor(black)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def compute_content_hash(rendered_body: str, signed_at_iso: str, contract_no: str) -> str:
    """契約内容＋署名日時＋契約番号のSHA-256ハッシュ"""
    content = f"{contract_no}|{signed_at_iso}|{rendered_body}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
