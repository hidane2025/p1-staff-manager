"""共通イベントセレクター

全ページでセッション共有のイベント選択UIを提供。
選択はst.session_state["selected_event_id"]に保存される。
"""

from __future__ import annotations

from typing import Optional
import streamlit as st


SESSION_KEY = "selected_event_id"


def select_event(events: list[dict], label: str = "イベント",
                 required: bool = True) -> Optional[int]:
    """共通イベントセレクター

    - 初回: 最新イベントを自動選択
    - 選択はsession_stateに保存され、全ページで共有
    - 既存の選択が events に含まれていなければ最新に戻す

    Args:
        events: [{"id": 1, "name": "...", "start_date": "...", "end_date": "..."}]
        label: セレクトボックスのラベル
        required: Trueのときイベントゼロなら警告＋stop

    Returns:
        選択されたevent_id（イベントゼロならNone）
    """
    if not events:
        if required:
            st.warning("イベントがありません。シフト取込ページでイベントを作成してください。")
            st.stop()
        return None

    event_by_id = {e["id"]: e for e in events}
    current = st.session_state.get(SESSION_KEY)
    # 現在の選択が無効なら最新（先頭）にフォールバック
    if current not in event_by_id:
        current = events[0]["id"]
        st.session_state[SESSION_KEY] = current

    # 表示ラベル→ID
    options = [e["id"] for e in events]
    def _fmt(eid: int) -> str:
        e = event_by_id[eid]
        return f"{e['name']} ({e['start_date']}〜{e['end_date']})"

    try:
        idx = options.index(current)
    except ValueError:
        idx = 0

    selected = st.selectbox(label, options, index=idx, format_func=_fmt,
                             key="__event_selector__")
    st.session_state[SESSION_KEY] = selected
    return selected
