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

大阪開催の対象エリア（2026-08-16 中野さん確定・本文どおり）:
    近郊通勤  大阪府内、兵庫東部、京都南部、奈良北部など → 1日1,000円
    隣接      兵庫、京都、奈良、滋賀、和歌山            → 往復5,000円
    中距離    愛知、岐阜、三重、岡山、香川、徳島        → 往復15,000円
    遠方      東京、神奈川、千葉、埼玉、広島、山口、福岡など → 往復25,000円
    特別遠方  北海道、沖縄、東北北部、南九州など        → 往復30,000円

    ⚠️ 兵庫・京都・奈良は「県としては隣接」「会場寄りの一部は近郊通勤」の
    二重指定になっている。都道府県だけでは分けられないため、県は隣接に置き、
    NEAR_COMMUTE_CITIES に載せた市区町村だけを近郊通勤へ引き上げる。
    ここに載らない市（姫路・福知山・十津川など）は隣接のまま。
"""

from __future__ import annotations

# ゾーン名（表示順）
ZONE_COMMUTE = "近郊通勤"
ZONE_ADJACENT = "隣接"
ZONE_MIDDLE = "中距離"
ZONE_FAR = "遠方"
ZONE_EXTRA_FAR = "特別遠方"
# 海外招聘（台湾Dealer等）。国内の距離区分に載らないため別枠で固定支給する。
# 木村さんシート（2026-08-06）の「特別遠方（台湾固定）30,000円/人」に相当。
ZONE_OVERSEAS = "海外"
ZONES = (ZONE_COMMUTE, ZONE_ADJACENT, ZONE_MIDDLE, ZONE_FAR, ZONE_EXTRA_FAR,
         ZONE_OVERSEAS)

# ゾーン別の上限（近郊通勤だけは「1日あたりの日額」、他は往復総額の上限）
ZONE_CAPS: dict = {
    ZONE_COMMUTE: 1000,      # 円/出勤日（領収書不要）
    ZONE_ADJACENT: 5000,
    ZONE_MIDDLE: 15000,
    ZONE_FAR: 25000,
    ZONE_EXTRA_FAR: 30000,
    ZONE_OVERSEAS: 30000,    # 固定支給（領収書不要）
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
        # 2026-08-16 中野さん確定: 近郊通勤は「大阪府内、兵庫東部、京都南部、
        # 奈良北部など」。県単位では表現できないため、県としては隣接に置き、
        # 会場に近い市区町村だけを NEAR_COMMUTE_CITIES で近郊通勤へ引き上げる。
        commute=["大阪府"],
        adjacent=["兵庫県", "京都府", "奈良県", "滋賀県", "和歌山県"],
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


# ============================================================
# 県内の一部だけが「近郊通勤」になる市区町村（2026-08-16 中野さん指示）
#   大阪開催の「兵庫東部・京都南部・奈良北部」は都道府県より細かいので、
#   住所文字列に下記の市区町村名が含まれていれば隣接→近郊通勤へ引き上げる。
#   ここに無い市（姫路・福知山・十津川など）は県の区分どおり隣接のまま。
#   ⚠️ 市の線引きは運用判断。過不足があればこのリストだけ直せばよい。
# ============================================================
NEAR_COMMUTE_CITIES: dict = {
    "大阪": {
        # 兵庫東部（阪神間＋神戸市）
        "兵庫県": ["神戸市", "尼崎市", "西宮市", "芦屋市", "伊丹市",
                   "宝塚市", "川西市", "三田市", "猪名川町"],
        # 京都南部
        "京都府": ["京都市", "宇治市", "城陽市", "向日市", "長岡京市",
                   "八幡市", "京田辺市", "木津川市", "大山崎町", "久御山町",
                   "井手町", "宇治田原町", "精華町", "和束町", "笠置町",
                   "南山城村"],
        # 奈良北部
        "奈良県": ["奈良市", "大和郡山市", "天理市", "生駒市", "香芝市",
                   "大和高田市", "王寺町", "上牧町", "河合町", "三郷町",
                   "斑鳩町", "平群町", "安堵町", "川西町", "三宅町",
                   "田原本町", "広陵町"],
    },
}


def near_commute_city(venue: str, prefecture, address) -> str:
    """住所が「県内の近郊通勤エリア」に当たるならその市区町村名を返す。"""
    table = NEAR_COMMUTE_CITIES.get(venue or "", {}).get(str(prefecture or ""), [])
    addr = str(address or "")
    for city in table:
        if city in addr:
            return city
    return ""


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


def zone_for_staff(staff: dict, venue: str) -> str:
    """スタッフ1人の交通区分を決める（2026-08-16 追加）。

    順序:
      1. region が「海外」なら海外ゾーン（台湾Dealer等の固定支給）
      2. prefecture（無ければ住所から抽出）→ 会場別のゾーン表
      3. 住所が分からなければ空文字（＝ゾーン未判定。交通費は0で手入力に委ねる）

    ⚠️ 住所が無い人を勝手に「特別遠方」に寄せない。上限だけ大きくなって
    実態のない支給根拠を作るより、未判定として人が見る方が安全。
    """
    if not staff:
        return ""
    if str(staff.get("region") or "") == ZONE_OVERSEAS:
        return ZONE_OVERSEAS
    pref = staff.get("prefecture")
    if not pref:
        try:
            from utils.region import extract_prefecture
            pref = extract_prefecture(staff.get("address"))
        except Exception:
            pref = None
    if not pref:
        return ""
    zone = zone_of(venue, pref)
    # 県は隣接でも、会場に近い市区町村（兵庫東部・京都南部・奈良北部）は近郊通勤
    if zone == ZONE_ADJACENT and near_commute_city(venue, pref, staff.get("address")):
        return ZONE_COMMUTE
    return zone


def default_zone_rules(venue: str = "") -> list:
    """交通費ルール表（p1_event_transport_rules）に入れる区分別の行を返す。

    近郊通勤だけ is_venue_region=1（＝日額×出勤日数・領収書不要）。
    海外は領収書不要の固定支給なので receipt_required=0 だが日額ではない。
    """
    rows = []
    for z in ZONES:
        is_venue = 1 if z == ZONE_COMMUTE else 0
        if z == ZONE_COMMUTE:
            note = "開催地近郊（領収書不要・出勤1日あたり一律）"
        elif z == ZONE_OVERSEAS:
            note = "海外招聘（領収書不要・固定支給）"
        else:
            note = f"往復総額の上限¥{ZONE_CAPS[z]:,}（片道領収書×2で精算）"
        rows.append({
            "region": z,
            "max_amount": ZONE_CAPS[z],
            "receipt_required": 0 if z in (ZONE_COMMUTE, ZONE_OVERSEAS) else 1,
            "is_venue_region": is_venue,
            "note": note,
        })
    return rows


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
