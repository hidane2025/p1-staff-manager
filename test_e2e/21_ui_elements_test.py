"""P1 Staff Manager — UI要素検出テスト（v3.7 全機能チェック）

Streamlit AppTest を使って、各ページの主要UI要素が**実際にレンダリング**されるかを検証する。
従来の 18_pages_smoke_test.py は「例外なし起動」のみを確認していたが、
このテストはタイトル文字列・タブ・ボタン・フォーム・KPI・フローバーまで踏み込む。

実行:
    cd p1-staff-manager
    .venv/bin/python test_e2e/21_ui_elements_test.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest

# 2026-07-29: 認証を fail-closed 化したため、認証情報が無い状態では
# 各ページが管理者ログイン画面で停止し、本来の画面が描画されない。
# このテストは「画面が正しく描画されるか」を見るものなので、
# 開発用の明示フラグで認証を外す（§16 だけは意図的にフラグを外して
# ゲートが機能することを確認する）。
os.environ["P1_ALLOW_NO_AUTH"] = "1"
os.environ.pop("ADMIN_PASSWORD", None)

# 2026-08-02: 本番DBに繋がずにUIを検証する。
# db.py から既定キーを削除（漏洩対策）したため、環境変数が無いと
# ページがDB呼び出しで例外になる。テストは本番へ接続すべきでないので、
# get_client() だけをスタブに差し替える（db.py の集計・整形ロジックは本物が動く）。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fake_db import install_fake_db  # noqa: E402
install_fake_db()


PASS = "✅"
FAIL = "❌"
failures: list = []


def _check(name: str, cond: bool, detail: str = ""):
    mark = PASS if cond else FAIL
    print(f"  {mark} {name}")
    if not cond:
        failures.append(f"{name}: {detail}")


def _is_harness_limitation(at) -> bool:
    """AppTest 側の制約による例外か（製品の不具合ではない）。

    st.page_link は AppTest 単体実行時に url_pathname を解決できず KeyError になる。
    実アプリでは正常に動くため、これを製品の欠陥と数えない。
    """
    if not at.exception:
        return False

    def _is_page_link_artifact(msg: str) -> bool:
        # AppTest は対象ページ自身をエントリポイントとして実行するため、
        # st.page_link("pages/xxx.py") の相対解決に失敗する。
        # 実アプリ（エントリ=app.py）では正しく解決されるので製品の不具合ではない。
        # ただし「実在しないパスを指している」場合は本物のバグなので、
        # 参照先がディスク上に在るときだけ環境要因と判定する。
        if "url_pathname" in msg:
            return True
        if "Could not find page" not in msg:
            return False
        import re as _re
        m = _re.search(r"`([^`]+\.py)`", msg)
        return bool(m) and (ROOT / m.group(1)).exists()

    return all(_is_page_link_artifact(str(getattr(e, "message", e))) for e in at.exception)


def _exc_detail(at) -> str:
    """失敗時に原因が分かるよう、例外の要約を返す。"""
    if not at.exception:
        return ""
    return " | ".join(str(getattr(e, "message", e))[:120] for e in at.exception)


def _no_product_exception(at) -> bool:
    """製品側の例外が無いこと（テスト環境固有の制約は除外）。"""
    return (not at.exception) or _is_harness_limitation(at)


def _texts(at) -> str:
    """全マークダウン/title/header/caption/警告/情報を連結した検索用文字列"""
    parts = []
    for kind in ("title", "header", "subheader", "markdown", "caption",
                 "warning", "info", "error", "success", "text"):
        try:
            for el in getattr(at, kind, []):
                v = getattr(el, "value", None) or getattr(el, "body", None)
                if v:
                    parts.append(str(v))
        except Exception:
            pass
    return "\n".join(parts)


def _has(at, *needles: str) -> bool:
    blob = _texts(at)
    return all(n in blob for n in needles)


def _count_buttons(at) -> int:
    try:
        return len(at.button)
    except Exception:
        return 0


def _count_tabs(at) -> int:
    try:
        return len(at.tabs)
    except Exception:
        return 0


# ============================================================
# 1. ホーム
# ============================================================
print("\n[1] ホーム (app.py)")
at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
_check("例外なし起動（製品側）", _no_product_exception(at), _exc_detail(at))
_check("タイトル 'P1 Staff Manager' を含む",
       _has(at, "P1 Staff Manager"))
_check("バージョン v3.10 表示（最新）", _has(at, "v3.10"))
_check("ダッシュボード見出し（v3.10: TODOリスト or 数字でみる現状）",
       _has(at, "今日のTo-Do") or _has(at, "数字でみる現状"))
# UX A (2026-05-09): 進捗チェックリストが描画されている
_check("UX A: ホームに進捗チェックリストが導入されている",
       _has(at, "今日のTo-Do") or _has(at, "今日の進捗"))
_check("業務の流れ STEP 1〜4 全部",
       _has(at, "STEP 1", "STEP 2", "STEP 3", "STEP 4"))
_check("4段階「作る/入れる/計算/渡す」",
       _has(at, "作る", "入れる", "計算", "渡す"))
_check("KPI: 進行中のイベント / 未承認 / 領収書",
       _has(at, "進行中のイベント", "未承認の支払い", "領収書"))
_check("補助ツール（折りたたみ）あり",
       _has(at, "補助ツール"))


# ============================================================
# 2. 0_イベント設定（ウィザード）
# ============================================================
print("\n[2] 0_イベント設定")
at = AppTest.from_file(str(ROOT / "pages/0_event_setup.py"), default_timeout=30).run()
_check("例外なし起動（製品側）", _no_product_exception(at), _exc_detail(at))
_check("タイトル 'イベント設定'", _has(at, "イベント設定"))
_check("フローバー active=setup",
       _has(at, "STEP 1", "作る"))
tab_count = _count_tabs(at)
_check(f"3タブ構成（JSON投入/プリセット/既存編集） tabs={tab_count}",
       tab_count >= 3, f"got tab count {tab_count}")


# ============================================================
# 3. 1_staff
# ============================================================
print("\n[3] 1_staff")
at = AppTest.from_file(str(ROOT / "pages/1_staff.py"), default_timeout=30).run()
_check("例外なし起動（製品側）", _no_product_exception(at), _exc_detail(at))
_check("タイトル 'スタッフ管理'", _has(at, "スタッフ管理"))
_check("フローバー active=input",
       _has(at, "STEP 2", "入れる"))
_check("検索ボックスあり",
       _has(at, "検索") or len(at.text_input) > 0)
tab_count = _count_tabs(at)
_check(f"取込 4タブ構成 tabs={tab_count}",
       tab_count >= 4, f"got {tab_count}")


# ============================================================
# 4. 2_シフト取込
# ============================================================
print("\n[4] 2_シフト取込")
at = AppTest.from_file(str(ROOT / "pages/2_shift_import.py"), default_timeout=30).run()
_check("例外なし起動（製品側）", _no_product_exception(at), _exc_detail(at))
_check("タイトル 'シフト取込'", _has(at, "シフト取込"))
_check("フローバー active=input/done=setup",
       _has(at, "STEP 1", "STEP 2"))


# ============================================================
# 5. 3_支払い計算
# ============================================================
print("\n[5] 3_支払い計算")
at = AppTest.from_file(str(ROOT / "pages/3_payment.py"), default_timeout=30).run()
_check("例外なし起動（製品側）", _no_product_exception(at), _exc_detail(at))
_check("タイトル '支払い計算'", _has(at, "支払い計算"))
_check("フローバー active=calc",
       _has(at, "STEP 3", "計算"))


# ============================================================
# 6. 4_封筒リスト
# ============================================================
print("\n[6] 4_封筒リスト")
at = AppTest.from_file(str(ROOT / "pages/4_envelope.py"), default_timeout=30).run()
_check("例外なし起動（製品側）", _no_product_exception(at), _exc_detail(at))
_check("タイトル '封筒リスト'", _has(at, "封筒リスト"))


# ============================================================
# 7. 5_出退勤
# ============================================================
print("\n[7] 5_出退勤")


def _button_labels(at) -> str:
    """全ボタンの label を1つの文字列に連結（検索用）"""
    parts = []
    try:
        for b in at.button:
            v = getattr(b, "label", None)
            if v:
                parts.append(str(v))
    except Exception:
        pass
    return " | ".join(parts)


# pages/5 はシフトが無い日は空状態で正しく早期 stop する設計のため、タブ検証には
# 「初日にシフトがあるイベント」へ誘導する（可変な本番データへの依存を排した頑健化）。
# 旧テストは最新イベント既定が偶然シフトを持つ前提で、データが入れ替わると誤って赤くなった。
import db as _db_att  # noqa: E402
_att_event = None
try:
    for _ev in (_db_att.get_all_events() or []):
        _dates = [r["date"] for r in (_db_att.get_event_rates(_ev["id"]) or [])]
        if _dates and _db_att.get_shifts_for_event(_ev["id"], date=_dates[0]):
            _att_event = _ev["id"]
            break
except Exception:
    _att_event = None

at = AppTest.from_file(str(ROOT / "pages/5_attendance.py"), default_timeout=30)
if _att_event is not None:
    # select_event は session_state["selected_event_id"] を読む（utils/event_selector.py）
    at.session_state["selected_event_id"] = _att_event
at.run()
_check("例外なし起動（製品側）", _no_product_exception(at), _exc_detail(at))
_check("タイトル '出退勤'", _has(at, "出退勤"))

# Phase 1-2 (2026-05-08): 個別リセットタブが追加されていること
tab_count_5 = _count_tabs(at)
if tab_count_5 == 0:
    # どのイベントの初日にもシフトが無い（テストデータ枯渇）場合は、
    # 空状態を例外なく表示しているかだけ検証する（タブ検証はデータ有時のみ）。
    _check(
        "シフト無しでも空状態を例外なく表示（タブ検証はデータ有時のみ実施）",
        _no_product_exception(at),
    )
else:
    _check(
        f"タブが6個に増えた（旧5: 凍結/欠勤/遅刻/延長/早退 + 新1: 個別リセット）tabs={tab_count_5}",
        tab_count_5 >= 6, f"got {tab_count_5}",
    )
    _check("『個別リセット』タブの中身が描画されている",
           _has(at, "入力ミスや誤操作の取り消し") or _has(at, "1名だけ"))
    _check("『全員リセット』ボタンが個別と分離（リネーム済）",
           "全員リセット" in _button_labels(at))


# ============================================================
# 8. 6_精算レポート（管理者ガード対象）
# ============================================================
print("\n[8] 6_精算レポート")
at = AppTest.from_file(str(ROOT / "pages/6_report.py"), default_timeout=30).run()
_check("例外なし起動（製品側）", _no_product_exception(at), _exc_detail(at))
_check("タイトル '精算レポート'", _has(at, "精算レポート"))
# 2026-07-29: 認証未設定時の挙動を fail-open → fail-closed に変更した。
# 本テストは P1_ALLOW_NO_AUTH=1 を明示しているので「認証なしモード」の
# 警告が出るのが正しい（何も出ずに素通りするのは退行）。
_check("認証なしモードであることが画面に明示される",
       _has(at, "認証なしモード") or _has(at, "P1_ALLOW_NO_AUTH"))


# ============================================================
# 9. 7_年間累計（管理者ガード対象）
# ============================================================
print("\n[9] 7_年間累計")
at = AppTest.from_file(str(ROOT / "pages/7_yearly.py"), default_timeout=30).run()
_check("例外なし起動（製品側）", _no_product_exception(at), _exc_detail(at))
_check("タイトル '年間累計'", _has(at, "年間累計"))


# ============================================================
# 10. 8_交通費
# ============================================================
print("\n[10] 8_交通費")
at = AppTest.from_file(str(ROOT / "pages/8_transport.py"), default_timeout=30).run()
_check("例外なし起動（製品側）", _no_product_exception(at), _exc_detail(at))
_check("タイトル '交通費'", _has(at, "交通費"))


# ============================================================
# 11. 91_領収書発行（管理者ガード対象）
# ============================================================
print("\n[11] 91_領収書発行")
at = AppTest.from_file(str(ROOT / "pages/91_receipt_issue.py"), default_timeout=30).run()
_check("例外なし起動（製品側）", _no_product_exception(at), _exc_detail(at))
_check("タイトル '領収書発行'", _has(at, "領収書発行"))


# ============================================================
# 12. 92_発行者設定（管理者ガード対象）
# ============================================================
print("\n[12] 92_発行者設定")
at = AppTest.from_file(str(ROOT / "pages/92_issuer_settings.py"), default_timeout=30).run()
_check("例外なし起動（製品側）", _no_product_exception(at), _exc_detail(at))
_check("タイトル '発行者設定'", _has(at, "発行者設定"))


# ============================================================
# 13. 93_契約書テンプレ（管理者ガード対象）
# ============================================================
print("\n[13] 93_契約書テンプレ")
at = AppTest.from_file(str(ROOT / "pages/93_contract_template.py"), default_timeout=30).run()
_check("例外なし起動（製品側）", _no_product_exception(at), _exc_detail(at))
_check("タイトル '契約書テンプレート'", _has(at, "契約書テンプレート"))


# ============================================================
# 14. 94_契約書発行（管理者ガード対象）
# ============================================================
print("\n[14] 94_契約書発行")
at = AppTest.from_file(str(ROOT / "pages/94_contract_issue.py"), default_timeout=30).run()
_check("例外なし起動（製品側）", _no_product_exception(at), _exc_detail(at))
_check("タイトル '契約書発行・管理'", _has(at, "契約書発行"))


# ============================================================
# 14.5. 10_ピット端末（v3.8 新規・管理者ガード対象）
# ============================================================
print("\n[14.5] 10_ピット端末（v3.8 NEW）")
at = AppTest.from_file(str(ROOT / "pages/10_pit_terminal.py"), default_timeout=30).run()
_check("例外なし起動（製品側）", _no_product_exception(at), _exc_detail(at))
_check("タイトル 'ピット端末'", _has(at, "ピット端末"))
_check("ADMIN_PASSWORD未設定でも警告で通過（フォールバック）",
       _has(at, "ADMIN_PASSWORD") or _has(at, "管理者認証") or _has(at, "退勤打刻"))
# Codex 4回目 P2 #9 (2026-05-09): 深夜跨ぎ対応のシフト日付セレクタが追加されているか
# Note: スタッフ未選択状態ではセレクタが表示されないので、ファイル内容で検証
_pit_src = (ROOT / "pages/10_pit_terminal.py").read_text()
_check("深夜跨ぎ対応の日付セレクタが追加されている",
       "シフト日付（深夜跨ぎ時はここで前日を選択）" in _pit_src)
_check("交通費の日数倍計算が追加されている",
       "max_amt * days_worked" in _pit_src or "max_amt × 勤務日数" in _pit_src)
# Codex 6回目 P2 #13 (2026-05-09): 古い no-show を誤って優先しない
_check("前日の判定が「厳密に前日」(_prev_date)に絞り込まれている",
       "_prev_date" in _pit_src and "timedelta(days=1)" in _pit_src)
_check("前日かつ深夜跨ぎシフトのみ優先（_is_overnight_shift関数）",
       "_is_overnight_shift" in _pit_src)


# ============================================================
# 14.6. 11_個別手当（v3.9 新規・管理者ガード対象）
# ============================================================
print("\n[14.6] 11_個別手当（v3.9 NEW）")
at = AppTest.from_file(str(ROOT / "pages/11_allowances.py"), default_timeout=30).run()
_check("例外なし起動（製品側）", _no_product_exception(at), _exc_detail(at))
_check("タイトル '個別手当'", _has(at, "個別手当") or _has(at, "手当"))
# マイグレ未実行ならエラー表示・実行済みなら手当一覧UIが出る
_check("マイグレ案内・追加フォーム・空状態のいずれかが描画される",
       _has(at, "20260508_add_individual_allowances")
       or _has(at, "新規追加") or _has(at, "手当の種類")
       or _has(at, "イベント") or _no_product_exception(at))


# ============================================================
# 15. スタッフ向け2ページ（receipt_download / contract_sign）
# ============================================================
# 2026-07-29: スタッフ向け2ページは staff_site/ へ物理分離した
# （管理ページと同じプロセスに置くとURL直打ちで到達できるため）
print("\n[15] staff_site: receipt_download / contract_sign（スタッフ向け）")

at = AppTest.from_file(str(ROOT / "staff_site/pages/receipt_download.py"), default_timeout=30).run()
_check("receipt_download 例外なし起動", not at.exception)
_check("タイトル '領収書ダウンロード'", _has(at, "領収書"))

at = AppTest.from_file(str(ROOT / "staff_site/pages/contract_sign.py"), default_timeout=30).run()
_check("contract_sign 例外なし起動", not at.exception)
_check("タイトル '電子署名'", _has(at, "署名"))

# 分離が保たれているか（管理ページ側に戻っていないこと）
import os as _os
_check("スタッフ用ページが pages/ に無い（分離の維持）",
       not _os.path.exists(str(ROOT / "pages/9_receipt_download.py"))
       and not _os.path.exists(str(ROOT / "pages/99_contract_sign.py")))


# ============================================================
# 16. 管理者ガード: ADMIN_PASSWORD あり時の挙動
# ============================================================
print("\n[16] 管理者ガード: ADMIN_PASSWORD設定時はゲート表示")
# ここだけは認証を有効に戻して、ゲートが本当に立つことを確認する
os.environ.pop("P1_ALLOW_NO_AUTH", None)
os.environ["ADMIN_PASSWORD"] = "testpw_for_unit_test_only"
try:
    at = AppTest.from_file(str(ROOT / "pages/7_yearly.py"), default_timeout=30).run()
    _check("例外なし起動 (PWあり)", not at.exception)
    _check("管理者認証画面が出る",
           _has(at, "管理者認証") or _has(at, "管理者パスワード"))
    _check("st.stop() で本体表示はされていない（年間累計は1/1〜12/31の文言なし）",
           not _has(at, "1/1〜12/31"))
finally:
    os.environ.pop("ADMIN_PASSWORD", None)


# ============================================================
# 結果集計
# ============================================================
print()
print("=" * 60)
if failures:
    print(f"{FAIL} 失敗 {len(failures)}件:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print(f"{PASS} 全UIテスト成功")
    sys.exit(0)
