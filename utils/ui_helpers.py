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
/* スタッフ向けページ（token経由でのみ使う）をサイドバーから隠す */
section[data-testid="stSidebarNav"] ul li a[href$="/receipt_download"],
section[data-testid="stSidebarNav"] ul li a[href$="/contract_sign"] {
    display: none !important;
}
/* :has() 対応ブラウザで li 自体を隠す */
section[data-testid="stSidebarNav"] ul li:has(a[href$="/receipt_download"]),
section[data-testid="stSidebarNav"] ul li:has(a[href$="/contract_sign"]) {
    display: none !important;
}
</style>
<script>
/* :has()非対応ブラウザ用のJSフォールバック */
(function(){
  const hide = () => {
    document.querySelectorAll('section[data-testid="stSidebarNav"] ul li a').forEach(a => {
      const h = a.getAttribute('href') || '';
      if (h.endsWith('/receipt_download') || h.endsWith('/contract_sign')) {
        const li = a.closest('li');
        if (li) li.style.display = 'none';
      }
    });
  };
  hide();
  const obs = new MutationObserver(hide);
  obs.observe(document.body, {childList: true, subtree: true});
})();
</script>
"""


def hide_staff_only_pages() -> None:
    """管理者用ページでsidebarから「receipt download」「contract sign」を隠す"""
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


def missing_field_warning(staff_rows: list[dict], fields: list[str]) -> list[dict]:
    """指定フィールドが空のスタッフを抽出して警告表示
    Returns: 不完全なスタッフのリスト（呼び出し側で「それでも発行」の判定に使える）
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
        st.warning(
            f"⚠️ 以下の {len(bad)}名 は必須情報が未登録です。"
            f"このまま発行すると書類の宛名がディーラーネームになります。"
        )
        st.dataframe(bad, hide_index=True, use_container_width=True)
    return bad
