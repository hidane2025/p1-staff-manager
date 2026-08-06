"""操作マニュアル用スクリーンショットを撮る（2026-08-06 版）

前提: http://localhost:8611 でアプリ起動中（ADMIN_PASSWORD設定済み・デモデータ投入済み）
ポイント: Streamlitのセッションはページ遷移(goto)で切れるため、
         ログイン後は必ず**サイドバーのリンクをクリック**して移動する（実利用と同じ動線）。
出力: shots/*.png
"""
from __future__ import annotations

import pathlib
import time

from playwright.sync_api import sync_playwright, Page

HERE = pathlib.Path(__file__).parent
OUT = HERE / "shots"
OUT.mkdir(exist_ok=True)
BASE = "http://localhost:8611"
EVENT_LABEL = "【操作説明用】"
DEMO_PW = "demo-manual-shot-only"

HIDE_CSS = """
[data-testid='stToolbar'], [data-testid='stDecoration'], footer,
[data-testid='stStatusWidget'] { display: none !important; }
"""


def ready(page: Page, extra: float = 1.5) -> None:
    page.wait_for_selector("[data-testid='stAppViewContainer']", timeout=45000)
    for _ in range(160):
        if not page.query_selector("[data-testid='stStatusWidget']"):
            break
        time.sleep(0.25)
    time.sleep(extra)
    try:
        page.add_style_tag(content=HIDE_CSS)
    except Exception:
        pass


def login(page: Page, operator: str = "見本") -> bool:
    op_box = pw_box = None
    for b in page.query_selector_all("input"):
        lbl = b.get_attribute("aria-label") or ""
        if "オペレーター" in lbl:
            op_box = b
        elif b.get_attribute("type") == "password":
            pw_box = b
    if pw_box is None:
        return False
    if op_box:
        op_box.fill(operator)
    pw_box.fill(DEMO_PW)
    for btn in page.query_selector_all("button"):
        if "ログイン" in (btn.inner_text() or ""):
            btn.click()
            break
    ready(page, 3.0)
    return True


def nav(page: Page, label: str) -> bool:
    """サイドバーのリンクをクリックして移動（セッション維持）"""
    for a in page.query_selector_all("[data-testid='stSidebar'] a"):
        if label in (a.inner_text() or ""):
            a.click()
            ready(page, 2.0)
            return True
    return False


def pick_event(page: Page) -> None:
    for b in page.query_selector_all("[data-testid='stSelectbox']"):
        try:
            if EVENT_LABEL in (b.inner_text() or ""):
                return
        except Exception:
            pass
    boxes = page.query_selector_all("[data-testid='stSelectbox']")
    if not boxes:
        return
    boxes[0].click()
    time.sleep(0.8)
    for o in page.query_selector_all("[role='option']"):
        if EVENT_LABEL in (o.inner_text() or ""):
            o.click()
            ready(page, 2.0)
            return
    page.keyboard.press("Escape")


SCROLL_JS = """
(frac) => {
  const cands = Array.from(document.querySelectorAll('section, div'))
    .filter(e => e.scrollHeight > e.clientHeight + 200);
  const el = cands.sort((a,b) => b.scrollHeight - a.scrollHeight)[0]
             || document.scrollingElement;
  el.scrollTop = (el.scrollHeight - el.clientHeight) * frac;
  return [el.scrollTop, el.scrollHeight];
}
"""


def scroll_to(page: Page, frac: float) -> None:
    try:
        page.evaluate(SCROLL_JS, frac)
    except Exception:
        pass
    time.sleep(1.5)


def shot(page: Page, name: str, full: bool = True) -> None:
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=full)
    print(f"  📸 {name}.png ({path.stat().st_size // 1024}KB)")


PAGES = [
    ("イベント設定", "02_event_setup"),
    ("スタッフ管理", "03_staff"),
    ("シフト取込", "04_shift_import"),
    ("交通費", "05_transport"),
    ("出退勤", "06_attendance"),
    ("ピット端末", "07_pit_before_search"),
    ("支払い計算", "08_payment"),
    ("封筒リスト", "09_envelope"),
    ("精算レポート", "10_report"),
    ("領収書発行", "11_receipt_issue"),
    ("契約書発行", "12_contract_issue"),
    ("アカウント管理", "13_users"),
    ("個別手当", "14_allowances"),
]


def main() -> None:
    with sync_playwright() as p:
        br = p.chromium.launch()
        ctx = br.new_context(viewport={"width": 1440, "height": 1000},
                             device_scale_factor=2, locale="ja-JP")
        page = ctx.new_page()

        page.goto(BASE, wait_until="networkidle")
        ready(page, 2.5)
        shot(page, "00_login")
        if not login(page):
            print("  ⚠️ ログインフォームが見つからない")
        shot(page, "01_home")

        for label, name in PAGES:
            try:
                if not nav(page, label):
                    print(f"  ⚠️ {name}: サイドバーに「{label}」が無い")
                    continue
                pick_event(page)
                shot(page, name)
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠️ {name}: {str(e)[:80]}")

        # ピット端末: NO.検索した状態
        try:
            nav(page, "ピット端末")
            pick_event(page)
            for i in page.query_selector_all("input[type='text']"):
                if "18" in (i.get_attribute("placeholder") or ""):
                    i.fill("9101")
                    i.press("Enter")
                    break
            ready(page, 2.5)
            shot(page, "15_pit_searched")
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠️ 15_pit_searched: {str(e)[:80]}")

        # 支払い計算: 計算実行 → 一覧と個別内訳
        try:
            nav(page, "支払い計算")
            pick_event(page)
            for b in page.query_selector_all("button"):
                if "支払い額を計算" in (b.inner_text() or ""):
                    b.click()
                    break
            ready(page, 5.0)
            shot(page, "16_payment_calculated")
            # 個別内訳までスクロール（Streamlitは内側コンテナがスクロールする）
            scroll_to(page, 0.72)
            shot(page, "17_payment_detail", full=False)
            # 承認まで実行（この後の画面を実運用の姿にするため）
            scroll_to(page, 0.45)
            for b in page.query_selector_all("button"):
                if "一括承認" in (b.inner_text() or ""):
                    b.click()
                    ready(page, 4.0)
                    break
            scroll_to(page, 0.0)
            shot(page, "21_payment_approved")
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠️ 16/17: {str(e)[:80]}")

        # 計算後の封筒・レポート
        for label, name in (("封筒リスト", "18_envelope_after"),
                            ("精算レポート", "19_report_after"),
                            ("領収書発行", "20_receipt_after")):
            try:
                nav(page, label)
                pick_event(page)
                shot(page, name)
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠️ {name}: {str(e)[:80]}")

        br.close()
    print("撮影完了:", len(list(OUT.glob("*.png"))), "枚")


if __name__ == "__main__":
    main()
