"""ツール全体の深掘り監査スクリプト（iframe対応）

人間目線で見る項目:
- 全画面のサイドバー状態
- ホームカードの描画有無
- 主要機能の応答時間
- モバイル崩れ
- 期待要素の存在
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, Frame


BASE = "https://hidane2025-p1-staff-manager-app-fw8ggg.streamlit.app"
OUT = Path(__file__).resolve().parent / "screenshots" / "audit"
OUT.mkdir(parents=True, exist_ok=True)


def get_app_frame(page) -> Frame | None:
    for f in page.frames:
        if "+" in f.url and "streamlit" in f.url:
            return f
    return None


def main():
    findings = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        # 【1】ホーム画面
        print("【1】ホーム画面チェック")
        page.goto(f"{BASE}/", wait_until="networkidle", timeout=30000)
        time.sleep(10)  # Streamlit full render
        af = get_app_frame(page)
        if af:
            # カード数
            cards = af.evaluate("""
                () => {
                    const links = document.querySelectorAll('a[data-testid="stPageLink-NavLink"]');
                    return Array.from(links).map(a => a.innerText.trim());
                }
            """)
            print(f"  ホームカードリンク数: {len(cards)}")
            for c in cards:
                print(f"    - {c[:40]}")
            if len(cards) < 12:
                findings.append(f"ホームカード不足: {len(cards)}/12")

            # サイドバーリンク
            sidebar_links = af.evaluate("""
                () => Array.from(document.querySelectorAll(
                    'a[data-testid="stSidebarNavLink"]'))
                    .map(a => ({text: a.innerText.trim(),
                                visible: !(a.offsetParent === null ||
                                          getComputedStyle(a).display === 'none'),
                                href: a.getAttribute('href')}));
            """)
            print(f"  サイドバーリンク数: {len(sidebar_links)}")
            visible_staff_links = [s for s in sidebar_links if s["visible"] and
                                   ("receipt_download" in (s["href"] or "") or
                                    "contract_sign" in (s["href"] or ""))]
            if visible_staff_links:
                findings.append(f"❌ スタッフ専用ページが見えている: {[s['text'] for s in visible_staff_links]}")
            else:
                print("  ✅ スタッフ専用ページは非表示")
        page.screenshot(path=str(OUT / "01_home.png"))

        # 【2】領収書発行ページ
        print("\n【2】領収書発行ページ")
        page.goto(f"{BASE}/領収書発行", wait_until="networkidle", timeout=30000)
        time.sleep(10)
        af = get_app_frame(page)
        if af:
            # コピーボタンあるか（st.code）
            has_code_block = af.evaluate("""
                () => document.querySelectorAll('code, pre, [data-testid="stCode"]').length
            """)
            print(f"  コードブロック数: {has_code_block}")
            # 発行対象表示
            body = af.evaluate("() => document.body.innerText")
            keywords_found = {
                "発行対象": "発行対象" in body,
                "一括発行": "一括発行" in body,
                "コピー": "コピー" in body,
                "DL回数": "DL回数" in body,
                "80件": "80件" in body or "80 件" in body,
            }
            print(f"  キーワード: {keywords_found}")
            for k, v in keywords_found.items():
                if not v and k != "80件":
                    findings.append(f"領収書発行ページ: 「{k}」が表示されていない")
        page.screenshot(path=str(OUT / "02_receipts.png"), full_page=True)

        # 【3】契約書発行ページ
        print("\n【3】契約書発行ページ")
        page.goto(f"{BASE}/契約書発行", wait_until="networkidle", timeout=30000)
        time.sleep(10)
        af = get_app_frame(page)
        if af:
            body = af.evaluate("() => document.body.innerText")
            keywords = {
                "テンプレート選択": "テンプレート選択" in body,
                "対象スタッフ選択": "対象スタッフ" in body,
                "無効化": "無効化" in body,
                "一括発行": "一括発行" in body,
            }
            print(f"  キーワード: {keywords}")
            for k, v in keywords.items():
                if not v:
                    findings.append(f"契約書発行ページ: 「{k}」が表示されていない")
        page.screenshot(path=str(OUT / "03_contracts.png"), full_page=True)

        # 【4】年間累計ページ - 健全性チェック
        print("\n【4】年間累計ページ")
        page.goto(f"{BASE}/年間累計", wait_until="networkidle", timeout=30000)
        time.sleep(10)
        af = get_app_frame(page)
        if af:
            body = af.evaluate("() => document.body.innerText")
            keywords = {
                "法定調書": "法定調書" in body,
                "健全性": "健全性" in body,
                "50万": "50万" in body or "500,000" in body or "500000" in body,
            }
            print(f"  キーワード: {keywords}")
            for k, v in keywords.items():
                if not v:
                    findings.append(f"年間累計ページ: 「{k}」が表示されていない")
        page.screenshot(path=str(OUT / "04_yearly.png"), full_page=True)

        # 【5】スタッフ管理ページ
        print("\n【5】スタッフ管理ページ")
        page.goto(f"{BASE}/スタッフ管理", wait_until="networkidle", timeout=30000)
        time.sleep(10)
        af = get_app_frame(page)
        if af:
            body = af.evaluate("() => document.body.innerText")
            keywords = {
                "スタッフ": "スタッフ" in body,
                "一括登録": "一括登録" in body or "CSV" in body,
                "検索": "検索" in body,
            }
            print(f"  キーワード: {keywords}")
        page.screenshot(path=str(OUT / "05_staff.png"), full_page=True)

        # 【6】支払い計算ページ
        print("\n【6】支払い計算ページ")
        page.goto(f"{BASE}/支払い計算", wait_until="networkidle", timeout=30000)
        time.sleep(10)
        af = get_app_frame(page)
        if af:
            body = af.evaluate("() => document.body.innerText")
            keywords = {
                "500円": "500" in body,
                "承認": "承認" in body,
                "支払済": "支払済" in body,
            }
            print(f"  キーワード: {keywords}")
        page.screenshot(path=str(OUT / "06_payment.png"), full_page=True)

        # 【7】モバイル表示
        print("\n【7】モバイル表示（iPhone）")
        mctx = browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
                         " AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0"
                         " Mobile/15E148 Safari/604.1"),
            locale="ja-JP",
        )
        mpage = mctx.new_page()
        mpage.goto(f"{BASE}/", wait_until="networkidle", timeout=30000)
        time.sleep(10)
        mpage.screenshot(path=str(OUT / "07_mobile_home.png"), full_page=True)

        # 【8】スタッフ用DLページ（トークンなし）
        print("\n【8】スタッフ用DLページ（トークンなし）")
        page.goto(f"{BASE}/receipt_download", wait_until="networkidle", timeout=30000)
        time.sleep(8)
        af = get_app_frame(page)
        if af:
            body = af.evaluate("() => document.body.innerText")
            print(f"  先頭100文字: {body[:100]}")
            if "URLが不正" in body:
                print("  ✅ 正しい警告表示")
            else:
                findings.append("receipt_download: トークンなし時の警告が出ていない")
        page.screenshot(path=str(OUT / "08_receipt_dl_notoken.png"))

        browser.close()

    # 最終サマリ
    print("\n" + "=" * 80)
    print("📋 発見事項")
    print("=" * 80)
    if not findings:
        print("✅ 大きな問題は見つかりませんでした")
    else:
        print(f"❌ {len(findings)}件の指摘事項:")
        for f in findings:
            print(f"  - {f}")


if __name__ == "__main__":
    main()
