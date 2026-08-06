"""操作説明書のファクトチェック — 記述どおりに実際のUIを操作して検証する

前提: localhost:8612 でアプリ起動中（ADMIN_PASSWORD=factcheck-local-only・デモデータ投入済み）
方針: 説明書の各記述を「主張」に分解し、UI操作＋DB照合で真偽を判定する。
     本番に影響する操作（アカウント作成＝共有パスワード無効化）は行わない。
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright, Page

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(pathlib.Path.home() / "Documents/GitHub/p1-staff-manager"))
BASE = "http://localhost:8612"
PW = "factcheck-local-only"
EVENT_LABEL = "【操作説明用】"
IDS = json.loads((HERE / "demo_ids.json").read_text())
EV = IDS["event"]

results = []


def claim(section: str, text: str, ok: bool, detail: str = "") -> None:
    results.append((section, text, ok, detail))
    print(f"  {'✅' if ok else '❌'} [{section}] {text}" + (f" — {detail}" if not ok else ""))


def ready(page: Page, extra: float = 1.5) -> None:
    page.wait_for_selector("[data-testid='stAppViewContainer']", timeout=45000)
    for _ in range(160):
        if not page.query_selector("[data-testid='stStatusWidget']"):
            break
        time.sleep(0.25)
    time.sleep(extra)


def body(page: Page) -> str:
    return page.inner_text("[data-testid='stAppViewContainer']")


def login(page: Page, operator: str = "見本花子") -> None:
    for b in page.query_selector_all("input"):
        lbl = b.get_attribute("aria-label") or ""
        if "オペレーター" in lbl and operator:
            b.fill(operator)
        elif b.get_attribute("type") == "password":
            b.fill(PW)
    for btn in page.query_selector_all("button"):
        if "ログイン" in (btn.inner_text() or ""):
            btn.click()
            break
    ready(page, 3.0)


def nav(page: Page, label: str) -> bool:
    for a in page.query_selector_all("[data-testid='stSidebar'] a"):
        if label in (a.inner_text() or ""):
            a.click()
            ready(page, 2.0)
            return True
    return False


def pick_event(page: Page) -> None:
    for b in page.query_selector_all("[data-testid='stSelectbox']"):
        if EVENT_LABEL in (b.inner_text() or ""):
            return
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


def clear_no(page: Page) -> None:
    """NO.欄を空にする（NO.が残っていると名前検索が効かない仕様のため）"""
    for i in page.query_selector_all("input"):
        if "18" in (i.get_attribute("placeholder") or ""):
            i.fill("")
            i.press("Enter")
            ready(page, 1.5)
            return


def set_checkout(page: Page, hour: int, minute: int) -> bool:
    """退勤時刻を入れる（時=number_input / 分=selectbox の2欄構成）"""
    done_h = False
    for i in page.query_selector_all("input[type='number']"):
        lbl = i.get_attribute("aria-label") or ""
        if "時" in lbl and "分" not in lbl:
            i.fill(str(hour))
            i.press("Tab")
            done_h = True
            break
    time.sleep(1.0)
    for sb in page.query_selector_all("[data-testid='stSelectbox']"):
        if "分" in (sb.inner_text() or ""):
            sb.click()
            time.sleep(0.6)
            for o in page.query_selector_all("[role='option']"):
                if (o.inner_text() or "").strip() == str(minute):
                    o.click()
                    ready(page, 1.5)
                    return done_h
            page.keyboard.press("Escape")
    return done_h


def click_btn(page: Page, text: str) -> bool:
    for b in page.query_selector_all("button"):
        if text in (b.inner_text() or ""):
            b.click()
            ready(page, 3.0)
            return True
    return False


def fill_by_label(page: Page, label_part: str, value: str) -> bool:
    for i in page.query_selector_all("input, textarea"):
        lbl = (i.get_attribute("aria-label") or "") + (i.get_attribute("placeholder") or "")
        if label_part in lbl:
            i.fill(value)
            return True
    return False


SCROLL_JS = """(f)=>{const c=Array.from(document.querySelectorAll('section,div'))
.filter(e=>e.scrollHeight>e.clientHeight+200);
const el=c.sort((a,b)=>b.scrollHeight-a.scrollHeight)[0]||document.scrollingElement;
el.scrollTop=(el.scrollHeight-el.clientHeight)*f;}"""


def scroll(page: Page, f: float) -> None:
    try:
        page.evaluate(SCROLL_JS, f)
    except Exception:
        pass
    time.sleep(1.0)


def main() -> None:
    import db
    with sync_playwright() as p:
        br = p.chromium.launch()
        ctx = br.new_context(viewport={"width": 1440, "height": 1100}, locale="ja-JP")
        page = ctx.new_page()

        # ============ 第1部 ============
        print("\n━━━ 第1部 全員共通 ━━━")
        page.goto(BASE, wait_until="networkidle")
        ready(page, 2.5)
        t = body(page)
        claim("1-2", "ログイン画面に「オペレーター名」欄がある", "オペレーター名" in t)
        claim("2-1", "ログイン画面に当日運用コードの入口がある", "当日運用コード" in t, t[:150])

        # 名前なしログイン → 承認ボタンが出ないこと（説明書1-2の主張）
        for i in page.query_selector_all("input"):
            if i.get_attribute("type") == "password":
                i.fill(PW)
        click_btn(page, "ログイン")
        nav(page, "支払い計算")
        pick_event(page)
        click_btn(page, "支払い額を計算")
        t = body(page)
        no_name_warn = "オペレーター名" in t and ("無効化" in t or "押せません" in t or "記録できません" in t)
        has_approve = any("一括承認" in (b.inner_text() or "") for b in page.query_selector_all("button"))
        claim("1-2", "名前を入れずに入ると承認ボタンが押せない",
              no_name_warn and not has_approve,
              f"警告={no_name_warn} 承認ボタン={has_approve}")

        # 名前ありで入り直す
        page.goto(BASE, wait_until="networkidle")
        ready(page, 2.5)
        login(page, "見本花子")
        t = body(page)
        claim("1-3", "サイドバーに「ピット端末」「支払い計算」「封筒リスト」がある",
              all(k in t for k in ("ピット端末", "支払い計算", "封筒リスト")))
        claim("1-3", "STEP 1〜4 の帯がある", "STEP 1" in t and "STEP 4" in t)

        # ============ 第2部 ピット担当 ============
        print("\n━━━ 第2部 ピット担当 ━━━")
        nav(page, "ピット端末")
        pick_event(page)
        t = body(page)
        claim("2-2", "NO.（数字）とディーラーネームの2つの検索欄がある",
              "NO.（数字）" in t and "ディーラーネーム" in t)
        claim("2-4", "配布チェック（弁当・ドリンク券）がある", "配布チェック" in t)

        # 存在しないNO.
        fill_by_label(page, "18", "99999")
        page.keyboard.press("Enter")
        ready(page, 2.0)
        t = body(page)
        claim("2-4", "存在しないNO.は「見つかりません」と出る（落ちない）",
              "見つかりません" in t, t[-200:])

        # 名前の部分一致
        nav(page, "ピット端末")
        pick_event(page)
        clear_no(page)
        fill_by_label(page, "EveKat", "デモ")
        page.keyboard.press("Enter")
        ready(page, 2.5)
        t = body(page)
        claim("2-2", "ディーラーネームの部分一致で探せる", "デモ花子" in t, t[-250:])
        claim("2-1", "ピット端末に本名・住所が表示されない",
              "見本 デモ花子" not in t and "堺市" not in t)

        # 深夜跨ぎの人を確定（27:00表記）
        sid = IDS["staff"]["9102"]
        before = db.get_shifts_for_event(EV, staff_id=sid)
        set_ok = set_checkout(page, 27, 30)
        ok_btn = click_btn(page, "退勤＋支払い確定") or click_btn(page, "退勤")
        after = db.get_shifts_for_event(EV, staff_id=sid)
        ends = {s["date"]: s.get("actual_end") for s in after}
        claim("2-3", "24時超え（27時30分）で退勤確定できる",
              ok_btn and "27:30" in str(ends), f"設定={set_ok} btn={ok_btn} ends={ends}")
        pay = db.get_client().table("p1_payments").select("*").eq("event_id", EV)\
            .eq("staff_id", sid).execute().data
        claim("2-3", "退勤確定と同時に支払いが計算・保存される", bool(pay),
              f"{len(pay)}件")
        if pay:
            claim("2-3", "深夜勤務に深夜手当がつく", int(pay[0]["night_pay"] or 0) > 0,
                  f"night_pay={pay[0]['night_pay']}")

        # 説明書の記述「25:00 のように書く」の真偽
        nums = [(i.get_attribute("aria-label"), i.get_attribute("max"))
                for i in page.query_selector_all("input[type='number']")]
        hour_box = [n for n in nums if n[0] and "時" in n[0] and "分" not in n[0]]
        claim("2-3", "退勤時刻は「25:00」と1つの欄に入力する（説明書の記述）",
              False if hour_box else True,
              f"実際は時と分の2欄構成。時欄={hour_box}")

        # やり直し（同じ人を再確定）
        nav(page, "ピット端末")
        pick_event(page)
        fill_by_label(page, "18", "9102")
        page.keyboard.press("Enter")
        ready(page, 2.5)
        set_checkout(page, 26, 0)
        redo = click_btn(page, "退勤＋支払い確定") or click_btn(page, "退勤")
        after2 = db.get_shifts_for_event(EV, staff_id=sid)
        claim("2-4", "時刻を間違えても同じ人を呼び出して確定し直せる",
              redo and "26:00" in str({s["date"]: s.get("actual_end") for s in after2}),
              str({s["date"]: s.get("actual_end") for s in after2}))

        # ============ 第3部 経理 ============
        print("\n━━━ 第3部 経理担当 ━━━")
        nav(page, "支払い計算")
        pick_event(page)
        click_btn(page, "支払い額を計算")
        t = body(page)
        claim("3-1", "計算すると「◯名の支払い額を計算・保存しました」が出る",
              "計算・保存しました" in t, t[:200])
        claim("3-1", "交通費0円の人がいると理由が案内される",
              "交通費が" in t and "0" in t, "（該当者がいない場合はスキップ可）")

        rows = db.get_client().table("p1_payments").select("*").eq("event_id", EV).execute().data
        # 内訳の和＝合計（説明書3-2の主張）
        bad = []
        for r in rows:
            s = sum(int(r.get(k) or 0) for k in ("base_pay", "night_pay", "transport_total",
                                                 "floor_bonus_total", "mix_bonus_total",
                                                 "attendance_bonus", "adjustment"))
            s -= int(r.get("break_deduction") or 0)
            allow = sum(int(a.get("amount") or 0)
                        for a in db.get_individual_allowances(EV, r["staff_id"]))
            if s + allow != int(r["total_amount"] or 0):
                bad.append((r["staff_id"], s + allow, r["total_amount"]))
        claim("3-2", "内訳の合計＝支給合計（全員）", not bad, str(bad))

        # 交通費のルール（説明書4-3の主張）
        rules = {x["region"]: x for x in db.get_transport_rules(EV)}
        days = {}
        for s in db.get_shifts_for_event(EV):
            if s.get("status") != "absent":
                days.setdefault(s["staff_id"], set()).add(s["date"])
        staff = {x["id"]: x for x in db.get_all_staff()}
        tbad = []
        for r in rows:
            st = staff.get(r["staff_id"], {})
            ru = rules.get(st.get("region") or "")
            exp = None
            if ru and ru.get("is_venue_region"):
                exp = int(ru["max_amount"]) * len(days.get(r["staff_id"], ()))
            if exp is not None and exp != int(r["transport_total"] or 0):
                tbad.append((st.get("name_jp"), exp, r["transport_total"]))
        claim("4-3", "開催地は「1日あたりの金額 × 出勤日数」で支給される",
              not tbad, str(tbad))

        # 承認
        approved = click_btn(page, "一括承認")
        sts = [x["status"] for x in db.get_client().table("p1_payments")
               .select("status").eq("event_id", EV).execute().data]
        claim("3-3", "一括承認で全員が承認済みになる",
              approved and sts.count("approved") == len(sts), f"{sts}")

        # 領収書未受領では支払えない（説明書3-5の主張）
        t = body(page)
        can_pay = any("支払済み" in (b.inner_text() or "") and "確定" not in (b.inner_text() or "")
                      for b in page.query_selector_all("button"))
        claim("3-5", "領収書を受け取っていないと支払いに進めない",
              (not can_pay) or "未受領" in t, f"支払ボタン={can_pay}")

        # 承認後にシフトを変えると未承認へ戻る（説明書3-1の主張）
        db.upsert_shift(EV, IDS["staff"]["9101"], "2026-09-01", "13:00", "23:00")
        st1 = db.get_client().table("p1_payments").select("status")\
            .eq("event_id", EV).eq("staff_id", IDS["staff"]["9101"]).execute().data
        claim("3-1", "後からシフトを直すとその人だけ未承認に戻る",
              st1 and st1[0]["status"] == "pending", str(st1))

        # ============ 第4部 準備 ============
        print("\n━━━ 第4部 準備担当 ━━━")
        nav(page, "シフト取込")
        pick_event(page)
        t = body(page)
        claim("4-2", "対応フォーマットにExcel/CSV/TSVの記載がある",
              "CSV" in t and ("xlsx" in t or "Excel" in t), t[:250])

        nav(page, "交通費")
        pick_event(page)
        t = body(page)
        claim("4-3", "開催地は領収書不要・1日あたり一律と画面に書いてある",
              "出勤1日あたり" in t and "領収書不要" in t, t[:300])
        claim("4-3", "見積（銀行準備の目安）がある", "事前見積" in t or "見積" in t)

        nav(page, "アカウント管理")
        t = body(page)
        claim("4-4", "アカウント管理画面が開き、追加フォームがある",
              "アカウントを追加" in t)
        claim("4-4", "1つ目を作ると共有パスワードが使えなくなる旨の警告がある",
              "共有パスワード" in t and ("入れなくなり" in t or "切り替わり" in t), t[:400])

        # 封筒・レポート
        nav(page, "封筒リスト")
        pick_event(page)
        t = body(page)
        claim("3-4", "「銀行で用意する現金」の枚数が出る",
              "銀行で用意する現金" in t and "枚" in t)
        nav(page, "精算レポート")
        pick_event(page)
        t = body(page)
        claim("3-7", "「領収書 未受領」の人数が出る", "未受領" in t)
        claim("3-7", "CSV出力がある", "CSV" in t)

        br.close()

    ng = [r for r in results if not r[2]]
    print(f"\n{'='*60}")
    print(f"検証 {len(results)} 件 / 合致 {len(results)-len(ng)} / 不一致 {len(ng)}")
    if ng:
        print("\n【説明書の記述と実際が違う箇所】")
        for s, txt, _, d in ng:
            print(f"  ❌ [{s}] {txt}\n       実際: {d[:180]}")


if __name__ == "__main__":
    main()
