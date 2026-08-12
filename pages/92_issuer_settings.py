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
from utils.admin_guard import require_admin, admin_logout_button, operator_name
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
            help="例: 株式会社P1 Entertainment。"
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


# ============================================================
# 🎫 当日運用コード（日替わりワンタイムコード 2026-07-28 追加）
# ============================================================
st.divider()
st.subheader("🎫 当日運用コード")
st.caption(
    "大会当日、TD・給与窓口が**ピット端末・出退勤**に入るための時限コードです。"
    "有効日の**翌朝7時に自動失効**します。管理者パスワードを現場に配る必要がなくなります。"
)

from datetime import datetime as _dtn, timedelta as _tdn, timezone as _tzn
_JST_92 = _tzn(_tdn(hours=9))
_today_jst = _dtn.now(_JST_92).date()

_col_dc1, _col_dc2 = st.columns([1, 1])
with _col_dc1:
    _dc_date = st.date_input("有効日", value=_today_jst, key="day_code_date")
with _col_dc2:
    _dc_label = st.text_input("メモ（任意）", placeholder="例: 大阪DAY1", key="day_code_label")

if st.button("🎫 コードを発行", type="primary", key="issue_day_code"):
    try:
        _code = db.issue_day_code(str(_dc_date), _dc_label, created_by=operator_name())
        st.success("発行しました。**この画面でしか表示されません。** 今すぐ現場責任者に伝えてください。")
        st.markdown(
            f'<div style="font-size:44px;font-weight:800;letter-spacing:12px;'
            f'text-align:center;padding:16px;background:#F0FDF4;border:2px solid #16A34A;'
            f'border-radius:12px;">{_code}</div>',
            unsafe_allow_html=True,
        )
        st.caption(f"有効: {_dc_date} 0:00 〜 翌朝7:00（JST）／対象ページ: ピット端末・出退勤のみ")
    except Exception as _e:
        st.error("発行に失敗しました。DBマイグレーション（20260728_add_day_codes_and_totp.sql）"
                 "が未適用の可能性があります。")
        with st.expander("🔧 技術詳細"):
            st.code(str(_e), language=None)

_codes = db.list_day_codes(limit=10)
if _codes:
    st.markdown("**発行済みコード（直近10件・コード本体は表示されません）**")
    for _c in _codes:
        _cc1, _cc2 = st.columns([4, 1])
        with _cc1:
            _state = "🟢 有効" if _c.get("active") else "⚫ 失効済み"
            st.write(
                f"{_state}　有効日 {_c.get('valid_date')}　{_c.get('label') or '（メモなし）'}"
                f"　発行者: {_c.get('created_by') or '—'}"
            )
        with _cc2:
            if _c.get("active") and st.button("失効", key=f"revoke_dc_{_c['id']}"):
                db.revoke_day_code(_c["id"], performed_by=operator_name())
                st.rerun()

# ============================================================
# 🔐 2要素認証（TOTP 2026-07-28 追加）
# ============================================================
st.divider()
st.subheader("🔐 2要素認証（管理者ログイン）")
st.caption(
    "有効にすると、管理者ログインは「パスワード → 認証アプリの6桁コード」の2段階になります。"
    "Google Authenticator / 1Password / iPhone標準の「パスワード」アプリ等に対応。"
)

try:
    _totp_cfg = db.get_totp("admin")
except Exception:
    _totp_cfg = None
    st.warning("2要素認証の設定を確認できませんでした（DB接続を確認してください）。")
if _totp_cfg:
    st.success("✅ 2要素認証は**有効**です。")
    st.caption("無効化するには、現在の6桁コードを入力してください（本人確認）。")
    with st.form("__totp_disable_form__"):
        _dis_code = st.text_input("6桁コード", max_chars=6, key="totp_disable_code")
        _dis = st.form_submit_button("🔓 2要素認証を無効化")
    if _dis:
        try:
            import pyotp as _pyotp
            if _pyotp.TOTP(_totp_cfg["secret"]).verify((_dis_code or "").strip(), valid_window=1):
                db.set_totp("admin", _totp_cfg["secret"], enabled=False,
                            performed_by=operator_name())
                st.success("無効化しました。")
                st.rerun()
            else:
                st.error("❌ コードが違います")
        except Exception as _e:
            st.error(f"エラー: {str(_e)[:100]}")
    st.caption("📱 スマホを紛失した場合: Supabaseダッシュボード → p1_admin_totp テーブルの行を削除すると解除されます。")
else:
    if "totp_setup_secret" not in st.session_state:
        if st.button("🔐 2要素認証を設定する", type="primary", key="totp_setup_start"):
            import pyotp as _pyotp
            st.session_state["totp_setup_secret"] = _pyotp.random_base32()
            st.rerun()
    else:
        import pyotp as _pyotp
        _secret = st.session_state["totp_setup_secret"]
        _uri = _pyotp.totp.TOTP(_secret).provisioning_uri(
            name="admin", issuer_name="P1 Staff Manager")
        from utils.receipt_qr import qr_png_bytes as _qr_png
        _sc1, _sc2 = st.columns([1, 2])
        with _sc1:
            st.image(_qr_png(_uri, box_size=6))
        with _sc2:
            st.markdown(
                "1. 認証アプリでこのQRを読み取る\n"
                "2. アプリに表示された**6桁コード**を下に入力して有効化\n\n"
                f"（QRが読めない場合の手動入力キー: `{_secret}`）"
            )
        with st.form("__totp_enable_form__"):
            _en_code = st.text_input("6桁コード", max_chars=6, key="totp_enable_code")
            _en = st.form_submit_button("✅ 有効化", type="primary")
        if _en:
            if _pyotp.TOTP(_secret).verify((_en_code or "").strip(), valid_window=1):
                if db.set_totp("admin", _secret, enabled=True, performed_by=operator_name()):
                    st.session_state.pop("totp_setup_secret", None)
                    st.success("✅ 2要素認証を有効化しました。次回ログインから6桁コードが必要です。")
                    st.rerun()
                else:
                    st.error("保存に失敗しました（DBマイグレ未適用の可能性）。")
            else:
                st.error("❌ コードが違います。アプリの最新コードで再入力してください。")
        if st.button("キャンセル", key="totp_setup_cancel"):
            st.session_state.pop("totp_setup_secret", None)
            st.rerun()

# ============================================================
# 🩺 DB接続診断（セキュリティ移行の確認用 2026-07-28 追加）
# ============================================================
st.divider()
st.subheader("🩺 DB接続診断")
_h = db.connection_health()
_role_txt = str(_h.get("role"))
if _h.get("using_default_key"):
    st.warning(
        "⚠️ **内蔵の共有キー（anon）で接続中です。** セキュリティ移行が未完了の状態。"
        "ホスティングの環境変数に `SUPABASE_SERVICE_KEY` を設定してください。"
    )
elif _role_txt == "service_role":
    st.success("✅ service_role キー（Secrets設定）で接続中。移行完了状態です。")
else:
    st.info(f"接続キーのrole: {_role_txt}")
st.caption(
    f"接続テスト: {'✅ OK' if _h.get('select_ok') else '❌ 失敗 — ' + str(_h.get('error'))[:120]}"
)
