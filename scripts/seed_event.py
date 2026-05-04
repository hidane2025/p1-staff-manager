"""P1 Staff Manager — イベント一括投入CLI（汎用版）

【役割】
docs/event_templates/*.json で定義したイベント1つ分を Supabase に丸ごと投入する。
旧 seed_nagoya.py（イベント固有・データ埋め込み）の後継。

【使い方】
    cd p1-staff-manager
    .venv/bin/python scripts/seed_event.py docs/event_templates/p1_nagoya_2026_winter.json

【オプション】
    --update <event_id>   既存イベントを上書き更新（基本情報・レート・交通費）
    --dry-run             DBに書き込まずバリデーションのみ実行
    --supabase-url        環境変数 SUPABASE_URL を上書き
    --supabase-key        環境変数 SUPABASE_KEY を上書き

【認証情報】
明示指定が無ければ環境変数 SUPABASE_URL / SUPABASE_KEY を使用。
未設定時は db.py のデフォルト（プロジェクト共有 anon key）にフォールバック。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


# ============================================================
# 早めに sys.path を整え、認証情報を環境変数に流し込んでから db を import
# ============================================================
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="P1 イベント一括投入CLI")
    p.add_argument("template", help="docs/event_templates/*.json へのパス")
    p.add_argument("--update", type=int, default=None,
                   help="既存 event_id を上書き更新（指定なしは新規作成）")
    p.add_argument("--dry-run", action="store_true",
                   help="DBに書き込まずバリデーションのみ実行")
    p.add_argument("--supabase-url", default=None, help="Supabase URL を明示指定")
    p.add_argument("--supabase-key", default=None, help="Supabase KEY を明示指定")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    if args.supabase_url:
        os.environ["SUPABASE_URL"] = args.supabase_url
    if args.supabase_key:
        os.environ["SUPABASE_KEY"] = args.supabase_key

    # streamlit の cache_resource をバイパス（CLI実行用）
    try:
        import streamlit as st
        st.cache_resource = lambda f: f  # noqa: E731
    except Exception:
        pass

    from utils import event_template as etpl

    tmpl_path = Path(args.template)
    if not tmpl_path.exists():
        print(f"❌ テンプレが見つかりません: {tmpl_path}", file=sys.stderr)
        return 2

    print(f"📂 読込中: {tmpl_path}")
    tmpl = etpl.load_template(tmpl_path)

    print("🔍 検証中...")
    errs = etpl.validate_template(tmpl)
    if errs:
        print("❌ 検証エラー:", file=sys.stderr)
        for e in errs:
            print(f"   - {e}", file=sys.stderr)
        return 3

    print("✅ 検証OK")
    print(f"   イベント名: {tmpl.get('name')}")
    print(f"   会場: {tmpl.get('venue')}（{tmpl.get('venue_prefecture', '—')}）")
    print(f"   期間: {tmpl.get('start_date')} 〜 {tmpl.get('end_date')}")
    print(f"   日別レート: {len(tmpl.get('rates') or {})}日分")
    print(f"   交通費ルール: {len(tmpl.get('transport_rules') or [])}地域")

    if args.dry_run:
        print("🟡 dry-run モードのため DB 投入はスキップしました。")
        return 0

    print()
    if args.update:
        print(f"🔁 既存 event_id={args.update} を上書き更新します")
        eid = etpl.apply_template(tmpl, mode="update", event_id=args.update)
    else:
        print("➕ 新規イベントとして作成します")
        eid = etpl.apply_template(tmpl, mode="create")

    print(f"✅ 完了 event_id={eid}")
    print("   次のステップ: スタッフCSVをアップロード → シフトCSVを取込 → 支払い計算")
    return 0


if __name__ == "__main__":
    sys.exit(main())
