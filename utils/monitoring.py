"""P1 Staff Manager — 監視・異常通知（2026-07-29）

背景:
    レビュー指摘「現状監視がなされていない」への対応。
    これまでは障害が起きても誰も気づかず、翌日ユーザーの申告で発覚していた。

3層で監視する:
    ①死活監視  … ホスティング側のヘルスチェック（/_stcore/health）＋自動再起動
                  → railway.json で設定。本モジュールの担当外
    ②異常検知  … アプリ内で起きた例外を捕まえてメール通知（本モジュール）
    ③不正検知  … ログイン失敗の連続をメール通知（本モジュール）

設計方針:
    - 通知が失敗しても業務は止めない（監視が原因の障害を作らない）
    - 同じ異常で通知が洪水にならないよう、内容ハッシュ＋時間窓で抑制する
    - 通知先が未設定なら黙ってログのみ（起動は妨げない）
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
import traceback
from typing import Optional

# 同一内容の通知を抑制する時間窓（秒）
_DEDUPE_WINDOW_SEC = 1800  # 30分
# プロセス全体の通知上限（暴走時のメール爆発とSMTP遮断を防ぐ）
_MAX_ALERTS_PER_HOUR = 12

_lock = threading.Lock()
_recent: dict[str, float] = {}
_sent_times: list[float] = []

_logger = logging.getLogger("p1.monitoring")


def _alert_recipient() -> str:
    """通知先メールアドレス。ALERT_EMAIL > MAIL_FROM の順で解決する。"""
    try:
        import streamlit as st
        for key in ("ALERT_EMAIL", "MAIL_FROM"):
            try:
                v = str(st.secrets.get(key, "") or "").strip()
                if v:
                    return v
            except Exception:
                pass
    except Exception:
        pass
    for key in ("ALERT_EMAIL", "MAIL_FROM"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return ""


def _should_send(key: str) -> bool:
    """重複抑制とレート制限。送ってよければ True。"""
    now = time.time()
    with _lock:
        # 時間窓を過ぎた記録を掃除
        for k, t in list(_recent.items()):
            if now - t > _DEDUPE_WINDOW_SEC:
                _recent.pop(k, None)
        _sent_times[:] = [t for t in _sent_times if now - t < 3600]

        if key in _recent:
            return False
        if len(_sent_times) >= _MAX_ALERTS_PER_HOUR:
            return False
        _recent[key] = now
        _sent_times.append(now)
        return True


def alert(subject: str, body: str, *, dedupe_key: Optional[str] = None) -> bool:
    """異常をメール通知する。失敗しても例外は投げない（監視で業務を止めない）。

    Returns:
        実際に送信したら True。抑制・未設定・失敗なら False。
    """
    key = dedupe_key or hashlib.sha256(f"{subject}\n{body}".encode()).hexdigest()[:16]
    if not _should_send(key):
        return False

    to_addr = _alert_recipient()
    if not to_addr:
        _logger.warning("[監視] 通知先未設定のため送信しません: %s", subject)
        return False

    try:
        from utils import mailer
        if not mailer.mail_enabled():
            _logger.warning("[監視] メール未設定のため送信しません: %s", subject)
            return False
        ok, msg = mailer.send_mail(to_addr, f"[P1経理ツール警報] {subject}", body)
        if not ok:
            _logger.error("[監視] 通知の送信に失敗: %s", msg)
        return bool(ok)
    except Exception:
        # 通知の失敗で業務を止めない
        _logger.exception("[監視] 通知処理で例外")
        return False


# ==========================================================================
# ② 異常検知: Streamlitが握った例外を拾ってメール通知する
#     Streamlitは画面にエラーを出すと同時に logging へ ERROR を出す。
#     そこにハンドラを挿すことで、全ページの例外を1箇所で拾える
#     （各ページをtry/exceptで囲む必要がない＝付け忘れが起きない）。
# ==========================================================================
class _ExceptionAlertHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno < logging.ERROR:
                return
            exc_text = ""
            if record.exc_info:
                exc_text = "".join(traceback.format_exception(*record.exc_info))
            message = record.getMessage()

            # 例外種別＋発生位置で重複判定（同じ不具合の連打を1通にまとめる）
            head = exc_text.strip().splitlines()[-1] if exc_text else message
            key = hashlib.sha256(f"{record.name}|{head}".encode()).hexdigest()[:16]

            body = (
                "アプリ内で例外が発生しました。\n\n"
                f"■ 発生元: {record.name}\n"
                f"■ 内容: {message}\n\n"
                f"■ トレースバック\n{exc_text or '(なし)'}\n\n"
                "※同じ内容の通知は30分間まとめられます。\n"
            )
            alert("アプリ例外", body, dedupe_key=key)
        except Exception:
            # ログ処理内での例外は握りつぶす（無限ループを避ける）
            pass


_installed = False


def install() -> None:
    """例外監視を有効化する。何度呼んでも二重登録しない（Streamlitは再実行が多い）。"""
    global _installed
    if _installed:
        return
    try:
        handler = _ExceptionAlertHandler()
        handler.setLevel(logging.ERROR)
        # Streamlitのスクリプト実行で握られた例外はこのロガーに出る
        for name in ("streamlit", "streamlit.runtime.scriptrunner_utils.script_runner"):
            logging.getLogger(name).addHandler(handler)
        _installed = True
    except Exception:
        _logger.exception("[監視] 例外監視の登録に失敗")


# ==========================================================================
# ③ 不正検知: ログイン失敗の連続を通知
# ==========================================================================
_login_failures: dict[str, list[float]] = {}
_LOGIN_FAIL_THRESHOLD = 5      # 5回失敗で通知
_LOGIN_FAIL_WINDOW_SEC = 600   # 10分以内


def record_login_failure(kind: str, detail: str = "") -> None:
    """ログイン失敗を記録し、短時間に連続したら通知する。

    Args:
        kind: 失敗の種類（"管理者パスワード" / "当日運用コード" / "2要素認証" 等）
    """
    now = time.time()
    try:
        with _lock:
            hist = [t for t in _login_failures.get(kind, []) if now - t < _LOGIN_FAIL_WINDOW_SEC]
            hist.append(now)
            _login_failures[kind] = hist
            count = len(hist)
        if count >= _LOGIN_FAIL_THRESHOLD:
            alert(
                f"ログイン失敗が連続しています（{kind}）",
                f"{kind} の認証失敗が {_LOGIN_FAIL_WINDOW_SEC // 60}分以内に {count}回 発生しました。\n"
                f"{('補足: ' + detail) if detail else ''}\n\n"
                "心当たりがない場合はパスワード／当日運用コードの変更を検討してください。\n",
                dedupe_key=f"loginfail:{kind}",
            )
    except Exception:
        _logger.exception("[監視] ログイン失敗の記録で例外")


def notify_startup() -> None:
    """起動（デプロイ完了）を1度だけ通知する。デプロイの成否が黙って分かるようにする。"""
    alert(
        "アプリが起動しました",
        "P1 Staff Manager が起動しました（デプロイまたは再起動）。\n"
        "意図しない再起動が続く場合はホスティングのログを確認してください。\n",
        dedupe_key="startup",
    )
