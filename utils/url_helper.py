"""P1 Staff Manager — URL生成ヘルパー

スタッフ配布用URL（領収書DL・契約署名）の base host を
デプロイ環境に応じて自動取得する。

優先順位:
1. st.secrets["PUBLIC_URL"]（手動上書き用）
2. st.context.headers の Host / X-Forwarded-Host（Streamlit 1.36+）
3. ハードコードfallback
"""

from __future__ import annotations

import os as _os
from urllib.parse import quote as _quote

import streamlit as st


# 2026-07-29: 旧Streamlit環境のURLへのフォールバックを廃止。
# 誤ったドメインのリンクをスタッフに配るより、明示的に失敗させる方が安全。
FALLBACK_HOST = ""


def get_base_host() -> str:
    # 1) secrets override
    try:
        if hasattr(st, "secrets"):
            v = st.secrets.get("PUBLIC_URL", "")
            if v:
                return v.rstrip("/")
    except Exception:
        pass

    # 1b) 環境変数（Railway等のホスティングで設定する想定）
    for _k in ("APP_BASE_URL", "PUBLIC_URL"):
        _v = (_os.environ.get(_k) or "").strip()
        if _v:
            return _v.rstrip("/")

    # 2) Streamlitのリクエストヘッダから
    #    ※Hostは利用者側が偽装しうるため、本番では上の APP_BASE_URL を設定して
    #      この経路に頼らないこと（偽装したHostでトークン付きURLを生成されると
    #      攻撃者のドメインへ誘導するリンクを作られる）。
    try:
        headers = st.context.headers  # Streamlit 1.36+
        host = (headers.get("Host")
                 or headers.get("host")
                 or headers.get("X-Forwarded-Host")
                 or headers.get("x-forwarded-host"))
        if host:
            # Streamlit Cloudは常にhttps
            return f"https://{host}".rstrip("/")
    except Exception:
        pass

    # 3) いずれも取得できない場合は、誤ったリンクを配らないよう明示的に失敗させる
    raise RuntimeError(
        "配布URLの生成元（APP_BASE_URL）が設定されていません。"
        "ホスティングの環境変数に公開URLを設定してください。"
    )


def receipt_download_url(token: str) -> str:
    return f"{get_base_host()}/staff/receipt_download?token={_quote(str(token), safe='')}"


def contract_sign_url(token: str) -> str:
    return f"{get_base_host()}/staff/contract_sign?token={_quote(str(token), safe='')}"
