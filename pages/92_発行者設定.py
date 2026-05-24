"""P1 Staff Manager — 発行者設定（領収書の宛先＝支払者情報）

2026-05-25 仕様変更（構造逆転）:
    領収書は受領者（ディーラー）が支払者（PRT等の主催者）に発行する文書。
    このページで設定するのは「領収書の宛名（御中で表示される会社名）」と
    但し書きの内容。
    発行者欄（右下）にはスタッフマスターの本名・住所・E-mailが自動で印字される。
"""

from __future__ import annotations

import streamlit as st

import db
from utils import receipt_db
from utils import event_selector


st.set_page_config(page_title="発行者設定", page_icon="🏢", layout="wide")
from utils.ui_helpers import hide_staff_only_pages
from utils.page_layout import apply_global_style, page_header
from utils.admin_guard import require_admin, admin_logout_button
apply_global_style()
hide_staff_only_pages()
require_admin(page_name="発行者設定")
admin_logout_button()

page_header(
    "🏢 発行者設定（領収書の宛先＝支払者情報）",
    "領収書PDFの宛名（「○○御中」と表示される会社名）と但し書きを設定します。"
    "領収書の発行者欄（右下）にはスタッフ本名・住所・E-mailが自動で入ります。",
)

st.info(
    "📌 **領収書の構造（2026-05-25 仕様）**\n"
    "- 領収書はディーラー（受領者）が PRT 等（支払者）に対して発行する文書です。\n"
    "- ここで設定する**会社名・住所**は領収書の**宛名**（『○○御中』）として印字されます。\n"
    "- 領収書の**発行者欄（右下）**には、スタッフマスターに登録された**本名・住所・E-mail**が"
    "自動で印字されます。スタッフ管理ページで未登録の人は領収書発行時に警告が出ます。"
)

events = db.get_all_events()
if not events:
    st.warning("イベントを先に作成してください。")
    st.stop()

event_id = event_selector.select_event(events, label="対象イベント")
if not event_id:
    st.stop()

st.divider()

cur = receipt_db.get_issuer_settings(event_id)

# Codex P2 R5 対応 (2026-05-25): legacy値 or 空値の場合に、領収書に
# 印字される実際の宛名を案内する。raw 値を上書きしないため、ユーザーは
# 必要に応じて自分で正式名称を入力できる。
_resolved_payer_for_receipt = receipt_db.resolve_payer_name(cur["issuer_name"])
if _resolved_payer_for_receipt != (cur["issuer_name"] or "").strip():
    st.info(
        f"💡 現在『{cur['issuer_name'] or '(未入力)'}』が保存されています。"
        f"このまま領収書を発行すると、宛名には自動的に"
        f"『{_resolved_payer_for_receipt}』が印字されます。"
        "正式名称や別の主催者名を使いたい場合は下のフォームで上書きしてください。"
    )

with st.form("issuer_form"):
    col1, col2 = st.columns(2)
    with col1:
        issuer_name = st.text_input(
            "宛名（支払者の会社名）*",
            value=cur["issuer_name"],
            help="例: 株式会社 PACIFIC RACING TEAM。"
            "領収書には「{この名前}  御中」として印字されます。",
        )
        issuer_address = st.text_area(
            "支払者の住所",
            value=cur["issuer_address"],
            height=70,
            help="領収書PDFには描画されません。"
            "ただし契約書テンプレートでは {{issuer_address}} として参照されるため、"
            "契約書も発行する場合は必ず正確な住所を入力してください。",
        )
        issuer_tel = st.text_input(
            "電話番号",
            value=cur["issuer_tel"],
            help="領収書PDFには描画されません。"
            "契約書テンプレートで {{issuer_tel}} を使う場合のみ参照されます。",
        )
    with col2:
        receipt_purpose = st.text_input(
            "但し書き（デフォルト）",
            value=cur["receipt_purpose"],
            help="例: ポーカー大会運営業務委託費として",
        )
        show_tax_breakdown = st.checkbox(
            "消費税額を内訳表示する",
            value=cur["show_tax_breakdown"],
            help=(
                "ONにすると領収書PDFの金額ブロックに"
                "「内 本体価格 ¥xxx」「内 消費税額 ¥xxx（10%）」の2行を追加します。"
                "インボイス制度対応時に推奨。"
            ),
        )
        issuer_seal_url = st.text_input(
            "電子印影URL（任意）",
            value=cur["issuer_seal_url"],
            help="PNG推奨。Supabase Storageの公開URL or 外部URL。"
            "通常は未使用（ディーラー個人印は持たないため）。空欄で印影なし。",
        )

    submitted = st.form_submit_button("💾 保存", type="primary")
    if submitted:
        # 2026-05-25: invoice_number は廃止。
        # DB側のカラムは残っているが、領収書には印字されない。
        receipt_db.save_issuer_settings(
            event_id,
            issuer_name=issuer_name,
            issuer_address=issuer_address,
            issuer_tel=issuer_tel,
            issuer_seal_url=issuer_seal_url,
            receipt_purpose=receipt_purpose,
            show_tax_breakdown=show_tax_breakdown,
        )
        st.success("✅ 設定を保存しました")
        st.rerun()

st.divider()
st.markdown("""
### 📝 運用メモ

- **領収書の宛名**は、ここで設定した会社名に「御中」を付けて印字されます。
- **領収書の発行者欄（右下）**は、スタッフマスターの「本名・住所・E-mail」が自動で印字されます。
  スタッフ情報の登録は『スタッフ管理』ページから行ってください。
- **インボイス番号**は仕様により領収書には印字しません（2026-05-25 中野指示）。
- **電子印影**はPNG推奨。背景透過で150×150px程度。通常はディーラー個人印を扱わないため未使用です。
- **イベント単位**で設定できます。主催者が変わる場合はイベントごとに更新してください。
- **過去に発行済みの領収書は再生成が必要**です（領収書発行ページの『強制再生成』を使ってください）。
""")
