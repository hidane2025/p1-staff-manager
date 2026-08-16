"""CI・ローカル共通のテストランナー（本番DBに書かない安全セットのみ）

背景（2026-08-13 QA第3巡）:
    CI（.github/workflows/test.yml）がテストを1本ずつ列挙しており、
    新設した回帰テスト30〜34番が未登録＝CIが素通しになっていた。
    安全セットの正をこのファイル1箇所にし、CI側はこれを呼ぶだけにする。

「安全」の基準:
    Supabase・ネットワーク・起動済みアプリに依存しない（fakeクライアント・
    AppTest・純関数のみ）。DBに書くE2E（1,2,3,5,6,7,9,10〜13番）は
    本番停止中に手動で回す運用のため、ここには絶対に足さないこと。
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).parent
SAFE = [4, 8, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 35, 36, 37, 38,
        39, 40, 41, 42]


def main() -> int:
    files = []
    for n in SAFE:
        hits = sorted(ROOT.glob(f"{n}_*.py"))
        if not hits:
            print(f"  ⚠️ {n}_*.py が見つかりません（リストの更新漏れ？）")
            return 1
        files.extend(hits)
    failed = []
    for f in files:
        r = subprocess.run([sys.executable, str(f)], capture_output=True, text=True)
        mark = "✅" if r.returncode == 0 else "❌"
        print(f"  {mark} {f.name}")
        if r.returncode != 0:
            failed.append(f.name)
            tail = (r.stdout + r.stderr).strip().splitlines()[-8:]
            for line in tail:
                print(f"      {line}")
    print(f"\n  {len(files) - len(failed)}/{len(files)} PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
