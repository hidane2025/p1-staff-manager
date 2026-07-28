"""P1 Staff Manager — UI共通ヘルパー

- サイドバーからスタッフ専用ページを隠す
- リンクのクリップボードコピー
- 確認ダイアログ（session_state経由）
"""

from __future__ import annotations

import streamlit as st


# ==========================================================================
# サイドバー調整
# ==========================================================================
_HIDE_STAFF_PAGES_CSS = """
<style>
/* 2026-07-28: ページファイル名を英字化（URLの日本語を排除）したことに伴い、
   ファイル名由来の英字ラベルが出る標準ナビ全体を隠し、日本語ラベルを持つ
   クイックナビ（page_layout.render_quick_nav）に一本化する。
   スタッフ専用ページ（receipt_download / contract_sign）も併せて非表示になる。 */
[data-testid="stSidebarNav"] {
    display: none !important;
}
</style>
<script>
/* CSSが効かない描画タイミング用のフォールバック（動的再描画にも追随） */
(function(){
  const hide = () => {
    const nav = document.querySelector('[data-testid="stSidebarNav"]');
    if (nav) nav.style.display = 'none';
  };
  hide();
  const obs = new MutationObserver(hide);
  obs.observe(document.body, {childList: true, subtree: true});
})();
</script>
"""


def hide_staff_only_pages() -> None:
    """標準のページナビを隠す（日本語ラベルのクイックナビに一本化）"""
    st.markdown(_HIDE_STAFF_PAGES_CSS, unsafe_allow_html=True)


# ==========================================================================
# コピー可能リンクブロック
# ==========================================================================
def copyable_url(url: str, label: str = "") -> None:
    """クリック1つでクリップボードに入るURL表示（st.code使用・右上にコピーボタンあり）"""
    if label:
        st.caption(label)
    st.code(url, language=None)


# ==========================================================================
# 2段階確認ボタン
# ==========================================================================
def confirm_button(
    label: str,
    confirm_label: str,
    warning_message: str,
    key: str,
    on_confirm: callable,
    type: str = "primary",
) -> bool:
    """
    2段階確認ボタン。
    - 1回目クリック: 警告表示
    - 2回目クリック: on_confirm 実行
    """
    session_key = f"__confirm_{key}"
    if session_key not in st.session_state:
        st.session_state[session_key] = False

    pending = st.session_state[session_key]

    if not pending:
        if st.button(label, key=f"start_{key}", type=type):
            st.session_state[session_key] = True
            st.rerun()
        return False

    st.warning(warning_message)
    col_yes, col_no = st.columns([1, 1])
    with col_yes:
        if st.button(confirm_label, key=f"yes_{key}", type="primary"):
            on_confirm()
            st.session_state[session_key] = False
            st.rerun()
            return True
    with col_no:
        if st.button("❌ キャンセル", key=f"no_{key}"):
            st.session_state[session_key] = False
            st.rerun()
    return False


# ==========================================================================
# エラー表示（ユーザーフレンドリー）
# ==========================================================================
def friendly_error(user_message: str, technical_detail: str | None = None) -> None:
    """ユーザー向けエラー表示。技術詳細は expander に格納"""
    st.error(user_message)
    if technical_detail:
        with st.expander("🔧 技術詳細（管理者向け）"):
            st.code(technical_detail, language=None)


def missing_field_warning(
    staff_rows: list[dict],
    fields: list[str],
    warning_text: str | None = None,
) -> list[dict]:
    """指定フィールドが空のスタッフを抽出して警告表示

    Args:
        staff_rows: スタッフ行のリスト
        fields: 必須フィールド名のリスト（例: ["real_name", "address", "email"]）
        warning_text: 文書種別ごとの追加説明文（任意）。
            呼び出し側で「このまま発行するとどうなるか」を文書種別に応じて指定する。
            未指定なら汎用的な警告のみ。

    Returns:
        不完全なスタッフのリスト（呼び出し側で「それでも発行」の判定に使える）
    """
    bad = []
    label_map = {
        "real_name": "本名",
        "email": "メール",
        "address": "住所",
        "nearest_station": "最寄駅",
    }
    for s in staff_rows:
        missing = [f for f in fields if not s.get(f)]
        if missing:
            bad.append({
                "no": s.get("no", 0),
                "name_jp": s.get("name_jp", ""),
                "missing": "、".join(label_map.get(m, m) for m in missing),
            })
    if bad:
        # 共用ヘルパーのため警告本文は呼び出し側でカスタマイズできる設計（2026-05-25）。
        if warning_text:
            st.warning(
                f"⚠️ 以下の {len(bad)}名 は必須情報が未登録です。{warning_text}"
            )
        else:
            st.warning(
                f"⚠️ 以下の {len(bad)}名 は必須情報が未登録です。"
                "対応する書類への印字内容が空欄になる可能性があります。"
            )
        st.dataframe(bad, hide_index=True, use_container_width=True)
    return bad
