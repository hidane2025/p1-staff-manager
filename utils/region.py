"""日本の都道府県・地域区分ユーティリティ"""

from __future__ import annotations

import re
from typing import Optional

# 都道府県 → 地域
PREFECTURE_TO_REGION: dict[str, str] = {
    # 北海道・東北
    "北海道": "北海道",
    "青森県": "東北", "岩手県": "東北", "宮城県": "東北",
    "秋田県": "東北", "山形県": "東北", "福島県": "東北",
    # 関東
    "茨城県": "関東", "栃木県": "関東", "群馬県": "関東",
    "埼玉県": "関東", "千葉県": "関東", "東京都": "関東",
    "神奈川県": "関東",
    # 甲信越
    "新潟県": "甲信越", "山梨県": "甲信越", "長野県": "甲信越",
    # 北陸
    "富山県": "北陸", "石川県": "北陸", "福井県": "北陸",
    # 東海
    "岐阜県": "東海", "静岡県": "東海", "愛知県": "東海", "三重県": "東海",
    # 近畿
    "滋賀県": "近畿", "京都府": "近畿", "大阪府": "近畿",
    "兵庫県": "近畿", "奈良県": "近畿", "和歌山県": "近畿",
    # 中国
    "鳥取県": "中国", "島根県": "中国", "岡山県": "中国",
    "広島県": "中国", "山口県": "中国",
    # 四国
    "徳島県": "四国", "香川県": "四国", "愛媛県": "四国", "高知県": "四国",
    # 九州・沖縄
    "福岡県": "九州", "佐賀県": "九州", "長崎県": "九州",
    "熊本県": "九州", "大分県": "九州", "宮崎県": "九州",
    "鹿児島県": "九州", "沖縄県": "沖縄",
}

REGIONS: list[str] = [
    "北海道", "東北", "関東", "甲信越", "北陸",
    "東海", "近畿", "中国", "四国", "九州", "沖縄",
]

# 都道府県名の正規表現（最初にヒットしたものを使う）
_PREF_PATTERN = re.compile(
    r"(北海道|東京都|京都府|大阪府|"
    r"青森県|岩手県|宮城県|秋田県|山形県|福島県|茨城県|栃木県|群馬県|"
    r"埼玉県|千葉県|神奈川県|新潟県|山梨県|長野県|富山県|石川県|福井県|"
    r"岐阜県|静岡県|愛知県|三重県|滋賀県|兵庫県|奈良県|和歌山県|"
    r"鳥取県|島根県|岡山県|広島県|山口県|徳島県|香川県|愛媛県|高知県|"
    r"福岡県|佐賀県|長崎県|熊本県|大分県|宮崎県|鹿児島県|沖縄県)"
)


def extract_prefecture(address: Optional[str]) -> Optional[str]:
    """住所文字列から都道府県を抽出"""
    if not address:
        return None
    m = _PREF_PATTERN.search(address)
    return m.group(1) if m else None


def prefecture_to_region(prefecture: Optional[str]) -> Optional[str]:
    """都道府県から地域区分を返す"""
    if not prefecture:
        return None
    return PREFECTURE_TO_REGION.get(prefecture)


def address_to_region(address: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """住所から (都道府県, 地域) を抽出。両方Noneの場合もある"""
    pref = extract_prefecture(address)
    region = prefecture_to_region(pref)
    return pref, region


def default_regions_for_event(venue_prefecture: Optional[str] = None) -> list[dict]:
    """新規イベント用のデフォルト交通費ルール雛形

    開催地の都道府県を渡すと、そこを「開催地」として領収書不要設定。
    他地域は領収書必要＋上限0（手動で編集してもらう）。
    """
    venue_region = prefecture_to_region(venue_prefecture) if venue_prefecture else None
    rules = []
    for region in REGIONS:
        is_venue = (region == venue_region) if venue_region else False
        rules.append({
            "region": region,
            "max_amount": 1000 if is_venue else 0,
            "receipt_required": 0 if is_venue else 1,
            "is_venue_region": 1 if is_venue else 0,
            "note": "開催地（領収書不要・一律支給）" if is_venue else "",
        })
    return rules
