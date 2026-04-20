"""全体ウォークスルー: 各ページをPlaywrightで開いて状態チェック＋スクショ取得

人間目線で気になる項目を自動検出:
- サイドバー構成
- エラー画面の有無
- 主要要素の存在
- レンダリング時間
- モバイル表示
"""

from __future__ import annotations

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "https://hidane2025-p1-staff-manager-app-fw8ggg.streamlit.app"
OUT = Path(__file__).resolve().parent / "screenshots" / "walkthrough"
OUT.mkdir(parents=True, exist_ok=True)


# 検査する項目
CHECKS = [
    # (slug, path, 期待されるタイトル, 期待する要素テキスト)
    ("home", "/", "P1 Staff Manager", ["スタッフ管理", "契約書発行"]),
    ("staff", "/スタッフ管理", "スタッフ管理", ["スタッフ"]),
    ("shift", "/シフト取込", "シフト", []),
    ("payment", "/支払い計算", "支払い計算", ["支払"]),
    ("envelope", "/封筒リスト", "封筒", ["紙幣"]),
    ("attendance", "/出退勤", "出退勤", []),
    ("report", "/精算レポート", "精算", []),
    ("yearly", "/年間累計", "年間累計", ["法定調書"]),
    ("transport", "/交通費", "交通費", []),
    ("receipts", "/領収書発行", "領収書発行", []),
    ("issuer", "/発行者設定", "発行者設定", []),
    ("tpl", "/契約書テンプレ", "契約書テンプレ", []),
    ("contracts", "/契約書発行", "契約書発行", []),
]

# スタッフ向けページ（管理者には見えないはず）
STAFF_CHECKS = [
    ("dl_notoken", "/receipt_download", "領収書ダウンロード", ["URLが不正"]),
    ("sign_notoken", "/contract_sign", "契約書", ["URLが不正"]),
]


def summarize(page, expect_texts: list[str]) -> dict:
    """ページの状態サマリを返す"""
    body_text = page.inner_text("body")[:5000]
    return {
        "title": page.title(),
        "url": page.url,
        "body_preview": body_text[:400],
        "has_error": any(marker in body_text for marker in
                          ["Traceback", "APIError", "ModuleNotFoundError",
                           "Page not found", "エラーが発生しました"]),
        "sidebar_items": _sidebar_items(page),
        "expected_found": {t: (t in body_text) for t in expect_texts},
    }


def _sidebar_items(page) -> list[str]:
    try:
        items = page.locator('section[data-testid="stSidebarNav"] ul li').all_inner_texts()
        return [i.strip() for i in items if i.strip()]
    except Exception:
        return []


def main():
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        )
        page = ctx.new_page()

        print("=" * 80)
        print("📋 管理画面ウォークスルー")
        print("=" * 80)

        for slug, path, expect_title, expect_texts in CHECKS:
            url = f"{BASE}{path}"
            print(f"\n▸ {slug}: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Streamlit描画を待つ
                time.sleep(3)
                page.screenshot(
                    path=str(OUT / f"{slug}.png"),
                    full_page=False,  # viewport sized for faster
                )
                info = summarize(page, expect_texts)
                info["slug"] = slug
                info["path"] = path
                results.append(info)
                print(f"   title: {info['title']}")
                print(f"   has_error: {info['has_error']}")
                if info["expected_found"]:
                    print(f"   expected: {info['expected_found']}")
            except Exception as e:
                print(f"   ❌ error: {e}")
                results.append({"slug": slug, "error": str(e)[:200]})

        # スタッフページ（トークンなしアクセス→警告出るはず）
        print("\n" + "=" * 80)
        print("🔒 スタッフ向けページ（トークンなしアクセステスト）")
        print("=" * 80)
        for slug, path, expect_title, expect_texts in STAFF_CHECKS:
            url = f"{BASE}{path}"
            print(f"\n▸ {slug}: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)
                page.screenshot(path=str(OUT / f"staff_{slug}.png"), full_page=False)
                info = summarize(page, expect_texts)
                info["slug"] = f"staff_{slug}"
                results.append(info)
                print(f"   title: {info['title']}")
                print(f"   expected: {info['expected_found']}")
                # サイドバーに現れていないか確認
                sidebar = info.get("sidebar_items", [])
                if "receipt download" in " ".join(sidebar).lower():
                    print("   ⚠️ サイドバーに receipt download が見えている")
                if "contract sign" in " ".join(sidebar).lower():
                    print("   ⚠️ サイドバーに contract sign が見えている")
            except Exception as e:
                print(f"   ❌ error: {e}")

        # モバイル表示テスト
        print("\n" + "=" * 80)
        print("📱 モバイル表示 (iPhone viewport)")
        print("=" * 80)
        mctx = browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                         "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148"),
            locale="ja-JP",
        )
        mpage = mctx.new_page()
        for slug, path in [("home", "/"), ("contracts", "/契約書発行"),
                            ("receipts", "/領収書発行")]:
            print(f"\n▸ mobile {slug}: {path}")
            try:
                mpage.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)
                mpage.screenshot(path=str(OUT / f"mobile_{slug}.png"), full_page=False)
                txt = mpage.inner_text("body")[:400]
                print(f"   preview: {txt[:120]}")
            except Exception as e:
                print(f"   ❌ error: {e}")

        browser.close()

    # 最終サマリ
    print("\n" + "=" * 80)
    print("📊 最終サマリ")
    print("=" * 80)
    errors = [r for r in results if r.get("has_error")]
    print(f"\n✅ 正常: {len(results) - len(errors)}/{len(results)}")
    if errors:
        print(f"❌ エラー検出: {len(errors)}件")
        for e in errors:
            print(f"  - {e['slug']}: {e.get('body_preview', '')[:200]}")
    # 期待項目の不足
    missing = []
    for r in results:
        if r.get("expected_found"):
            for k, v in r["expected_found"].items():
                if not v:
                    missing.append(f"{r['slug']}: 「{k}」が見つからない")
    if missing:
        print(f"\n⚠️ 期待要素不足: {len(missing)}件")
        for m in missing:
            print(f"  - {m}")

    print(f"\n📸 スクショ出力先: {OUT}")


if __name__ == "__main__":
    main()
