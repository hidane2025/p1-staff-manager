"""P1 Staff Manager — メール送信ヘルパー（2026-07-10）

契約書の締結URL・領収書のDLリンクをスタッフへメール送信する。

設定（Streamlit Secrets / 環境変数。未設定なら mail_enabled()=False で機能は静かに無効化）:
    SMTP_HOST     = "smtp.gmail.com"       # 例: Gmail
    SMTP_PORT     = 587                     # 587=STARTTLS / 465=SSL
    SMTP_USER     = "xxxx@gmail.com"
    SMTP_PASSWORD = "アプリパスワード"      # Gmailは2段階認証+アプリパスワード
    MAIL_FROM     = "xxxx@gmail.com"        # 省略時 SMTP_USER
    MAIL_FROM_NAME = "株式会社P1 Entertainment"  # 省略時この既定値

送信は1通ずつ・失敗してもアプリ本体を壊さない（ok/エラー文字列を返す）。
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

import streamlit as st

DEFAULT_FROM_NAME = "株式会社P1 Entertainment"


def _conf(name: str, default: str = "") -> str:
    try:
        v = st.secrets.get(name)
    except Exception:
        v = None
    if v is None or str(v).strip() == "":
        v = os.environ.get(name, default)
    return str(v or "").strip()


def mail_enabled() -> bool:
    """SMTP設定が揃っているか（HOST/USER/PASSWORD必須）。"""
    return bool(_conf("SMTP_HOST") and _conf("SMTP_USER") and _conf("SMTP_PASSWORD"))


def send_mail(to_addr: str, subject: str, body: str) -> tuple[bool, str]:
    """テキストメールを1通送信。Returns: (成功?, エラーメッセージ)

    Secrets に MAIL_BCC が設定されていれば、全メールをそのアドレスへ
    エンベロープBCC（受信者には見えない控え送信）する。SMTP直送は
    「送信済み」フォルダに残らないため、控えはBCCで受信箱に残す方式。
    """
    if not mail_enabled():
        return False, "SMTP未設定（Secretsに SMTP_HOST/SMTP_USER/SMTP_PASSWORD を追加してください）"
    to_addr = (to_addr or "").strip()
    if not to_addr or "@" not in to_addr:
        return False, f"宛先メールアドレスが不正です: {to_addr!r}"

    host = _conf("SMTP_HOST")
    try:
        port = int(_conf("SMTP_PORT", "587"))
    except ValueError:
        port = 587
    user = _conf("SMTP_USER")
    password = _conf("SMTP_PASSWORD")
    from_addr = _conf("MAIL_FROM") or user
    from_name = _conf("MAIL_FROM_NAME") or DEFAULT_FROM_NAME

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(from_name, "utf-8")), from_addr))
    msg["To"] = to_addr

    # 控え用BCC（ヘッダには載せず、SMTPの宛先にだけ追加する）
    recipients = [to_addr]
    bcc = _conf("MAIL_BCC")
    if bcc and "@" in bcc and bcc.lower() != to_addr.lower():
        recipients.append(bcc)

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=20,
                                  context=ssl.create_default_context()) as s:
                s.login(user, password)
                s.sendmail(from_addr, recipients, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(user, password)
                s.sendmail(from_addr, recipients, msg.as_string())
        return True, ""
    except Exception as e:  # 認証失敗・接続失敗等はUI側で表示
        return False, str(e)[:300]


def mail_setup_hint() -> str:
    """未設定時にUIへ出す案内文。"""
    return (
        "📧 メール送信を使うには、Streamlit Cloud の **Settings → Secrets** に以下を追加してください：\n"
        "```toml\n"
        'SMTP_HOST = "smtp.gmail.com"\n'
        'SMTP_PORT = 587\n'
        'SMTP_USER = "送信に使うGmailアドレス"\n'
        'SMTP_PASSWORD = "Gmailのアプリパスワード"\n'
        'MAIL_FROM_NAME = "株式会社P1 Entertainment"\n'
        "```\n"
        "※Gmailの場合: Googleアカウント → セキュリティ → 2段階認証を有効化 → "
        "「アプリパスワード」を発行して SMTP_PASSWORD に貼り付け（通常のログインパスワードは不可）"
    )
