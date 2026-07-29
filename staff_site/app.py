"""P1 Staff Manager — スタッフ向け公開サイト（管理機能を一切含まない）

2026-07-29 分離の理由:
    管理画面はBasic認証の内側に置きたいが、スタッフ125名にIDとパスワードは配れない。
    そこで「スタッフがトークンURLで開く2ページだけ」を独立したアプリとして切り出し、
    こちらだけをBasic認証の外に出す。

    重要: 同一プロセスに管理ページを同居させてはいけない。
    Streamlitは pages/ 配下のファイルへURL直打ちで到達できてしまうため
    （st.navigationで登録を絞っても防げないことを2026-07-29に実測確認）、
    ディレクトリごと物理的に分離している。ここの pages/ には
    receipt_download.py と contract_sign.py の2つしか置かないこと。

    このアプリは --server.baseUrlPath=staff で起動し、
    WebSocketも静的資産も /staff/ 配下に収まる。nginxはその前置詞だけを
    Basic認証から除外すればよい（管理側の /_stcore/ は認証の内側に残る）。
"""

import streamlit as st

st.set_page_config(
    page_title="P1 Staff Manager",
    page_icon="🃏",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# 入口には業務情報を一切置かない（URLを直接踏まれても何も分からないようにする）
st.markdown(
    """
    ### P1 Staff Manager

    このページはスタッフの皆さま専用です。

    お手元のメールまたはQRコードのリンクから
    領収書のダウンロード・業務委託契約の締結を行ってください。

    リンクの有効期限が切れている場合は、担当者までご連絡ください。
    """
)
