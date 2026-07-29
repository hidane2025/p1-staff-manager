#!/usr/bin/env python3
"""P1 Staff Manager — 個人アカウント登録用の値を1コマンドで作る

本番（Railway）の環境変数 AUTH_USERS に貼り付ける値を生成する。
パスワードは画面に表示されず、どこにも保存されない。出力されるのは
元に戻せない変換結果（ハッシュ）だけなので、そのまま人に渡してよい。

使い方（各自が自分のPCで実行する）:
    python3 scripts/make_auth_users.py --username ito

    → パスワードを聞かれる（画面に出ない）
    → 貼り付け用の1行が表示される

複数人分をまとめる:
    python3 scripts/make_auth_users.py --merge '<既存のAUTH_USERSの値>' --username ito

⚠️ 重要:
    AUTH_USERS を設定すると、共有パスワード(ADMIN_PASSWORD)でのログインは
    無効になります。**全員分のアカウントを揃えてから**設定してください。
    1人分だけ登録すると、他の人がログインできなくなります。
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import secrets
import sys

ITERATIONS = 200_000


def make_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS
    ).hex()
    return f"pbkdf2${ITERATIONS}${salt}${digest}"


def main() -> int:
    ap = argparse.ArgumentParser(description="AUTH_USERS に貼り付ける値を作る")
    ap.add_argument("--username", required=True,
                    help="ログインID（半角英数。例: nakano, ito）")
    ap.add_argument("--role", default="admin", choices=["admin", "viewer"],
                    help="admin=全操作 / viewer=閲覧のみ（既定: admin）")
    ap.add_argument("--merge", default="",
                    help="既存の AUTH_USERS の値。指定するとそこに追記した形で出力する")
    args = ap.parse_args()

    uname = args.username.strip()
    if not uname.isascii() or not uname.replace("_", "").replace("-", "").isalnum():
        print("❌ ログインIDは半角英数字（_ - は可）にしてください。", file=sys.stderr)
        return 1

    pw = getpass.getpass(f"[{uname}] のパスワードを入力（画面には出ません）: ")
    if len(pw) < 10:
        print("❌ 10文字以上にしてください。", file=sys.stderr)
        return 1
    if pw != getpass.getpass("もう一度入力して確認: "):
        print("❌ 一致しません。", file=sys.stderr)
        return 1

    users: dict = {}
    if args.merge.strip():
        try:
            users = dict(json.loads(args.merge))
        except Exception:
            print("❌ --merge の値がJSONとして読めません。", file=sys.stderr)
            return 1

    users[uname] = {"password_hash": make_hash(pw), "role": args.role}
    del pw

    print()
    print("=" * 70)
    print("以下の1行が AUTH_USERS に設定する値です。")
    print("パスワードそのものではないので、そのまま中野さんに渡して構いません。")
    print("=" * 70)
    print()
    print(json.dumps(users, ensure_ascii=False, separators=(",", ":")))
    print()
    print(f"登録されるアカウント: {', '.join(sorted(users))}")
    print("⚠️ 全員分が揃っていることを確認してから本番に設定してください。")
    print("　（AUTH_USERS を設定すると共有パスワードでのログインは無効になります）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
