"""架空大会データ生成: P1 Kyoto 2026 夏大会（80名規模）

開催地: 京都府（近畿） / 2026-08-13〜2026-08-17（5日間・お盆）
スタッフ内訳:
  業務委託(contractor): 68名（うちMIX対応10名）
  タイミー(timee): 7名
  正社員(fulltime): 5名
住所分布:
  近畿(開催地): 35名
  東海: 22名
  関東: 12名
  その他（九州・四国・中国・北陸・甲信越・東北・北海道）: 11名
"""

from __future__ import annotations

import random
import csv
from pathlib import Path

random.seed(20260817)  # 再現性確保

OUT_DIR = Path(__file__).parent
EVENT_NAME = "P1 Kyoto 2026 夏大会"
EVENT_DATES = [
    "2026-08-13",  # 通常日
    "2026-08-14",  # 通常日
    "2026-08-15",  # ★特別日（お盆本番）
    "2026-08-16",  # ★特別日
    "2026-08-17",  # 通常日
]
PREMIUM_DATES = {"2026-08-15", "2026-08-16"}
VENUE_PREFECTURE = "京都府"

# 住所サンプル（地域分布用）
ADDRESSES = {
    "近畿": [
        ("京都府京都市下京区烏丸通", "京都駅"),
        ("京都府京都市中京区河原町", "京都河原町駅"),
        ("大阪府大阪市北区梅田1-1", "大阪駅"),
        ("大阪府大阪市中央区難波", "難波駅"),
        ("兵庫県神戸市中央区三宮町", "三ノ宮駅"),
        ("奈良県奈良市三条町", "近鉄奈良駅"),
        ("滋賀県大津市打出浜", "大津駅"),
        ("兵庫県西宮市甲子園七番町", "甲子園駅"),
    ],
    "東海": [
        ("愛知県名古屋市中区栄3-1", "名古屋駅"),
        ("愛知県名古屋市中村区名駅1-1", "名古屋駅"),
        ("岐阜県岐阜市神田町", "岐阜駅"),
        ("三重県津市羽所町", "津駅"),
        ("静岡県静岡市葵区黒金町", "静岡駅"),
        ("愛知県豊橋市花田町", "豊橋駅"),
    ],
    "関東": [
        ("東京都千代田区大手町", "東京駅"),
        ("東京都新宿区新宿3-1", "新宿駅"),
        ("神奈川県横浜市西区高島", "横浜駅"),
        ("埼玉県さいたま市大宮区", "大宮駅"),
        ("千葉県千葉市中央区新町", "千葉駅"),
    ],
    "九州": [
        ("福岡県福岡市博多区博多駅前", "博多駅"),
        ("熊本県熊本市中央区桜町", "熊本駅"),
    ],
    "中国": [
        ("広島県広島市中区紙屋町", "広島駅"),
        ("岡山県岡山市北区駅元町", "岡山駅"),
    ],
    "四国": [
        ("香川県高松市浜ノ町", "高松駅"),
    ],
    "北陸": [
        ("石川県金沢市広岡", "金沢駅"),
        ("富山県富山市明輪町", "富山駅"),
    ],
    "甲信越": [
        ("新潟県新潟市中央区花園", "新潟駅"),
        ("長野県長野市南長野", "長野駅"),
    ],
    "東北": [
        ("宮城県仙台市青葉区中央", "仙台駅"),
    ],
    "北海道": [
        ("北海道札幌市中央区北五条西", "札幌駅"),
    ],
}

# 苗字・名前サンプル
LAST_NAMES = ["山田", "佐藤", "鈴木", "田中", "伊藤", "渡辺", "中村", "小林",
              "加藤", "吉田", "高橋", "松本", "井上", "木村", "斎藤", "清水",
              "森", "池田", "橋本", "石川"]
FIRST_NAMES_M = ["太郎", "次郎", "健", "翔", "大輔", "拓也", "直樹", "誠", "学", "亮"]
FIRST_NAMES_F = ["花子", "美咲", "舞", "あい", "さくら", "陽菜", "結衣", "優", "香", "恵"]

DEALER_NAMES = [
    "EveKat", "久遠", "FUKA", "とも", "しゃる", "ゆずは", "honoka", "なぴ",
    "まふ", "なつき", "真冬", "さと", "zotti", "miyu", "ながお", "るな",
    "ゆに", "toko", "もと", "さくと", "かずま", "ぺそ", "うた", "ノア",
    "さく", "こたろう", "酔拳", "のこ", "のん", "るい", "kimi", "うい",
    "まお", "フロイト", "みわ", "まい", "ゆる", "たいき", "なおと", "コウヘイ",
    "しのもち", "ありす", "あつや", "なな", "すけ", "xion", "ゆうな", "ぱる",
    "けーた", "りょう", "こつ", "KENT", "かず", "みさき", "らむ", "なえ",
    "mizuno", "ぜの", "そよぎ", "ゆか", "あおい", "りっか", "Rento", "しゅん",
    "ベル", "ハル", "マサ", "ユウ", "リオ", "カナ", "アキラ", "タケシ",
    "サラ", "ジュン", "タイキ", "ダイキ", "ケント", "ソウタ", "レン", "ノブ",
]

