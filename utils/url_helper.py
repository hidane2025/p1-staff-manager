"""P1 Staff Manager — URL生成ヘルパー

スタッフ配布用URL（領収書DL・契約署名）の base host を
デプロイ環境に応じて自動取得する。

優先順位:
1. st.secrets["PUBLIC_URL"]（手動上書き用）
2. st.context.headers の Host / X-Forwarded-Host（Streamlit 1.36+）
3. ハードコードfallback
"""

from __future__ import annotations

import streamlit as st


FALLBACK_HOST = "https://hidane2025-p1-staff-manager-app-fw8ggg.streamlit.app"


def get_base_host() -> str:
    # 1) secrets override
    try:
        if hasattr(st, "secrets"):
            v = st.secrets.get("PUBLIC_URL", "")
            if v:
                return v.rstrip("/")
    except Exception:
        pass

    # 2) Streamlitのリクエストヘッダから
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

    # 3) fallback
    return FALLBACK_HOST


def receipt_download_url(token: str) -> str:
    return f"{get_base_host()}/receipt_download?token={token}"


def contract_sign_url(token: str) -> str:
    return f"{get_base_host()}/contract_sign?token={token}"
