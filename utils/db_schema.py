"""P1 Staff Manager — Supabase スキーマ存在チェック・ユーティリティ

マイグレーション未実行のDBでも後方互換で動作するように、
新カラムの存在を実行時に判定してクエリ組み立てに反映する。

使い方:
    from utils import db_schema

    if db_schema.has_column("p1_payments", "receipt_original_path"):
        cols += ", receipt_original_path"

判定は1回だけ実行しキャッシュする。Streamlit Cloud 側でマイグレ実行後に
アプリを再起動（Reboot app）すれば再判定される。
"""

from __future__ import annotations

from typing import Dict

import db  # type: ignore


# モジュールレベルキャッシュ（プロセス寿命内）
_SCHEMA_CACHE: Dict[str, bool] = {}


def has_column(table: str, column: str) -> bool:
    """指定テーブルに指定カラムが存在するかを返す（キャッシュあり）。

    Args:
        table: テーブル名（例 "p1_payments"）
        column: カラム名（例 "receipt_original_path"）

    Returns:
        True = 存在する、False = 存在しない or クエリ失敗

    Note:
        判定は Supabase に対して `SELECT <column> LIMIT 1` を投げ、
        例外の有無で判定する。結果はモジュール寿命キャッシュ。
        マイグレ後は Streamlit の Reboot app でキャッシュクリアされる。
    """
    key = f"{table}.{column}"
    if key in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[key]

    try:
        db.get_client().table(table).select(column).limit(1).execute()
        _SCHEMA_CACHE[key] = True
    except Exception:
        # column does not exist / auth error など全て False 扱い
        _SCHEMA_CACHE[key] = False

    return _SCHEMA_CACHE[key]


def clear_cache() -> None:
    """キャッシュを明示クリア（テストや再読み込み用）"""
    _SCHEMA_CACHE.clear()
