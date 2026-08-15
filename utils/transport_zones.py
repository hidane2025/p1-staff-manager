"""P1共通 交通費ゾーン（会場別・都道府県単位）— 2026-08-16 中野さん確定

基本ルール:
    本人確認書類の住所・最寄駅を基準に、開催会場までの合理的かつ経済的な経路で
    算出し、地域別上限内で実費精算する。最大上限は往復30,000円。
    これを超える場合は事前承認がある場合のみ精算対象。

ゾーンと上限（全会場共通）:
    近郊通勤: 出勤1日あたり一律1,000円（領収書不要）
    隣接:     往復上限 5,000円
    中距離:   往復上限15,000円
    遠方:     往復上限25,000円
    特別遠方: 往復上限30,000円（＝最大上限）

往復換算:
    往復で同一経路・同一交通手段の場合、片道領収書×2で往復分として算出可。
    支給額は「片道×2」「地域別上限」「最大上限30,000円」の**いずれか低い額**。

領収書:
    新幹線・特急・高速バス・飛行機の利用は領収書提出必須。
    無い場合は原則精算不可、または運営が確認できる最安相当額で判断する。

会場ごとの区分:
    同じ都道府県でも会場によってゾーンが変わる（例: 兵庫は大阪開催なら隣接、
    福岡開催なら遠方）。会場キーごとに都道府県→ゾーンを定義する。
    未定義の都道府県は「特別遠方」に寄せる（過少支給で揉めるより、上限側で
    受けて実費精算の判断に委ねる）。
"""

from __future__ import annotations

# ゾーン名（表示順）
ZONE_COMMUTE = "近郊通勤"
ZONE_ADJACENT = "隣接"
ZONE_MIDDLE = "中距離"
ZONE_FAR = "遠方"
ZONE_EXTRA_FAR = "特別遠方"
ZONES = (ZONE_COMMUTE, ZONE_ADJACENT, ZONE_MIDDLE, ZONE_FAR, ZONE_EXTRA_FAR)

# ゾーン別の上限（近郊通勤だけは「1日あたりの日額」、他は往復総額の上限）
ZONE_CAPS: dict = {
    ZONE_COMMUTE: 1000,      # 円/出勤日（領収書不要）
    ZONE_ADJACENT: 5000,
    ZONE_MIDDLE: 15000,
    ZONE_FAR: 25000,
    ZONE_EXTRA_FAR: 30000,
}

# 全ゾーン共通の絶対上限（事前承認がある場合のみ超過可）
MAX_CAP = 30000

# 領収書が必須になる交通手段（画面の注意書きに使う）
RECEIPT_REQUIRED_MODES = ("新幹線", "特急", "高速バス", "飛行機")


def _zone_map(commute, adjacent, middle, far) -> dict:
    """ゾーン→都道府県リストの定義から、都道府県→ゾーンの辞書を作る。
    ここに現れない県は特別遠方（呼び出し側の既定）になる。"""
    out = {}
    for zone, prefs in ((ZONE_COMMUTE, commute), (ZONE_ADJACENT, adjacent),
                        (ZONE_MIDDLE, middle), (ZONE_FAR, far)):
        for p in prefs:
            out[p] = zone
    return out


