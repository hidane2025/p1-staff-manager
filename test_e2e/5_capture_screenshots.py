"""Streamlit全ページのスクリーンショットを自動取得

前提: Streamlitが http://localhost:8502 で起動中
"""

from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright, Page


BASE = "http://localhost:8502"
OUT = Path(__file__).resolve().parent / "screenshots"
OUT.mkdir(exist_ok=True)


def wait_ready(page: Page, timeout: int = 20000) -> None:
    """Streamlitの描画完了を待つ"""
    try:
        page.wait_for_selector("[data-testid='stAppViewContainer']", timeout=timeout)
        # Running中のindicatorが消えるまで待つ
        for _ in range(50):
            running = page.query_selector(".stStatusWidget-running")
            if not running:
                break
            time.sleep(0.2)
        # 実描画があるまで待つ（h1/h2/メトリクスなど）
        for _ in range(30):
            t = page.locator("h1, h2, [data-testid='stMetric']").count()
            if t > 0:
                break
            time.sleep(0.2)
        time.sleep(2.0)
    except Exception:
        time.sleep(3)


PAGES = [
    # slug, url_path, title, sidebar_label (for click), expect_text
    ("home", "/", "app.py ホーム", None, "P1 Staff Manager"),
    ("1_staff", None, "スタッフ管理", "staff", "スタッフ管理"),
    ("2_shift", None, "シフト取込", "shift", "シフト"),
    ("3_payment", None, "支払い計算", "payment", "支払"),
    ("4_envelope", None, "封筒リスト", "envelope", "封筒"),
    ("5_attendance", None, "出退勤", "attendance", "出退勤"),
    ("6_report", None, "精算レポート", "report", "精算"),
    ("7_yearly", None, "年間累計", "yearly", "累計"),
    ("8_transport", None, "交通費", "transport", "交通費"),
    ("9_receipt_download_no_token", None, "領収書DL", "receipt download", "領収書"),
    ("A_receipts", None, "領収書発行", "A receipts", "領収書発行"),
    ("B_issuer_settings", None, "発行者設定", "B issuer settings", "発行者設定"),
]


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        )
        page = ctx.new_page()

        # まずホームにアクセス（以降sidebarクリックで遷移）
        page.goto(BASE, wait_until="domcontentloaded", timeout=30000)
        wait_ready(page)

        saved = 0
        errors = []
        for slug, path, title, sidebar_label, expect_text in PAGES:
            out_png = OUT / f"page_{slug}.png"
            print(f"  📸 {title}")
            try:
                if path is not None:
                    # home
                    page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=30000)
                else:
                    # sidebarリンクをクリック
                    # まずホームに戻る
                    page.goto(BASE, wait_until="domcontentloaded", timeout=30000)
                    wait_ready(page)
                    # sidebarのリンク（aタグ with page name）をクリック
                    link = page.get_by_role("link", name=sidebar_label, exact=False).first
                    link.click(timeout=10000)
                try:
                    page.wait_for_function(
                        f"document.body.innerText.includes('{expect_text}')",
                        timeout=20000,
                    )
                except Exception:
                    pass
                wait_ready(page)
                page.screenshot(path=str(out_png), full_page=True)
                print(f"     ✅ {out_png.name} ({out_png.stat().st_size:,} bytes)")
                saved += 1
            except Exception as e:
                print(f"     ⚠️ {e}")
                errors.append((slug, str(e)))
                try:
                    page.screenshot(path=str(out_png), full_page=False)
                except Exception:
                    pass

        browser.close()
        print(f"\n合計: {saved}/{len(PAGES)} 枚取得")
        if errors:
            print("エラー:")
            for s, e in errors:
                print(f"  {s}: {e[:100]}")


if __name__ == "__main__":
    main()
