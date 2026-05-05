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


PASS = "✅"
FAIL = "❌"
failures: list = []


def _check(name: str, cond: bool, detail: str = ""):
    mark = PASS if cond else FAIL
    print(f"  {mark} {name}")
    if not cond:
        failures.append(f"{name}: {detail}")


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
_check("例外なし起動", not at.exception)
_check("タイトル 'P1 Staff Manager' を含む",
       _has(at, "P1 Staff Manager"))
_check("バージョン v3.7 表示", _has(at, "v3.7"))
_check("ダッシュボード見出し",
       _has(at, "今日のダッシュボード"))
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
at = AppTest.from_file(str(ROOT / "pages/0_イベント設定.py"), default_timeout=30).run()
_check("例外なし起動", not at.exception)
_check("タイトル 'イベント設定'", _has(at, "イベント設定"))
_check("フローバー active=setup",
       _has(at, "STEP 1", "作る"))
tab_count = _count_tabs(at)
_check(f"3タブ構成（JSON投入/プリセット/既存編集） tabs={tab_count}",
       tab_count >= 3, f"got tab count {tab_count}")


# ============================================================
# 3. 1_スタッフ管理
# ============================================================
print("\n[3] 1_スタッフ管理")
at = AppTest.from_file(str(ROOT / "pages/1_スタッフ管理.py"), default_timeout=30).run()
_check("例外なし起動", not at.exception)
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
at = AppTest.from_file(str(ROOT / "pages/2_シフト取込.py"), default_timeout=30).run()
_check("例外なし起動", not at.exception)
_check("タイトル 'シフト取込'", _has(at, "シフト取込"))
_check("フローバー active=input/done=setup",
       _has(at, "STEP 1", "STEP 2"))


# ============================================================
# 5. 3_支払い計算
# ============================================================
print("\n[5] 3_支払い計算")
at = AppTest.from_file(str(ROOT / "pages/3_支払い計算.py"), default_timeout=30).run()
_check("例外なし起動", not at.exception)
_check("タイトル '支払い計算'", _has(at, "支払い計算"))
_check("フローバー active=calc",
       _has(at, "STEP 3", "計算"))


# ============================================================
# 6. 4_封筒リスト
# ============================================================
print("\n[6] 4_封筒リスト")
at = AppTest.from_file(str(ROOT / "pages/4_封筒リスト.py"), default_timeout=30).run()
_check("例外なし起動", not at.exception)
_check("タイトル '封筒リスト'", _has(at, "封筒リスト"))


# ============================================================
# 7. 5_出退勤
# ============================================================
print("\n[7] 5_出退勤")
at = AppTest.from_file(str(ROOT / "pages/5_出退勤.py"), default_timeout=30).run()
_check("例外なし起動", not at.exception)
_check("タイトル '出退勤'", _has(at, "出退勤"))


# ============================================================
# 8. 6_精算レポート（管理者ガード対象）
# ============================================================
print("\n[8] 6_精算レポート")
at = AppTest.from_file(str(ROOT / "pages/6_精算レポート.py"), default_timeout=30).run()
_check("例外なし起動", not at.exception)
_check("タイトル '精算レポート'", _has(at, "精算レポート"))
# ADMIN_PASSWORD未設定なら警告表示・通り抜ける（フォールバック挙動）
_check("ADMIN_PASSWORD未設定時は警告が出る（フォールバック動作）",
       _has(at, "ADMIN_PASSWORD") or _has(at, "管理者認証"))


# ============================================================
# 9. 7_年間累計（管理者ガード対象）
# ============================================================
print("\n[9] 7_年間累計")
at = AppTest.from_file(str(ROOT / "pages/7_年間累計.py"), default_timeout=30).run()
_check("例外なし起動", not at.exception)
_check("タイトル '年間累計'", _has(at, "年間累計"))


# ============================================================
# 10. 8_交通費
# ============================================================
print("\n[10] 8_交通費")
at = AppTest.from_file(str(ROOT / "pages/8_交通費.py"), default_timeout=30).run()
_check("例外なし起動", not at.exception)
_check("タイトル '交通費'", _has(at, "交通費"))


# ============================================================
# 11. 91_領収書発行（管理者ガード対象）
# ============================================================
print("\n[11] 91_領収書発行")
at = AppTest.from_file(str(ROOT / "pages/91_領収書発行.py"), default_timeout=30).run()
_check("例外なし起動", not at.exception)
_check("タイトル '領収書発行'", _has(at, "領収書発行"))


# ============================================================
# 12. 92_発行者設定（管理者ガード対象）
# ============================================================
print("\n[12] 92_発行者設定")
at = AppTest.from_file(str(ROOT / "pages/92_発行者設定.py"), default_timeout=30).run()
_check("例外なし起動", not at.exception)
_check("タイトル '発行者設定'", _has(at, "発行者設定"))


# ============================================================
# 13. 93_契約書テンプレ（管理者ガード対象）
# ============================================================
print("\n[13] 93_契約書テンプレ")
at = AppTest.from_file(str(ROOT / "pages/93_契約書テンプレ.py"), default_timeout=30).run()
_check("例外なし起動", not at.exception)
_check("タイトル '契約書テンプレート'", _has(at, "契約書テンプレート"))


# ============================================================
# 14. 94_契約書発行（管理者ガード対象）
# ============================================================
print("\n[14] 94_契約書発行")
at = AppTest.from_file(str(ROOT / "pages/94_契約書発行.py"), default_timeout=30).run()
_check("例外なし起動", not at.exception)
_check("タイトル '契約書発行・管理'", _has(at, "契約書発行"))


# ============================================================
# 15. スタッフ向け2ページ（receipt_download / contract_sign）
# ============================================================
print("\n[15] 9_receipt_download / 99_contract_sign（スタッフ向け）")

at = AppTest.from_file(str(ROOT / "pages/9_receipt_download.py"), default_timeout=30).run()
_check("9_receipt_download 例外なし起動", not at.exception)
_check("タイトル '領収書ダウンロード'", _has(at, "領収書"))

at = AppTest.from_file(str(ROOT / "pages/99_contract_sign.py"), default_timeout=30).run()
_check("99_contract_sign 例外なし起動", not at.exception)
_check("タイトル '電子署名'", _has(at, "署名"))


# ============================================================
# 16. 管理者ガード: ADMIN_PASSWORD あり時の挙動
# ============================================================
print("\n[16] 管理者ガード: ADMIN_PASSWORD設定時はゲート表示")
os.environ["ADMIN_PASSWORD"] = "testpw_for_unit_test_only"
try:
    at = AppTest.from_file(str(ROOT / "pages/7_年間累計.py"), default_timeout=30).run()
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