# ============================================================
# 会場別の区分（2026-08-16 中野さん指示の対象エリア例に準拠）
#   ※「兵庫東部」「京都南部」等の県内細分は都道府県単位に丸めている。
#     細かい線引きが要る人は個別に手入力で上書きする運用。
#     大阪開催の兵庫・京都・奈良は近郊通勤と隣接の両方に例示があるため、
#     支給が手厚い側（近郊通勤=日額）ではなく隣接（往復5,000）に寄せると
#     連日勤務者が不利になるので、**近郊通勤**として扱う。
# ============================================================
VENUE_ZONES: dict = {
    "大阪": _zone_map(
        commute=["大阪府", "兵庫県", "京都府", "奈良県"],
        adjacent=["滋賀県", "和歌山県"],
        middle=["愛知県", "岐阜県", "三重県", "岡山県", "香川県", "徳島県"],
        far=["東京都", "神奈川県", "千葉県", "埼玉県", "広島県", "山口県",
             "福岡県", "静岡県", "福井県", "石川県", "富山県", "鳥取県",
             "島根県", "愛媛県", "高知県", "長野県", "山梨県", "新潟県",
             "佐賀県", "長崎県", "熊本県", "大分県", "茨城県", "栃木県",
             "群馬県", "福島県"],
    ),
    "福岡": _zone_map(
        commute=["福岡県"],
        adjacent=["佐賀県", "熊本県", "大分県", "山口県"],
        middle=["長崎県", "宮崎県", "広島県", "岡山県"],
        far=["大阪府", "兵庫県", "京都府", "愛知県", "東京都", "神奈川県",
             "奈良県", "滋賀県", "和歌山県", "岐阜県", "三重県", "静岡県",
             "千葉県", "埼玉県", "島根県", "鳥取県", "香川県", "徳島県",
             "愛媛県", "高知県", "鹿児島県"],
    ),
    "東京": _zone_map(
        commute=["東京都", "神奈川県", "千葉県", "埼玉県"],
        adjacent=["茨城県", "栃木県", "群馬県", "山梨県"],
        middle=["静岡県", "長野県", "新潟県", "福島県", "愛知県"],
        far=["大阪府", "京都府", "兵庫県", "宮城県", "石川県", "富山県",
             "福井県", "岐阜県", "三重県", "奈良県", "滋賀県", "和歌山県",
             "岡山県", "広島県", "山形県"],
    ),
}


def venue_key(event: dict) -> str:
    """イベント（会場名・都道府県）から会場キーを推定する。

    見つからない場合は "大阪"（現行大会）を既定にせず None を返し、
    呼び出し側が「ゾーン未設定」として扱えるようにする。
    """
    text = " ".join(str(event.get(k) or "") for k in
                    ("venue", "name", "prefecture")) if event else ""
    for key in VENUE_ZONES:
        if key in text:
            return key
    # 会場名から拾えない場合は都道府県で判定
    pref = str((event or {}).get("prefecture") or "")
    for key, mapping in VENUE_ZONES.items():
        if mapping.get(pref) == ZONE_COMMUTE:
            return key
    return ""


def zone_of(venue: str, prefecture) -> str:
    """会場キー＋都道府県 → ゾーン名。未定義は特別遠方。"""
    mapping = VENUE_ZONES.get(venue or "")
    if not mapping:
        return ""
    return mapping.get(str(prefecture or ""), ZONE_EXTRA_FAR)


def cap_of(zone: str) -> int:
    """ゾーンの上限額（近郊通勤は日額、それ以外は往復総額）。"""
    return int(ZONE_CAPS.get(zone or "", 0))


def settle_amount(zone: str, one_way_receipt: int = 0,
                  round_trip_receipt: int = 0, days_worked: int = 0) -> tuple:
    """P1共通ルールでの精算額を返す。

    Args:
        zone: ゾーン名
        one_way_receipt: 片道の領収書額（×2して往復換算する）
        round_trip_receipt: 往復の実額（片道入力を使わない場合）
        days_worked: 出勤日数（近郊通勤の日額計算に使う）

    Returns:
        (支給額, 説明文字列)
    """
    if zone == ZONE_COMMUTE:
        amt = ZONE_CAPS[ZONE_COMMUTE] * max(0, int(days_worked or 0))
        return amt, f"近郊通勤: 1,000円 × {int(days_worked or 0)}日（領収書不要）"
    cap = min(cap_of(zone), MAX_CAP) if cap_of(zone) else MAX_CAP
    gross = (int(one_way_receipt or 0) * 2 if one_way_receipt
             else int(round_trip_receipt or 0))
    if gross <= 0:
        return 0, f"{zone or 'ゾーン未設定'}: 領収書未提出（上限¥{cap:,}）"
    amt = min(gross, cap)
    how = (f"片道¥{int(one_way_receipt):,}×2=¥{gross:,}" if one_way_receipt
           else f"往復¥{gross:,}")
    if amt < gross:
        return amt, f"{zone}: {how} → 上限¥{cap:,}に調整"
    return amt, f"{zone}: {how}（上限¥{cap:,}内）"
