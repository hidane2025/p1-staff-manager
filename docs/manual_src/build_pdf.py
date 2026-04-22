"""P1 Staff Manager 取扱説明書 HTML → PDF ビルダー

ユイ実装: Playwright(Chromium) の印刷エンジンで A4 PDFを出力
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
HTML_SRC = HERE / "manual.html"
PDF_OUT = HERE.parent / "MANUAL_v2_取扱説明書.pdf"


def main():
    if not HTML_SRC.exists():
        print(f"❌ HTMLソース無し: {HTML_SRC}")
        return 1

    print(f"📄 HTML: {HTML_SRC}")
    print(f"📑 出力: {PDF_OUT}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1200, "height": 1800},
            locale="ja-JP",
        )
        page = context.new_page()

        # file:// で HTMLを読み込む（CSS・画像の相対パス解決のため）
        file_url = f"file://{HTML_SRC}"
        print(f"🌐 loading: {file_url}")
        page.goto(file_url, wait_until="networkidle", timeout=30000)
        time.sleep(2)  # フォント読込とレイアウト安定

        # PDF生成
        pdf_bytes = page.pdf(
            format="A4",
            print_background=True,
            prefer_css_page_size=True,  # @page size を尊重
            margin={"top": "0mm", "right": "0mm", "bottom": "0mm", "left": "0mm"},
            display_header_footer=False,
        )
        PDF_OUT.write_bytes(pdf_bytes)
        size_kb = len(pdf_bytes) // 1024
        print(f"✅ 完了: {PDF_OUT.name} ({size_kb:,} KB)")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
