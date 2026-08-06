"""接続・監査ログなどの基盤（get_client の差し替え点はここ）（db.py から2026-08-06に機械分割・挙動不変）"""
import os
import re
import unicodedata
import streamlit as st
from datetime import datetime, timezone, timedelta
from typing import Optional
try:
    from supabase import create_client
except ImportError:
    create_client = None


# 日本時間（JST = UTC+9）で統一
_JST = timezone(timedelta(hours=9))

# Supabase接続情報（st.secretsまたは環境変数から取得）
# 本番のキーは .streamlit/secrets.toml または環境変数に設定
# デフォルトはanon公開キー（RLS有効＋allow_allポリシー）だが、機密データを扱う場合は必ず上書きすること
# 2026-07-29: 接続情報のハードコードを廃止。
# 従来は実プロジェクトのURLとanonキーを直書きし、未設定時に黙ってそこへ
# フォールバックしていたため、①公開リポジトリとイメージにキーが焼き込まれる
# ②本番で設定漏れに気づけない、という二重の問題があった。
# 現在は未設定なら明示的に失敗させる（fail closed）。
_DEFAULT_SUPABASE_URL = ""
_DEFAULT_SUPABASE_KEY = ""


def _sanitize_key(raw) -> str:
    """Secretsに貼られたキーの貼り付け事故を吸収する（2026-07-28 追加）。

    - 前後の空白・引用符を除去
    - JWT（eyJ〜）や新形式キー（sb_〜）の内部に紛れた改行・空白を除去
      （Secretsのテキストエリアで折り返し貼り付けした場合の破損対策）
    """
    s = str(raw or "").strip().strip('"').strip("'").strip()
    if s.startswith("eyJ") or s.startswith("sb_"):
        s = "".join(s.split())
    return s


def supabase_key_role(token: str):
    """キー(JWT)の role クレームを返す。JWTでない/解析不可なら None。

    旧形式キーは JWT で role=anon / service_role を持つ。新形式の不透明キー
    （sb_secret_ 等）は JWT でないため None（role判定スキップ）。
    """
    try:
        import base64
        import json as _json
        parts = (token or "").split(".")
        if len(parts) != 3:
            return None
        pad = "=" * (-len(parts[1]) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(parts[1] + pad))
        return payload.get("role")
    except Exception:
        return None


def _get_supabase_config():
    """Supabase URL/Keyを取得。

    Key優先度: SUPABASE_SERVICE_KEY > SUPABASE_SERVICE_ROLE_KEY > SUPABASE_KEY(anon)
    > 環境変数 > デフォルトanon。
    Streamlitはサーバ側で動くため service_role キーを使ってもブラウザに露出しない。
    SUPABASE_SERVICE_KEY を設定すればアプリ全体が service_role で動くので、PIIテーブルの
    anon権限を締めても壊れない。未設定時は従来どおり anon にフォールバック
    （※anon権限剥奪後はSecrets設定が必須になる）。
    """
    def _secret(name):
        try:
            return st.secrets.get(name)
        except Exception:
            return None

    url = _sanitize_key(_secret("SUPABASE_URL") or os.environ.get("SUPABASE_URL", _DEFAULT_SUPABASE_URL))
    key = _sanitize_key(
        _secret("SUPABASE_SERVICE_KEY")
        or _secret("SUPABASE_SERVICE_ROLE_KEY")
        or _secret("SUPABASE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_KEY", _DEFAULT_SUPABASE_KEY)
    )
    return url, key


def connection_health() -> dict:
    """DB接続の健全性診断（発行者設定ページの管理者向け表示・移行確認用 2026-07-28）。

    Returns: {"role": 接続キーのロール名（service_role / anon / opaque）,
              "using_default_key": bool, "select_ok": bool, "error": str}
    """
    url, key = _get_supabase_config()
    role = supabase_key_role(key) or ("opaque(sb_*)" if key.startswith("sb_") else "不明")
    # 既定キーは廃止済み（空）。空同士の比較で「既定キー使用」と誤判定しないようにする
    using_default = bool(_DEFAULT_SUPABASE_KEY) and (key == _sanitize_key(_DEFAULT_SUPABASE_KEY))
    out = {"role": role, "using_default_key": using_default, "select_ok": False,
           "ok": False, "error": ""}
    try:
        get_client().table("p1_events").select("id").limit(1).execute()
        out["select_ok"] = True
        out["ok"] = True   # 起動時セルフテストが参照するキー名（select_ok と同義）
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


@st.cache_resource
def get_client():
    """Supabaseクライアントを取得（キャッシュ）"""
    url, key = _get_supabase_config()
    return create_client(url, key)


def _now():
    """JSTの現在時刻を返す（Supabaseに保存する日時を統一）"""
    return datetime.now(_JST).strftime("%Y-%m-%d %H:%M:%S")


# === Audit Log ===

def log_action(action, target_type, target_id=None, detail="", event_id=None, performed_by="system"):
    """監査ログを記録"""
    try:
        get_client().table("p1_audit_log").insert({
            "event_id": event_id, "action": action, "target_type": target_type,
            "target_id": target_id, "detail": detail, "performed_by": performed_by
        }).execute()
    except Exception:
        pass  # ログ記録失敗はサイレント


def get_audit_log(event_id=None, limit=50):
    q = get_client().table("p1_audit_log").select("*").order("created_at", desc=True).limit(limit)
    if event_id:
        q = q.eq("event_id", event_id)
    return q.execute().data


def _flatten_staff_join(data):
    """Supabase結合結果のp1_staffが dict/list いずれでもフラット化"""
    for row in data:
        staff_info = row.pop("p1_staff", None)
        if isinstance(staff_info, list):
            staff_info = staff_info[0] if staff_info else {}
        if not isinstance(staff_info, dict):
            staff_info = {}
        row["name_jp"] = staff_info.get("name_jp", "")
        row["name_en"] = staff_info.get("name_en", "")
        row["no"] = staff_info.get("no", 0)
        row["role"] = staff_info.get("role", "Dealer")
    return data


# === 互換性のためのinit_db（何もしない） ===
def init_db():
    pass
