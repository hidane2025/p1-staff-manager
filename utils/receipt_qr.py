"""P1 Staff Manager — 領収書DL用QRコード生成ヘルパー（2026-07-06）

領収書のトークン付きDL URLをQRコード化する。
- 封筒ラベル（封筒リスト印刷モード）に埋め込む → 現金手渡しと同時に本人がスキャン
- ピット端末に大きく表示 → 退勤時にその場でスキャン

QRの中身は既存のDL URLそのもの。セキュリティ特性（トークン・有効期限・失効）は
URL運用と同一で、新しい経路は増やさない。
"""

from __future__ import annotations

import base64
from io import BytesIO

import qrcode


def qr_png_bytes(url: str, box_size: int = 7) -> bytes:
    """URLをQRコードPNG（bytes）にする。st.image用。"""
    qr = qrcode.QRCode(border=2, box_size=box_size)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_data_uri(url: str, box_size: int = 5) -> str:
    """URLをQRコードの data URI にする。印刷用HTML(<img src=...>)埋め込み用。"""
    return "data:image/png;base64," + base64.b64encode(
        qr_png_bytes(url, box_size=box_size)
    ).decode("ascii")
