"""Streamlit 内部iframe のDOM構造調査 v4"""
import time
from playwright.sync_api import sync_playwright

BASE = "https://hidane2025-p1-staff-manager-app-fw8ggg.streamlit.app"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(f"{BASE}/", wait_until="networkidle", timeout=30000)
    time.sleep(8)

    # Streamlit アプリ iframe を取得
    app_frame = None
    for f in page.frames:
        if "+" in f.url and "streamlit" in f.url:
            app_frame = f
            break
    if not app_frame:
        print("❌ アプリframeが見つからない")
        browser.close()
        exit()

    print(f"✅ アプリframe: {app_frame.url}\n")

    # サイドバー関連の data-testid
    testids = app_frame.evaluate("""
        () => {
            const ids = new Set();
            document.querySelectorAll('[data-testid]').forEach(el => {
                const t = el.getAttribute('data-testid');
                if (t.toLowerCase().includes('sidebar') || t.toLowerCase().includes('nav')) {
                    ids.add(t);
                }
            });
            return Array.from(ids).sort();
        }
    """)
    print("--- サイドバー/ナビ関連の data-testid ---")
    for t in testids:
        print(f"  {t}")

    # サイドバー全体のHTML 先頭
    sidebar_html = app_frame.evaluate("""
        () => {
            const sb = document.querySelector('[data-testid*="idebar"]') ||
                        document.querySelector('[data-testid*="idebar"i]') ||
                        document.querySelector('aside') ||
                        document.querySelector('section > div > div');
            if (!sb) return null;
            return {
                testid: sb.getAttribute('data-testid'),
                tag: sb.tagName,
                html: sb.outerHTML.substring(0, 2000)
            };
        }
    """)
    print("\n--- サイドバー要素 ---")
    if sidebar_html:
        print(f"testid={sidebar_html['testid']}, tag={sidebar_html['tag']}")
        print(sidebar_html['html'])

    # ナビ系のリンク一覧
    print("\n--- ナビ系リンクの href ---")
    links = app_frame.evaluate("""
        () => {
            const nav = document.querySelector('[data-testid*="idebarNav"]');
            if (!nav) return {error: 'ナビ要素が見つからない'};
            return {
                testid: nav.getAttribute('data-testid'),
                links: Array.from(nav.querySelectorAll('a')).map(a => ({
                    text: a.innerText.trim(),
                    href: a.getAttribute('href'),
                }))
            };
        }
    """)
    print(links)

    # 全リンク一覧（フォールバック）
    print("\n--- 全 a タグ（href に文字列含むもの） ---")
    all_links = app_frame.evaluate("""
        () => {
            return Array.from(document.querySelectorAll('a'))
                .filter(a => a.getAttribute('href'))
                .slice(0, 30)
                .map(a => ({
                    text: a.innerText.trim(),
                    href: a.getAttribute('href'),
                    parent_testid: a.closest('[data-testid]')?.getAttribute('data-testid'),
                }));
        }
    """)
    for l in all_links:
        print(f"  text={l['text']!r} href={l['href']!r} parent={l['parent_testid']!r}")

    browser.close()
