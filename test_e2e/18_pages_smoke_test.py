"""P1 Staff Manager — Streamlit ページ起動スモークテスト

Streamlit の AppTest フレームワークで全ページを実行し、Python レベルの
例外が出ないかを確認する。フォーム送信はしないため Supabase への書き込みは発生しない。
（読込み系の get_* は実DBに当たるが、安全な参照のみ）

実行:
    cd p1-staff-manager
    .venv/bin/python test_e2e/18_pages_smoke_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest


PASS = "✅"
FAIL = "❌"


PAGES_TO_TEST = [
    ("app.py", "ホーム"),
    ("pages/0_イベント設定.py", "イベント設定（新規）"),
    ("pages/2_シフト取込.py", "シフト取込（改修済）"),
    ("pages/1_スタッフ管理.py", "スタッフ管理（既存）"),
    ("pages/3_支払い計算.py", "支払い計算（既存）"),
    ("pages/4_封筒リスト.py", "封筒リスト（既存）"),
    ("pages/7_年間累計.py", "年間累計（既存）"),
    ("pages/8_交通費.py", "交通費（既存）"),
]


failures: list = []


def _run(rel_path: str, label: str) -> bool:
    abs_path = ROOT / rel_path
    if not abs_path.exists():
        print(f"  {FAIL} {label}: ファイルなし {rel_path}")
        failures.append(f"{label}: ファイルなし {rel_path}")
        return False

    try:
        # default_timeout=30 で初回ロードを許容
        at = AppTest.from_file(str(abs_path), default_timeout=30).run()
    except Exception as e:
        print(f"  {FAIL} {label}: 起動例外 {type(e).__name__}: {e}")
        failures.append(f"{label}: 起動例外 {e}")
        return False

    if at.exception:
        excs = list(at.exception)
        print(f"  {FAIL} {label}: 実行時例外 {len(excs)}件")
        for exc in excs[:3]:
            # AppTest.exception は ElementList[Exception]
            exc_value = getattr(exc, "value", exc)
            print(f"      - {exc_value}")
        failures.append(f"{label}: 実行時例外")
        return False

    print(f"  {PASS} {label}: 例外なし起動成功")
    return True


def main() -> int:
    print("Streamlit ページ起動スモークテスト")
    print("=" * 60)
    for rel, label in PAGES_TO_TEST:
        _run(rel, label)
    print()
    print("=" * 60)
    if failures:
        print(f"{FAIL} 失敗 {len(failures)}件:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"{PASS} 全ページ例外なしで起動")
    return 0


if __name__ == "__main__":
    sys.exit(main())
