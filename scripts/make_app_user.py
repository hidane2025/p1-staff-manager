#!/usr/bin/env python3
"""P1 Staff Manager — アプリユーザー（ID/PASS＋ロール）の登録スニペット生成 CLI

パスワードを pbkdf2-hmac-sha256（ソルト付き）でハッシュ化し、Streamlit Secrets
（.streamlit/secrets.toml もしくは Streamlit Cloud の Secrets）に貼り付ける
TOML スニペットを出力する。平文パスワードはどこにも保存しない。

使い方:
    python3 scripts/make_app_user.py --username nakano --role admin
    # → パスワードを安全に入力（画面に出ない）→ TOML スニペットを表示

ロール:
    admin  … 全操作（承認・支払 等）
    viewer … 閲覧のみ（各ページが roles= で許可した範囲）

出力例:
    [auth.users.nakano]
    password_hash = "pbkdf2$200000$<salt>$<hash>"
    role = "admin"

このスニペットを Secrets に追記すれば、そのユーザーでログインできる。
（複数ユーザーは [auth.users.<id>] を増やすだけ）
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

# utils.admin_guard.hash_password を共通利用（ハッシュ方式を1箇所に集約）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from utils.admin_guard import hash_password  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="アプリユーザーの Secrets スニペット生成")
    p.add_argument("--username", required=True, help="ログインID（例: nakano）")
    p.add_argument("--role", default="admin", choices=["admin", "viewer"],
                   help="ロール（既定 admin）")
    args = p.parse_args()

    username = args.username.strip()
    if not username:
        print("❌ username が空です", file=sys.stderr)
        return 1
    # TOML キーとして安全な文字に限定（引用キーにするが、" と制御文字は拒否）
    if '"' in username or any(ord(c) < 0x20 for c in username):
        print('❌ username に " や制御文字は使えません', file=sys.stderr)
        return 1

    pw1 = getpass.getpass("パスワード: ")
    pw2 = getpass.getpass("パスワード（確認）: ")
    if pw1 != pw2:
        print("❌ パスワードが一致しません", file=sys.stderr)
        return 1
    if len(pw1) < 8:
        print("❌ パスワードは8文字以上にしてください", file=sys.stderr)
        return 1

    digest = hash_password(pw1)

    # TOML テーブルキーは必ず引用する（"." や "@" を含むIDがネストや不正キーに化けるのを防ぐ）。
    print("\n# ↓ これを .streamlit/secrets.toml もしくは Streamlit Cloud の Secrets に追記")
    print(f'[auth.users."{username}"]')
    print(f'password_hash = "{digest}"')
    print(f'role = "{args.role}"')
    print("\n（複数ユーザーは [auth.users.<別ID>] を増やすだけ。平文パスワードは保存されません）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
