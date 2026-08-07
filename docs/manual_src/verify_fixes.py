"""2026-08-07 の修正3件を、実際のUI操作で検証する

前提: localhost:8613（ADMIN_PASSWORD=verify-local-only・デモデータ投入済み）
検証:
  ①退勤済みの時刻修正   ②NO./名前検索の競合解消   ③分の5分きざみ
  ＋ 既存機能が壊れていないこと（通常の退勤確定・支払い計算・金額の一致）
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright, Page

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(pathlib.Path.home() / "Documents/GitHub/p1-staff-manager"))
BASE = "http://localhost:8613"
PW = "verify-local-only"
LABEL = "【操作説明用】"
IDS = json.loads((HERE / "demo_ids.json").read_text())
EV = IDS["event"]

ok_n = ng = 0


def chk(name: str, cond: bool, detail: str = "") -> None:
    global ok_n, ng
    if cond:
        ok_n += 1
        print(f"  ✅ {name}")
    else:
        ng += 1
        print(f"  ❌ {name} — {detail}")


def ready(p: Page, e: float = 2.0) -> None:
    p.wait_for_selector("[data-testid='stAppViewContainer']", timeout=45000)
    for _ in range(160):
        if not p.query_selector("[data-testid='stStatusWidget']"):
            break
        time.sleep(0.25)
    time.sleep(e)


def body(p: Page) -> str:
    return p.inner_text("[data-testid='stAppViewContainer']")


def nav(p: Page, label: str) -> bool:
    for a in p.query_selector_all("[data-testid='stSidebar'] a"):
        if label in (a.inner_text() or ""):
            a.click()
            ready(p, 2.2)
            return True
    return False


def pick_event(p: Page) -> None:
    for sb in p.query_selector_all("[data-testid='stSelectbox']"):
        if LABEL in (sb.inner_text() or ""):
            return
    sbs = p.query_selector_all("[data-testid='stSelectbox']")
    if not sbs:
        return
    sbs[0].click()
    time.sleep(0.8)
    for o in p.query_selector_all("[role='option']"):
        if LABEL in (o.inner_text() or ""):
            o.click()
            ready(p, 2.2)
            return
    p.keyboard.press("Escape")


def set_no(p: Page, no: str) -> None:
    for i in p.query_selector_all("input"):
        if "18" in (i.get_attribute("placeholder") or ""):
            i.fill(no)
            i.press("Enter")
            ready(p, 2.2)
            return


def set_name(p: Page, name: str) -> None:
    for i in p.query_selector_all("input"):
        if "EveKat" in (i.get_attribute("placeholder") or ""):
            i.fill(name)
            i.press("Enter")
            ready(p, 2.2)
            return


def set_time(p: Page, hour: int, minute: int) -> bool:
    got_h = False
    for i in p.query_selector_all("input[type='number']"):
        lbl = i.get_attribute("aria-label") or ""
        if "退勤時刻（時）" in lbl:
            i.fill(str(hour))
            i.press("Tab")
            got_h = True
            break
    time.sleep(1.0)
    for sb in p.query_selector_all("[data-testid='stSelectbox']"):
        if "退勤時刻（分）" in (sb.inner_text() or ""):
            sb.click()
            time.sleep(0.8)
            # ドロップダウンは一度に10件までしか表示されないため、
            # 数字を打って絞り込んでから選ぶ（実利用でも同じ操作ができる）
            p.keyboard.type(str(minute))
            time.sleep(0.8)
            for o in p.query_selector_all("[role='option']"):
                if (o.inner_text() or "").strip() == str(minute):
                    o.click()
                    ready(p, 1.8)
                    return got_h
            p.keyboard.press("Escape")
    return got_h


def click(p: Page, text: str, wait: float = 3.0) -> bool:
    for b in p.query_selector_all("button"):
        if text in (b.inner_text() or ""):
            b.click()
            ready(p, wait)
            return True
    return False


def expand(p: Page, text: str) -> bool:
    for e in p.query_selector_all("summary, [data-testid='stExpander'] summary"):
        if text in (e.inner_text() or ""):
            e.click()
            ready(p, 1.5)
            return True
    return False


def main() -> None:
    import db
    c = db.get_client()
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        page = br.new_context(viewport={"width": 1440, "height": 1100},
                              locale="ja-JP").new_page()
        page.goto(BASE, wait_until="networkidle")
        ready(page, 2.5)
        for i in page.query_selector_all("input"):
            if "オペレーター" in (i.get_attribute("aria-label") or ""):
                i.fill("検証太郎")
            elif i.get_attribute("type") == "password":
                i.fill(PW)
        click(page, "ログイン")

        # ================= ③ 分の刻み =================
        print("\n━━━ ③ 分の刻み（5分） ━━━")
        nav(page, "ピット端末")
        pick_event(page)
        set_no(page, "9101")
        opts = []
        for sb in page.query_selector_all("[data-testid='stSelectbox']"):
            if "退勤時刻（分）" in (sb.inner_text() or ""):
                sb.click()
                time.sleep(0.7)
                opts = [o.inner_text().strip() for o in page.query_selector_all("[role='option']")]
                page.keyboard.press("Escape")
                time.sleep(0.4)
                break
        from utils.time_input import MINUTE_CHOICES as _MC
        chk("分の選択肢は5分きざみ12個（コード）", len(_MC) == 12 and _MC[1] == 5, str(_MC))
        chk("一覧の先頭10件が5分きざみで出る",
            opts[:10] == ["0", "5", "10", "15", "20", "25", "30", "35", "40", "45"], f"{opts}")

        # ================= 通常の退勤確定（既存機能） =================
        print("\n━━━ 既存機能: 通常の退勤確定 ━━━")
        set_time(page, 22, 50)
        chk("確定ボタンが「退勤＋支払い確定」", click(page, "退勤＋支払い確定", 5.0))
        sid = IDS["staff"]["9101"]
        rows = db.get_shifts_for_event(EV, staff_id=sid)
        ends = {r["date"]: (r.get("actual_end"), r["status"]) for r in rows}
        chk("22:50 で記録された（50分は入力で絞り込んで選択）",
            any(v[0] == "22:50" for v in ends.values()), str(ends))
        pay = c.table("p1_payments").select("*").eq("event_id", EV).eq("staff_id", sid).execute().data
        chk("支払いが計算・保存された", bool(pay), f"{len(pay)}件")
        _before_total = int(pay[0]["total_amount"]) if pay else 0

        # ================= ① 退勤済みの修正 =================
        print("\n━━━ ① 退勤済みの時刻修正 ━━━")
        nav(page, "ピット端末")
        pick_event(page)
        set_no(page, "9101")
        t = body(page)
        chk("退勤済みでも修正メニューが出る", "退勤時刻を修正する" in t, t[-200:])
        chk("状態は「退勤済」と表示される", "退勤済" in t)
        opened = expand(page, "退勤時刻を修正する")
        chk("修正フォームを開ける", opened)
        if opened:
            t = body(page)
            chk("ボタンが「この時刻に修正する」", "この時刻に修正する" in t, t[-200:])
            set_time(page, 23, 15)
            chk("修正を実行できる", click(page, "この時刻に修正する", 5.0))
            rows = db.get_shifts_for_event(EV, staff_id=sid)
            ends = {r["date"]: r.get("actual_end") for r in rows}
            chk("23:15 に修正された", "23:15" in str(ends), str(ends))
            pay2 = c.table("p1_payments").select("*").eq("event_id", EV).eq("staff_id", sid).execute().data
            chk("支払いが再計算された（金額が増えた）",
                pay2 and int(pay2[0]["total_amount"]) > _before_total,
                f"{_before_total} → {pay2[0]['total_amount'] if pay2 else '—'}")
            logs = c.table("p1_audit_log").select("action,detail").eq("event_id", EV)\
                .eq("action", "pit_checkout_fix").execute().data
            chk("修正が監査ログに別アクションで残る", bool(logs),
                str(logs[:1]))

        # ================= ② 検索の競合 =================
        print("\n━━━ ② NO./名前検索の競合解消 ━━━")
        nav(page, "ピット端末")
        pick_event(page)
        set_no(page, "99999")          # 存在しないNO.
        set_name(page, "デモ")          # 名前も入れる
        t = body(page)
        chk("NO.が空振りしたら名前で見つかる", "デモ花子" in t, t[-250:])
        chk("フォールバックした旨が案内される", "ディーラーネームで検索" in t)
        # クリアボタン
        nav(page, "ピット端末")
        pick_event(page)
        set_no(page, "9103")
        chk("クリア前はNO.9103が出ている", "テスト次郎" in body(page))
        chk("「検索をクリア」ボタンがある", click(page, "検索をクリア", 2.5))
        t = body(page)
        chk("クリア後は候補が消える", "テスト次郎" not in t and "見つかりません" not in t,
            t[-200:])

        # ================= 支払済みの保護 =================
        print("\n━━━ 支払済みは修正できない（保護） ━━━")
        c.table("p1_payments").update({"status": "paid"}).eq("event_id", EV)\
            .eq("staff_id", sid).execute()
        nav(page, "ピット端末")
        pick_event(page)
        set_no(page, "9101")
        t = body(page)
        chk("支払済みだと修正フォームが出ない", "退勤時刻を修正する" not in t)
        chk("経理へ連絡する案内が出る", "支払い済み" in t and "経理" in t, t[-250:])
        c.table("p1_payments").update({"status": "pending"}).eq("event_id", EV)\
            .eq("staff_id", sid).execute()

        # ================= 出退勤ページ（刻み統一の確認） =================
        print("\n━━━ 出退勤ページ（刻みの統一） ━━━")
        nav(page, "出退勤")
        pick_event(page)
        t = body(page)
        chk("出退勤ページが例外なく開く", "出退勤" in t and "エラー" not in t)

        br.close()
    print(f"\n{'='*56}\n検証 {ok_n + ng} 件 / 合致 {ok_n} / 不一致 {ng}")
    sys.exit(1 if ng else 0)


if __name__ == "__main__":
    main()