assert len(DEALER_NAMES) >= 80, f"ディーラーネーム不足: {len(DEALER_NAMES)}"

# 役職割り当て
ROLE_DISTRIBUTION = (
    ["TD"] * 2 +          # 2名
    ["Floor"] * 12 +      # 12名
    ["DC"] * 3 +          # 3名
    ["Chip"] * 3 +        # 3名
    ["Dealer"] * 60       # 60名
)
assert len(ROLE_DISTRIBUTION) == 80

# 雇用区分の割り当て（5名タイミー + 5名正社員 + 70名業務委託）
EMPLOYMENT_DISTRIBUTION = (
    ["fulltime"] * 5 +
    ["timee"] * 7 +
    ["contractor"] * 68
)
assert len(EMPLOYMENT_DISTRIBUTION) == 80

# 地域分布（合計80名）
REGION_DISTRIBUTION = (
    ["近畿"] * 35 +
    ["東海"] * 22 +
    ["関東"] * 12 +
    ["九州"] * 3 +
    ["中国"] * 2 +
    ["四国"] * 1 +
    ["北陸"] * 2 +
    ["甲信越"] * 2 +
    ["東北"] * 1 +
    ["北海道"] * 0  # 北海道は1回ありにして合計80
)
# 調整
if sum(1 for _ in REGION_DISTRIBUTION) != 80:
    REGION_DISTRIBUTION = (
        ["近畿"] * 35 + ["東海"] * 22 + ["関東"] * 12 +
        ["九州"] * 3 + ["中国"] * 2 + ["四国"] * 1 +
        ["北陸"] * 2 + ["甲信越"] * 2 + ["東北"] * 1
    )
    if len(REGION_DISTRIBUTION) < 80:
        REGION_DISTRIBUTION += ["近畿"] * (80 - len(REGION_DISTRIBUTION))
assert len(REGION_DISTRIBUTION) == 80

# ランダム化
random.shuffle(ROLE_DISTRIBUTION)
random.shuffle(EMPLOYMENT_DISTRIBUTION)
random.shuffle(REGION_DISTRIBUTION)


def gen_real_name() -> str:
    sex = random.choice(["M", "F"])
    last = random.choice(LAST_NAMES)
    first = random.choice(FIRST_NAMES_M if sex == "M" else FIRST_NAMES_F)
    return f"{last}{first}"


def gen_phone() -> str:
    return f"090-{random.randint(1000,9999):04d}-{random.randint(1000,9999):04d}"


def gen_email(real_name: str, i: int) -> str:
    # ローマ字変換せず、適当なメール
    return f"p1staff_{i:03d}@example.com"


# スタッフ生成
staff_rows: list[dict] = []
used_nos: set[int] = set()
for i in range(80):
    name_jp = DEALER_NAMES[i]
    role = ROLE_DISTRIBUTION[i]
    emp_type = EMPLOYMENT_DISTRIBUTION[i]
    region = REGION_DISTRIBUTION[i]

    # 住所・最寄り駅
    addr_choices = ADDRESSES.get(region, ADDRESSES["近畿"])
    addr, station = random.choice(addr_choices)
    # 番地を付けて同じ住所の重複を避ける
    addr_detail = f"{addr}{random.randint(1,99)}-{random.randint(1,99)}"

    # NO. (100から)
    no = 100 + i
    while no in used_nos:
        no += 1
    used_nos.add(no)

    # 個別時給（タイミーのみ）
    custom_rate = None
    if emp_type == "timee":
        custom_rate = random.choice([1500, 1800, 2000, 2200])

    row = {
        "no": no,
        "name_jp": name_jp,
        "name_en": name_jp.upper() if name_jp.isascii() else f"P{no}",
        "real_name": gen_real_name(),
        "address": addr_detail,
        "email": gen_email("", no),
        "nearest_station": station,
        "contact": f"LINE_{no}",
        "role": role,
        "employment_type": emp_type,
        "custom_hourly_rate": custom_rate if custom_rate else "",
        "notes": "MIX対応" if role == "Dealer" and random.random() < 0.15 else "",
    }
    staff_rows.append(row)

# CSV出力
staff_csv = OUT_DIR / "01_staff_master.csv"
fieldnames = list(staff_rows[0].keys())
with staff_csv.open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(staff_rows)
print(f"スタッフマスタCSV: {staff_csv}")
print(f"  合計: {len(staff_rows)}名")
for emp in ["contractor", "timee", "fulltime"]:
    cnt = sum(1 for r in staff_rows if r["employment_type"] == emp)
    print(f"  {emp}: {cnt}名")
for region in ["近畿", "東海", "関東", "九州", "中国", "四国", "北陸", "甲信越", "東北"]:
    cnt = sum(1 for r in staff_rows if any(
        region in addr for addr, _ in ADDRESSES.get(region, [])
        if r["address"].startswith(addr[:6])
    ))

