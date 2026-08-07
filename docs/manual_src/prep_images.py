"""マニュアル用に画像を整える

1) content/ … サイドバーを切り落とし、本文だけにする（紙面で文字が読める大きさになる）
2) 番号付きの吹き出し（①②③）を要所の画像に描き込む
"""
from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).parent
SHOTS = HERE / "shots"
CONTENT = HERE / "content"
CONTENT.mkdir(exist_ok=True)

SIDEBAR_X = 507      # サイドバー右端（2880px幅の実測）
FONT_PATH = "/System/Library/Fonts/Helvetica.ttc"


def crop_content(name: str, top: float = 0.0, bottom: float = 1.0,
                 keep_sidebar: bool = False) -> pathlib.Path:
    im = Image.open(SHOTS / f"{name}.png")
    w, h = im.size
    x0 = 0 if keep_sidebar else SIDEBAR_X
    im2 = im.crop((x0, int(h * top), w, int(h * bottom)))
    out = CONTENT / f"{name}.png"
    im2.save(out)
    return out


def annotate(name: str, marks: list, suffix: str = "_num") -> pathlib.Path:
    """marks = [(相対x, 相対y, 番号)] 。切り出し済み画像に丸番号を描く"""
    src = CONTENT / f"{name}.png"
    im = Image.open(src).convert("RGB")
    w, h = im.size
    d = ImageDraw.Draw(im)
    r = int(min(w, h) * 0.028)
    font = ImageFont.truetype(FONT_PATH, int(r * 1.25))
    for rx, ry, num in marks:
        cx, cy = int(w * rx), int(h * ry)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(214, 48, 49),
                  outline=(255, 255, 255), width=max(3, r // 8))
        t = str(num)
        bb = d.textbbox((0, 0), t, font=font)
        d.text((cx - (bb[2] - bb[0]) / 2, cy - (bb[3] - bb[1]) / 2 - bb[1]),
               t, fill=(255, 255, 255), font=font)
    out = CONTENT / f"{name}{suffix}.png"
    im.save(out)
    return out


def main() -> None:
    # 全画面: サイドバーごと（画面の位置関係を示すため）
    crop_content("01_home", keep_sidebar=True)   # 画面全体の位置関係を示す
    crop_content("00_login", bottom=0.62)        # ログイン枠を大きく見せる

    # 本文のみ
    # スタッフ管理は氏名・住所・メールの一覧が写るため上部のみ使う
    crop_content("03_staff", bottom=0.42)
    for n in ("04_shift_import", "05_transport", "06_attendance",
              "07_pit_before_search", "08_payment", "09_envelope", "10_report",
              "11_receipt_issue", "12_contract_issue", "13_users", "14_allowances",
              "15_pit_searched", "16_payment_calculated", "17_payment_detail",
              "18_envelope_after", "19_report_after", "20_receipt_after",
              "21_payment_approved", "22_pit_checkout_form",
              "23_pit_search_clear", "24_pit_fix_form"):
        if (SHOTS / f"{n}.png").exists():
            crop_content(n)

    # 番号入り: ピット端末（検索欄の位置）
    annotate("07_pit_before_search", [(0.085, 0.678, 1), (0.375, 0.678, 2)])
    # 番号入り: 支払い計算（計算ボタン→結果）
    annotate("16_payment_calculated", [(0.075, 0.437, 1), (0.075, 0.575, 2), (0.075, 0.735, 3)])
    print("画像整形完了:", len(list(CONTENT.glob("*.png"))), "枚")


if __name__ == "__main__":
    main()
