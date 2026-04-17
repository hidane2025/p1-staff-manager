"""領収書デジタル発行機能 PDFマニュアル生成

スクリーンショット埋め込み・目次・カラーテーマの整ったPDFを出力。
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


# --- カラーパレット（P1事業ブランド想定：赤橙をアクセント、ベースはダーク系ではなく読みやすい白紺）---
COLOR_PRIMARY = HexColor("#C8381E")     # アクセント赤
COLOR_SECONDARY = HexColor("#1F3A5F")   # ネイビー
COLOR_INK = HexColor("#1A1A1A")
COLOR_MUTED = HexColor("#666666")
COLOR_BG_LIGHT = HexColor("#F5F2EE")
COLOR_BG_BOX = HexColor("#FFF8F0")
COLOR_GREEN = HexColor("#2E7D4F")

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "test_e2e" / "screenshots"
OUT = ROOT / "docs" / "MANUAL_領収書デジタル発行.pdf"

FONT_JP_REG = "HeiseiKakuGo-W5"
FONT_JP_BOLD = "HeiseiMin-W3"

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
MARGIN_TOP = 22 * mm
MARGIN_BOTTOM = 18 * mm


def ensure_fonts() -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))


class DocBuilder:
    """段組みPDFビルダー（縦Y座標を自動追跡・ページ跨ぎ処理つき）"""

    def __init__(self, out_path: Path):
        self.c = canvas.Canvas(str(out_path), pagesize=A4)
        self.page_no = 1
        self.y = PAGE_H - MARGIN_TOP
        self.section_title = ""
        self._draw_header_footer()

    # ---------- 内部ユーティリティ ----------
    def _draw_header_footer(self) -> None:
        # ヘッダーバー
        self.c.setFillColor(COLOR_SECONDARY)
        self.c.rect(0, PAGE_H - 12 * mm, PAGE_W, 12 * mm, fill=1, stroke=0)
        self.c.setFillColor(white)
        self.c.setFont(FONT_JP_REG, 9)
        self.c.drawString(MARGIN_X, PAGE_H - 8 * mm,
                          "P1 Staff Manager ｜ 領収書デジタル発行マニュアル")
        self.c.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 8 * mm,
                               "株式会社ヒダネ × Pacific")

        # フッター
        self.c.setFillColor(COLOR_MUTED)
        self.c.setFont(FONT_JP_REG, 8)
        self.c.drawCentredString(PAGE_W / 2, 10 * mm, f"- {self.page_no} -")
        self.c.drawRightString(PAGE_W - MARGIN_X, 10 * mm,
                               datetime.now().strftime("%Y-%m-%d 版"))

    def need(self, h_mm: float) -> None:
        """残り縦幅がh_mm未満なら改ページ"""
        if self.y - h_mm * mm < MARGIN_BOTTOM + 8 * mm:
            self.new_page()

    def new_page(self) -> None:
        self.c.showPage()
        self.page_no += 1
        self.y = PAGE_H - MARGIN_TOP
        self._draw_header_footer()

    # ---------- 要素描画 ----------
    def h1(self, text: str) -> None:
        self.need(28)
        self.c.setFillColor(COLOR_PRIMARY)
        self.c.rect(MARGIN_X, self.y - 2 * mm, 4 * mm, 10 * mm, fill=1, stroke=0)
        self.c.setFillColor(COLOR_SECONDARY)
        self.c.setFont(FONT_JP_BOLD, 20)
        self.c.drawString(MARGIN_X + 7 * mm, self.y + 2 * mm, text)
        self.y -= 14 * mm
        self.section_title = text

    def h2(self, text: str) -> None:
        self.need(18)
        self.c.setFillColor(COLOR_SECONDARY)
        self.c.setFont(FONT_JP_BOLD, 14)
        self.c.drawString(MARGIN_X, self.y, text)
        self.c.setStrokeColor(COLOR_PRIMARY)
        self.c.setLineWidth(0.8)
        self.c.line(MARGIN_X, self.y - 2 * mm,
                    MARGIN_X + 18 * mm, self.y - 2 * mm)
        self.y -= 10 * mm

    def h3(self, text: str) -> None:
        self.need(14)
        self.c.setFillColor(COLOR_SECONDARY)
        self.c.setFont(FONT_JP_BOLD, 11)
        self.c.drawString(MARGIN_X, self.y, text)
        self.y -= 7 * mm

    def para(self, text: str, size: int = 10, color=None) -> None:
        """自動改行・自動改ページ対応の段落"""
        color = color or COLOR_INK
        self.c.setFillColor(color)
        self.c.setFont(FONT_JP_REG, size)
        # 日本語は文字単位で折り返し（ReportLabはwrap難しいので自前）
        max_w = PAGE_W - MARGIN_X * 2
        lines = self._wrap_japanese(text, max_w, size)
        for ln in lines:
            self.need(size * 0.5 + 2)
            self.c.drawString(MARGIN_X, self.y, ln)
            self.y -= size * 1.45

    def _wrap_japanese(self, text: str, max_w: float, size: int) -> list[str]:
        out = []
        cur = ""
        for ch in text:
            if ch == "\n":
                out.append(cur)
                cur = ""
                continue
            test = cur + ch
            if self.c.stringWidth(test, FONT_JP_REG, size) > max_w:
                out.append(cur)
                cur = ch
            else:
                cur = test
        if cur:
            out.append(cur)
        return out

    def bullet(self, items: list[str], size: int = 10) -> None:
        for it in items:
            self.need(size * 0.5 + 4)
            self.c.setFillColor(COLOR_PRIMARY)
            self.c.setFont(FONT_JP_BOLD, size)
            self.c.drawString(MARGIN_X + 2 * mm, self.y, "●")
            self.c.setFillColor(COLOR_INK)
            self.c.setFont(FONT_JP_REG, size)
            # 自動改行
            max_w = PAGE_W - MARGIN_X * 2 - 8 * mm
            lines = self._wrap_japanese(it, max_w, size)
            for i, ln in enumerate(lines):
                self.need(size * 0.5 + 2)
                self.c.drawString(MARGIN_X + 8 * mm, self.y, ln)
                self.y -= size * 1.5

    def callout(self, title: str, body: str, color=COLOR_PRIMARY) -> None:
        """目立つ注意ボックス"""
        lines = self._wrap_japanese(body, PAGE_W - MARGIN_X * 2 - 12 * mm, 9)
        box_h = (len(lines) * 9 * 1.5 + 15) / 72 * 25.4   # mm変換
        box_h = max(box_h, 15)
        self.need(box_h + 5)
        self.c.setFillColor(COLOR_BG_BOX)
        self.c.rect(MARGIN_X, self.y - box_h * mm,
                    PAGE_W - MARGIN_X * 2, box_h * mm, fill=1, stroke=0)
        self.c.setFillColor(color)
        self.c.rect(MARGIN_X, self.y - box_h * mm,
                    2 * mm, box_h * mm, fill=1, stroke=0)
        self.c.setFillColor(color)
        self.c.setFont(FONT_JP_BOLD, 10)
        self.c.drawString(MARGIN_X + 5 * mm, self.y - 5 * mm, title)
        self.c.setFillColor(COLOR_INK)
        self.c.setFont(FONT_JP_REG, 9)
        yy = self.y - 10 * mm
        for ln in lines:
            self.c.drawString(MARGIN_X + 5 * mm, yy, ln)
            yy -= 9 * 1.5
        self.y -= box_h * mm + 3 * mm

    def table(self, headers: list[str], rows: list[list[str]],
              col_widths: list[float] | None = None) -> None:
        """シンプル2列/3列テーブル"""
        n = len(headers)
        total_w = PAGE_W - MARGIN_X * 2
        if col_widths is None:
            col_widths = [total_w / n] * n
        else:
            col_widths = [w * total_w for w in col_widths]

        row_h = 8 * mm
        # ヘッダー
        self.need(12)
        self.c.setFillColor(COLOR_SECONDARY)
        self.c.rect(MARGIN_X, self.y - row_h, total_w, row_h, fill=1, stroke=0)
        self.c.setFillColor(white)
        self.c.setFont(FONT_JP_BOLD, 10)
        x = MARGIN_X + 3 * mm
        for i, h in enumerate(headers):
            self.c.drawString(x, self.y - row_h + 2.5 * mm, h)
            x += col_widths[i]
        self.y -= row_h

        # 行
        for idx, row in enumerate(rows):
            self.need(10)
            if idx % 2 == 0:
                self.c.setFillColor(COLOR_BG_LIGHT)
                self.c.rect(MARGIN_X, self.y - row_h, total_w, row_h, fill=1, stroke=0)
            self.c.setFillColor(COLOR_INK)
            self.c.setFont(FONT_JP_REG, 9)
            x = MARGIN_X + 3 * mm
            for i, cell in enumerate(row):
                # セル内テキストは切り詰め（超長文は...）
                col_w = col_widths[i] - 6 * mm
                txt = cell
                while self.c.stringWidth(txt, FONT_JP_REG, 9) > col_w and len(txt) > 3:
                    txt = txt[:-2] + "…"
                self.c.drawString(x, self.y - row_h + 2.5 * mm, txt)
                x += col_widths[i]
            self.y -= row_h

        self.y -= 3 * mm

    def image(self, img_path: Path, max_w_mm: float = 170,
              max_h_mm: float = 110, caption: str = "") -> None:
        if not img_path.exists():
            self.callout("⚠ 画像が見つかりません", str(img_path), color=COLOR_PRIMARY)
            return
        img = ImageReader(str(img_path))
        iw, ih = img.getSize()
        # 縦横比を保って縮小
        sw = max_w_mm * mm
        sh = sw * ih / iw
        if sh > max_h_mm * mm:
            sh = max_h_mm * mm
            sw = sh * iw / ih
        self.need(sh / mm + 10)
        # 枠線
        x = (PAGE_W - sw) / 2
        self.c.setStrokeColor(HexColor("#D0D0D0"))
        self.c.setLineWidth(0.3)
        self.c.rect(x - 1, self.y - sh - 1, sw + 2, sh + 2, fill=0, stroke=1)
        self.c.drawImage(img, x, self.y - sh, sw, sh,
                         preserveAspectRatio=True, mask='auto')
        self.y -= sh + 2 * mm
        if caption:
            self.c.setFont(FONT_JP_REG, 8)
            self.c.setFillColor(COLOR_MUTED)
            self.c.drawCentredString(PAGE_W / 2, self.y, caption)
            self.y -= 6 * mm
        else:
            self.y -= 3 * mm

    def divider(self) -> None:
        self.need(8)
        self.c.setStrokeColor(HexColor("#E0E0E0"))
        self.c.setLineWidth(0.5)
        self.c.line(MARGIN_X, self.y, PAGE_W - MARGIN_X, self.y)
        self.y -= 5 * mm

    def spacer(self, h_mm: float) -> None:
        self.y -= h_mm * mm

    def save(self) -> None:
        self.c.save()


# ========================================================================
# 表紙ページ
# ========================================================================
def cover_page(b: DocBuilder) -> None:
    c = b.c
    # 上半分アクセントカラー
    c.setFillColor(COLOR_SECONDARY)
    c.rect(0, PAGE_H * 0.55, PAGE_W, PAGE_H * 0.45, fill=1, stroke=0)

    c.setFillColor(COLOR_PRIMARY)
    c.rect(0, PAGE_H * 0.52, PAGE_W, 3 * mm, fill=1, stroke=0)

    # タイトル
    c.setFillColor(white)
    c.setFont(FONT_JP_BOLD, 36)
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.78, "領収書デジタル発行")
    c.setFont(FONT_JP_REG, 18)
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.71, "操作マニュアル")

    c.setFont(FONT_JP_REG, 12)
    c.setFillColor(HexColor("#F0C0B0"))
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.63,
                         "P1 Staff Manager  ｜  v3.4  ｜  2026-04-17")

    # 下半分
    c.setFillColor(COLOR_INK)
    c.setFont(FONT_JP_REG, 11)
    y = PAGE_H * 0.42
    subtitle_lines = [
        "本マニュアルは、P1 Staff Manager に新しく追加された",
        "領収書デジタル発行機能について解説した資料です。",
        "Pacificがスタッフに代行発行する領収書を",
        "PDF生成 → クラウド保存 → 専用URL配布 まで自動化します。",
    ]
    for ln in subtitle_lines:
        c.drawCentredString(PAGE_W / 2, y, ln)
        y -= 7 * mm

    # 機能ハイライトカード
    card_y = PAGE_H * 0.20
    card_w = 50 * mm
    card_h = 28 * mm
    cards = [
        ("電子発行", "印紙不要", COLOR_GREEN),
        ("インボイス", "後日追加OK", COLOR_SECONDARY),
        ("トークン認証", "他人に見えない", COLOR_PRIMARY),
    ]
    total_w = len(cards) * card_w + (len(cards) - 1) * 6 * mm
    start_x = (PAGE_W - total_w) / 2
    for i, (title, sub, color) in enumerate(cards):
        x = start_x + i * (card_w + 6 * mm)
        c.setFillColor(COLOR_BG_LIGHT)
        c.rect(x, card_y, card_w, card_h, fill=1, stroke=0)
        c.setFillColor(color)
        c.rect(x, card_y + card_h - 3 * mm, card_w, 3 * mm, fill=1, stroke=0)
        c.setFillColor(color)
        c.setFont(FONT_JP_BOLD, 13)
        c.drawCentredString(x + card_w / 2, card_y + card_h - 12 * mm, title)
        c.setFillColor(COLOR_INK)
        c.setFont(FONT_JP_REG, 10)
        c.drawCentredString(x + card_w / 2, card_y + card_h - 20 * mm, sub)

    # 発行元
    c.setFillColor(COLOR_MUTED)
    c.setFont(FONT_JP_REG, 9)
    c.drawCentredString(PAGE_W / 2, 20 * mm,
                         "制作: 株式会社ヒダネ AI部  ／  運用: 株式会社パシフィック")

    c.showPage()
    b.page_no += 1
    b.y = PAGE_H - MARGIN_TOP
    b._draw_header_footer()


# ========================================================================
# 目次
# ========================================================================
def toc_page(b: DocBuilder) -> None:
    b.h1("目次")
    toc_items = [
        ("1. 機能概要", "p.3"),
        ("2. 初期セットアップ（初回のみ）", "p.4"),
        ("3. 運用フロー（毎大会の流れ）", "p.6"),
        ("4. 画面ガイド", "p.7"),
        ("   4-1. ホーム画面", "p.7"),
        ("   4-2. 発行者設定", "p.8"),
        ("   4-3. 領収書発行", "p.9"),
        ("   4-4. スタッフ向けDL画面", "p.10"),
        ("5. 領収書PDFサンプル", "p.11"),
        ("6. セキュリティ仕様", "p.13"),
        ("7. FAQ（よくある質問）", "p.14"),
        ("8. 運用メモ・次フェーズ", "p.15"),
    ]
    b.c.setFont(FONT_JP_REG, 11)
    for title, page in toc_items:
        b.need(8)
        b.c.setFillColor(COLOR_INK)
        b.c.drawString(MARGIN_X + 5 * mm, b.y, title)
        # ドットリーダー
        text_w = b.c.stringWidth(title, FONT_JP_REG, 11)
        dot_start = MARGIN_X + 5 * mm + text_w + 3 * mm
        dot_end = PAGE_W - MARGIN_X - 15 * mm
        b.c.setFillColor(COLOR_MUTED)
        for xx in range(int(dot_start), int(dot_end), 4):
            b.c.circle(xx, b.y + 1, 0.3, fill=1, stroke=0)
        b.c.setFillColor(COLOR_SECONDARY)
        b.c.drawRightString(PAGE_W - MARGIN_X, b.y, page)
        b.y -= 7 * mm
    b.new_page()


# ========================================================================
# 本編
# ========================================================================
def section_overview(b: DocBuilder) -> None:
    b.h1("1. 機能概要")
    b.para("Pacificがスタッフに代行発行する領収書を、紙から電子データに完全移行する機能です。"
            "PDF生成・クラウド保存・専用URL配布までをツール内で自動処理します。")
    b.spacer(3)

    b.h2("役割の整理")
    b.table(
        ["書類", "発行者 → 受領者", "Pacificの立場"],
        [
            ["領収書", "スタッフ → Pacific", "受領側（代行作成）"],
            ["契約書", "Pacific → スタッフ", "発行側（Phase 2予定）"],
        ],
        col_widths=[0.22, 0.42, 0.36],
    )
    b.spacer(3)

    b.h2("主な特徴")
    b.bullet([
        "電子発行につき収入印紙不要（PDFに注記を自動付与）",
        "インボイス番号は空欄運用可。Pacificが登録したら後日追加できる設計",
        "トークン認証で、他人の領収書は見られない",
        "有効期限付きURL（デフォルト7日、変更可）",
        "ダウンロード回数を記録（受領確認の代替に）",
        "承認済み・支払済みの全員分を一括発行",
    ])
    b.spacer(2)

    b.callout("電子化のメリット",
              "5万円以上の領収書でも印紙代は不要です。原本保管も不要で、検索性が大幅に向上。"
              "電子帳簿保存法（2024年1月完全義務化）にも対応しています。",
              color=COLOR_GREEN)


def section_setup(b: DocBuilder) -> None:
    b.h1("2. 初期セットアップ（初回のみ）")
    b.para("以下3ステップを初回のみ実施してください。"
            "2026-04-17時点で、中野さん＆ヒダネAI部の作業により①②は完了済みです。")

    b.h2("① Supabase SQLマイグレーション")
    b.para("Supabaseダッシュボード > SQL Editor を開き、"
            "以下のファイル内容を貼り付けて Run を押します。")
    b.bullet(["ファイル: docs/db_migrations/20260417_add_receipt_columns.sql"])
    b.callout("実行結果",
              "Success. No rows returned が表示されれば成功です。"
              "p1_payments に領収書関連7列、p1_events に発行者情報6列が追加されます。",
              color=COLOR_GREEN)

    b.h2("② Storageバケット作成")
    b.table(
        ["項目", "値"],
        [
            ["Name", "receipts"],
            ["Public bucket", "OFF（重要：Signed URL経由のみアクセス可）"],
            ["File size limit", "5 MB"],
            ["Allowed MIME types", "application/pdf"],
        ],
        col_widths=[0.35, 0.65],
    )

    b.h2("③ Storage RLSポリシー（SQL実行）")
    b.para("バケットへの読み書き権限を設定します。以下SQLをSQL Editorで実行してください。")
    b.bullet([
        'allow_receipts_insert  (anon/authenticatedがPDFをアップロード可能)',
        'allow_receipts_select  (Signed URL経由でのみPDF取得可能)',
        'allow_receipts_update  (再生成時の上書き可能)',
        'allow_receipts_delete  (上書き時の旧ファイル削除可能)',
    ])

    b.h2("④ 発行者情報入力")
    b.para("Streamlit画面サイドバー > 「B issuer settings（発行者設定）」 で "
            "Pacificの情報を登録します。インボイス番号は空欄でOK。後日追加可能です。")


def section_flow(b: DocBuilder) -> None:
    b.h1("3. 運用フロー（毎大会の流れ）")
    b.para("大会終了後、下記5ステップで領収書の発行〜配布が完了します。")
    b.spacer(3)

    steps = [
        ("1", "大会終了",  "既存機能で支払計算・承認まで完了させる"),
        ("2", "一括発行",   "「A receipts（領収書発行）」で対象者全員を選択 → 一括発行"),
        ("3", "リンク取得", "画面下部のDLリンク一覧をCSVでダウンロード"),
        ("4", "配布",      "LINE・メールで各スタッフに個別URLを送付"),
        ("5", "受領",      "スタッフがURLを開いてPDFダウンロード → DL回数が記録される"),
    ]
    for num, title, desc in steps:
        b.need(20)
        # 番号バッジ
        b.c.setFillColor(COLOR_PRIMARY)
        b.c.circle(MARGIN_X + 5 * mm, b.y - 2 * mm, 4.5 * mm, fill=1, stroke=0)
        b.c.setFillColor(white)
        b.c.setFont(FONT_JP_BOLD, 14)
        b.c.drawCentredString(MARGIN_X + 5 * mm, b.y - 4 * mm, num)
        # タイトル
        b.c.setFillColor(COLOR_SECONDARY)
        b.c.setFont(FONT_JP_BOLD, 13)
        b.c.drawString(MARGIN_X + 15 * mm, b.y - 1 * mm, title)
        # 説明
        b.c.setFillColor(COLOR_INK)
        b.c.setFont(FONT_JP_REG, 10)
        b.c.drawString(MARGIN_X + 15 * mm, b.y - 7 * mm, desc)
        b.y -= 16 * mm

    b.spacer(3)
    b.callout("所要時間の目安",
              "80名分の一括発行で約1〜2分（ネットワーク状況による）。"
              "CSV配布リンク生成は瞬時。スタッフへの配布は運用次第ですが、"
              "LINE公式連携（Phase 2予定）でさらに短縮可能です。",
              color=COLOR_SECONDARY)


def section_screens(b: DocBuilder) -> None:
    b.h1("4. 画面ガイド")

    b.h2("4-1. ホーム画面")
    b.para("サイドバーに新メニュー3つ（receipt download / A receipts / B issuer settings）が追加されています。")
    b.image(SHOTS / "page_home.png", caption="P1 Staff Manager ホーム画面")

    b.h2("4-2. 発行者設定（B issuer settings）")
    b.para("領収書PDFに印字する Pacific 情報を設定します。"
            "インボイス番号欄は空欄のままでも運用可能です。"
            "後日Pacificが適格請求書発行事業者として登録されたら、"
            "この画面で番号を入力するだけで全ての新規領収書に自動反映されます。")
    b.image(SHOTS / "page_B_issuer_settings.png",
            caption="発行者設定画面（インボイス番号・電子印影・但し書きも設定可能）")

    b.h3("入力項目")
    b.table(
        ["項目", "必須", "説明"],
        [
            ["発行者名", "必須", "例：株式会社パシフィック"],
            ["発行者住所", "任意", "本社住所"],
            ["電話番号", "任意", "問い合わせ先"],
            ["但し書き", "必須", "例：ポーカー大会運営業務委託費として"],
            ["インボイス番号", "任意", "T+13桁。空欄なら非表示"],
            ["電子印影URL", "任意", "PNG推奨。透過背景150x150px程度"],
        ],
        col_widths=[0.25, 0.13, 0.62],
    )

    b.h2("4-3. 領収書発行（A receipts）")
    b.para("支払承認済みのスタッフを一覧から選択して、一括でPDF発行します。"
            "発行済みの領収書はページ下部にDLリンク一覧として表示され、CSVエクスポート可能です。")
    b.image(SHOTS / "page_A_receipts.png",
            caption="領収書発行画面（対象絞り込み・一括選択・強制再生成に対応）")

    b.h3("操作手順")
    b.bullet([
        "① イベントを選択",
        "② 発行対象を絞り込み（推奨：承認/支払済みのみ）",
        "③ スタッフごとの「選択」にチェック（全選択も可能）",
        "④ 有効期限を確認（デフォルト7日、最長90日）",
        "⑤「選択分を一括発行」ボタンをクリック",
        "⑥ 発行完了後、下部の一覧から「DLリンク一覧をCSVでダウンロード」",
    ])

    b.h2("4-4. スタッフ向けDL画面（receipt download）")
    b.para("スタッフはPacificから受け取ったURL（例: .../receipt_download?token=xxxx）を開くだけ。"
            "トークンが有効なら自動的にPDFダウンロードボタンが表示されます。"
            "管理用サイドバーはスタッフには表示されません。")
    b.image(SHOTS / "page_9_receipt_download_no_token.png",
            caption="無効URL時の表示。正常時は金額と「PDFをダウンロード」ボタンが表示される")


def section_pdf_samples(b: DocBuilder) -> None:
    b.h1("5. 領収書PDFサンプル")
    b.para("実際に生成される領収書PDFの例を示します。"
            "インボイス未登録（現状）と登録後のビフォーアフター両方を確認できます。")

    b.h2("5-1. インボイス未登録時（現状 Pacific 想定）")
    b.image(SHOTS / "test_receipt_no_invoice.png",
            caption="Pacificがインボイス未登録の場合の領収書PDF（A5横）")

    b.spacer(2)
    b.bullet([
        "発行日・領収書No.は自動採番（R-日付-イベントID-スタッフID）",
        "宛名は本名を自動取得。住所・メールも小さく表示",
        "金額（税込）・但し書き・大会名を明記",
        "発行者情報は右下ブロックに配置",
        "インボイス番号欄は未登録のため非表示",
        "下端に「電子発行につき収入印紙不要」を自動注記",
    ])

    b.h2("5-2. インボイス登録後（後日追加シナリオ）")
    b.image(SHOTS / "test_receipt_with_invoice.png",
            caption="Pacificがインボイス登録した後の領収書PDF")

    b.spacer(2)
    b.callout("後付けの仕組み",
              "発行者設定画面でインボイス番号を入力保存するだけで、以降の領収書すべてに自動反映されます。"
              "既存の領収書を更新したい場合は、領収書発行画面で「強制再生成」にチェックを入れて一括再発行できます。",
              color=COLOR_GREEN)


def section_security(b: DocBuilder) -> None:
    b.h1("6. セキュリティ仕様")

    b.h2("トークン方式")
    b.bullet([
        "secrets.token_urlsafe(32) により256bitランダム値を生成（UUID4より強固）",
        "他人のURLを推測して領収書を見ることは事実上不可能",
        "有効期限切れは自動的に無効化される",
    ])

    b.h2("Storage非公開設定")
    b.bullet([
        "receiptsバケットは Public OFF",
        "直接URLアクセスしても403で拒否",
        "Signed URLまたは内部トークン経由のみDL可能",
    ])

    b.h2("監査ログ")
    b.bullet([
        "発行日時・DL日時・DL回数をすべてDBに記録",
        "audit_logテーブルに『issue_receipt』アクションが残る",
        "異常な大量DLや期限延長の追跡が可能",
    ])

    b.h2("自動テスト結果（2026-04-17実施）")
    b.table(
        ["テスト項目", "結果"],
        [
            ["トークン生成衝突チェック", "✅ PASS"],
            ["期限切れ判定", "✅ PASS"],
            ["PDF生成（インボイスなし）", "✅ 3,318 bytes"],
            ["PDF生成（インボイスあり）", "✅ 3,419 bytes"],
            ["実DB一括発行（10名）", "✅ 6.3秒"],
            ["Signed URL経由DL", "✅ PDF取得OK"],
            ["トークン経由DL＋回数記録", "✅ PASS"],
            ["無効トークン拒否", "✅ PASS"],
            ["強制再生成（新トークン発行）", "✅ PASS"],
            ["インボイス後付け反映", "✅ PASS"],
            ["既存E2E（80名大会）", "✅ 24/24 PASS"],
        ],
        col_widths=[0.7, 0.3],
    )


def section_faq(b: DocBuilder) -> None:
    b.h1("7. FAQ（よくある質問）")

    qas = [
        ("Q. インボイスを後から追加したい",
         "A. 「B issuer settings（発行者設定）」画面で登録番号を入力→保存。"
         "以降発行する領収書に自動反映されます。"
         "既存の領収書を更新したい場合は、領収書発行画面で「強制再生成」に"
         "チェックして一括再発行してください。"),
        ("Q. スタッフから「リンクが切れた」と連絡が来た",
         "A. 有効期限切れです。領収書発行画面で該当スタッフを再選択し、"
         "「強制再生成」にチェックを入れて再発行→新しいURLをスタッフに再送してください。"),
        ("Q. 印紙代はかかるの？",
         "A. 不要です。電子データで発行する領収書には収入印紙の貼付義務はありません。"
         "5万円以上でも同様で、PDFにもその旨を自動注記しています。"),
        ("Q. インボイスがないと発行できないスタッフがいる？",
         "A. 現状はインボイスなし運用でも問題なく発行できます。"
         "業務委託報酬の領収書は通常インボイス不要です。"
         "Pacific側でインボイス登録が必要なのは主に取引先から請求される場合です。"),
        ("Q. 同じ領収書を複数回DLできる？",
         "A. 有効期限内なら何度でもDL可能です。DL回数はカウントされ、"
         "管理画面で確認できます。"),
        ("Q. 領収書の内容を修正したい",
         "A. 「強制再生成」にチェックして発行し直すと、"
         "新しいPDF・新しいトークンで上書きされます。"),
        ("Q. スタッフに一斉送信したい",
         "A. 現状はCSVエクスポート＋手動LINE送信です。"
         "Phase 2でLINE公式アカウント連携による一括送信を実装予定です。"),
        ("Q. 過去に紙で発行した領収書も電子化したい",
         "A. 可能です。該当支払レコードを手動で選択して発行することで、"
         "遡及的に電子領収書を発行できます。"),
    ]
    for q, a in qas:
        b.need(18)
        b.c.setFillColor(COLOR_PRIMARY)
        b.c.setFont(FONT_JP_BOLD, 11)
        b.c.drawString(MARGIN_X, b.y, q)
        b.y -= 6 * mm
        b.c.setFillColor(COLOR_INK)
        b.c.setFont(FONT_JP_REG, 10)
        lines = b._wrap_japanese(a, PAGE_W - MARGIN_X * 2 - 5 * mm, 10)
        for ln in lines:
            b.need(6)
            b.c.drawString(MARGIN_X + 3 * mm, b.y, ln)
            b.y -= 5.5 * mm
        b.y -= 3 * mm


def section_memo(b: DocBuilder) -> None:
    b.h1("8. 運用メモ・次フェーズ")

    b.h2("運用上の注意点")
    b.bullet([
        "発行者情報はイベント単位で管理されます。大会ごとに発行者が変わる場合は切り替え可能",
        "電子印影はPNG推奨。背景透過で150x150px程度が最適",
        "Storageバケットの容量は Supabase無料枠で1GB。1領収書約3KBなので30万通分で1GB",
        "DLリンクのトークンは推測不可だが、LINE等での誤送信には注意（本人性の最終担保は宛先管理）",
    ])

    b.h2("Phase 2（契約書クラウド）予定機能")
    b.bullet([
        "業務委託契約書のPDFテンプレート管理",
        "スタッフ専用署名画面（電子署名パッド）",
        "署名完了ステータス追跡・未署名リマインド",
        "タイムスタンプ付与（改ざん防止）",
        "契約・領収書・請求書をスタッフマイページで一元閲覧",
    ])

    b.h2("エンジニア向けファイル構成")
    b.table(
        ["ファイル", "役割"],
        [
            ["docs/db_migrations/20260417_add_receipt_columns.sql", "DBスキーマ"],
            ["utils/receipt_v2.py", "PDF生成エンジン"],
            ["utils/receipt_token.py", "トークン生成・検証"],
            ["utils/receipt_storage.py", "Supabase Storage連携"],
            ["utils/receipt_db.py", "領収書DB CRUD"],
            ["utils/receipt_issuer.py", "一気通貫オーケストレーター"],
            ["pages/9_receipt_download.py", "スタッフ向けDL画面"],
            ["pages/A_receipts.py", "管理者向け一括発行画面"],
            ["pages/B_issuer_settings.py", "発行者設定画面"],
            ["test_e2e/4_receipt_unit_test.py", "ユニットテスト"],
            ["test_e2e/6_receipt_e2e_test.py", "実DB接続E2Eテスト"],
        ],
        col_widths=[0.5, 0.5],
    )

    b.spacer(5)
    b.callout("既存機能への影響", "本機能は全て新規ファイルとして追加されています。"
                                 "既存の db.py / receipt.py / pagesの8ページは一切変更していません。"
                                 "導入リスクは最小限です。",
              color=COLOR_GREEN)


# ========================================================================
# main
# ========================================================================
def main() -> None:
    ensure_fonts()
    b = DocBuilder(OUT)
    cover_page(b)
    toc_page(b)
    section_overview(b)
    b.new_page()
    section_setup(b)
    b.new_page()
    section_flow(b)
    b.new_page()
    section_screens(b)
    b.new_page()
    section_pdf_samples(b)
    b.new_page()
    section_security(b)
    b.new_page()
    section_faq(b)
    b.new_page()
    section_memo(b)
    b.save()
    print(f"✅ 出力: {OUT}")
    print(f"   サイズ: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
