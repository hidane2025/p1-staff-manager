"""日本語フォントの登録（PDF埋め込み）。

IPAex ゴシック/明朝を TTF で登録し、reportlab がPDFに**サブセット埋め込み**する
（使用文字だけ同梱するためファイルは軽い）。これにより、フォントを持たない相手の
環境（ブラウザ内蔵ビューア等）でも日本語が確実に表示される。

フォントファイルが見つからない場合は、標準CIDフォント（HeiseiKakuGo/Min・非埋め込み）に
フォールバックして最低限動作する。

ライセンス: IPAフォントライセンス v1.0（埋め込み・再配布可）。assets/fonts/ にライセンス同梱。
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

# 描画側が使う登録名
FONT_GOTHIC = "IPAexGothic"
FONT_MINCHO = "IPAexMincho"

_FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_REGISTERED = False
_RESOLVED: Tuple[str, str] = (FONT_GOTHIC, FONT_MINCHO)


def ensure_jp_fonts() -> Tuple[str, str]:
    """日本語フォントを登録し、(ゴシック名, 明朝名) を返す。初回のみ登録。

    IPAex の TTF があれば埋め込みフォントを使い、無ければ CID にフォールバックする。
    返り値は「実際に登録された名前」なので、呼び出し側はこれを setFont に使うこと。
    """
    global _REGISTERED, _RESOLVED
    if _REGISTERED:
        return _RESOLVED

    gothic_path = _FONTS_DIR / "ipaexg.ttf"
    mincho_path = _FONTS_DIR / "ipaexm.ttf"
    try:
        pdfmetrics.registerFont(TTFont(FONT_GOTHIC, str(gothic_path)))
        pdfmetrics.registerFont(TTFont(FONT_MINCHO, str(mincho_path)))
        _RESOLVED = (FONT_GOTHIC, FONT_MINCHO)
    except Exception:
        # フォントファイルが無い等 → 非埋め込みCIDにフォールバック（最低限表示できる）
        pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
        pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))
        _RESOLVED = ("HeiseiKakuGo-W5", "HeiseiMin-W3")

    _REGISTERED = True
    return _RESOLVED