# シフトCSV生成
# 各スタッフが5日間のうち3〜5日稼働
shift_header = ["", "", "NO.", "名前", "NAME"] + [
    f"{d.split('-')[1]}/{d.split('-')[2]}" for d in EVENT_DATES
]

# A列=役職、C列=NO、D列=名前、E列=英名、F列〜=日付
shift_rows = []
for row in staff_rows:
    role = row["role"]
    shift_cells = []
    for date in EVENT_DATES:
        # 稼働確率85%
        if random.random() < 0.85:
            # 役職別の時間帯
            if role == "TD":
                start = random.choice([10, 11, 12])
                end = random.choice([23, 24, 25])
            elif role == "Floor":
                start = random.choice([9, 10, 11])
                end = random.choice([22, 23, 24])
            elif role == "DC":
                start = 8
                end = 24
            elif role == "Chip":
                start = 8
                end = random.choice([22, 24])
            else:  # Dealer
                start = random.choice([10, 11, 13, 14, 16, 17])
                end = start + random.randint(6, 10)
                end = min(end, 26)
            start_str = f"{start:02d}:00"
            end_str = f"{end}:00" if end < 24 else f"{end}:00"  # 25, 26表記OK
            shift_cells.append(f"{start_str}~{end_str}")
        else:
            shift_cells.append("×")
    shift_rows.append({
        "role": role,
        "_blank": "",
        "no": row["no"],
        "name_jp": row["name_jp"],
        "name_en": row["name_en"],
        **{f"shift_{i}": cell for i, cell in enumerate(shift_cells)},
    })

# シフトCSV（シフト取込ページが期待する形式）
shift_csv = OUT_DIR / "02_shift_kyoto.csv"
with shift_csv.open("w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    # ヘッダー（5行目の日付行に合わせる）
    header = ["役職", "空", "NO.", "名前", "NAME"] + [
        f"{d.split('-')[1]}/{d.split('-')[2]}" for d in EVENT_DATES
    ]
    w.writerow(header)
    for row in shift_rows:
        w.writerow([
            row["role"], "", row["no"], row["name_jp"], row["name_en"],
            *[row[f"shift_{i}"] for i in range(len(EVENT_DATES))]
        ])
print(f"\nシフトCSV: {shift_csv}")
print(f"  日数: {len(EVENT_DATES)}日")
total_shifts = sum(1 for r in shift_rows for i in range(len(EVENT_DATES))
                    if r[f"shift_{i}"] != "×")
print(f"  総シフト数（稼働日延べ）: {total_shifts}件")

# イベント・レート設定もJSONで保存
import json
event_config = {
    "name": EVENT_NAME,
    "venue": "京都劇場",
    "venue_prefecture": VENUE_PREFECTURE,
    "start_date": EVENT_DATES[0],
    "end_date": EVENT_DATES[-1],
    "dates": EVENT_DATES,
    "rates": {
        d: {
            "hourly": 1600 if d in PREMIUM_DATES else 1500,
            "night": 2000 if d in PREMIUM_DATES else 1875,
            "transport": 1000,
            "floor_bonus": 5000 if d in PREMIUM_DATES else 3000,
            "mix_bonus": 1500,
            "date_label": "premium" if d in PREMIUM_DATES else "regular",
        }
        for d in EVENT_DATES
    },
    "transport_rules": [
        {"region": "近畿", "max_amount": 1000, "receipt_required": 0, "is_venue_region": 1, "note": "開催地・一律支給"},
        {"region": "東海", "max_amount": 8000, "receipt_required": 1, "is_venue_region": 0, "note": ""},
        {"region": "関東", "max_amount": 15000, "receipt_required": 1, "is_venue_region": 0, "note": ""},
        {"region": "北陸", "max_amount": 10000, "receipt_required": 1, "is_venue_region": 0, "note": ""},
        {"region": "甲信越", "max_amount": 12000, "receipt_required": 1, "is_venue_region": 0, "note": ""},
        {"region": "中国", "max_amount": 10000, "receipt_required": 1, "is_venue_region": 0, "note": ""},
        {"region": "四国", "max_amount": 12000, "receipt_required": 1, "is_venue_region": 0, "note": ""},
        {"region": "九州", "max_amount": 20000, "receipt_required": 1, "is_venue_region": 0, "note": ""},
        {"region": "東北", "max_amount": 20000, "receipt_required": 1, "is_venue_region": 0, "note": ""},
        {"region": "北海道", "max_amount": 25000, "receipt_required": 1, "is_venue_region": 0, "note": ""},
        {"region": "沖縄", "max_amount": 25000, "receipt_required": 1, "is_venue_region": 0, "note": ""},
    ],
}
with (OUT_DIR / "03_event_config.json").open("w", encoding="utf-8") as f:
    json.dump(event_config, f, ensure_ascii=False, indent=2)
print(f"\nイベント設定: {OUT_DIR / '03_event_config.json'}")
print("\n--- データ生成完了 ---")
