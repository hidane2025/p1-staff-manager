"""P1共通 交通費ゾーン（会場別・往復換算・最大上限）の単体テスト — DB非依存

2026-08-16 中野さん確定のP1共通ルールを固定する。
出典: 基本ルール「住所・最寄駅を基準に合理的経路で算出し地域別上限内で実費精算」
      最大上限 往復30,000円（超過は事前承認時のみ）
      往復同一経路は「片道領収書×2」可。支給は
      (片道×2 / 地域別上限 / 30,000) のいずれか低い額。
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from utils.transport_zones import (  # noqa: E402
    MAX_CAP, ZONE_CAPS, ZONES, cap_of, settle_amount, venue_key, zone_of,
    ZONE_COMMUTE, ZONE_ADJACENT, ZONE_MIDDLE, ZONE_FAR, ZONE_EXTRA_FAR,
)

failures: list = []


def _check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + ("" if cond else f" — {detail}"))
    if not cond:
        failures.append(name)


print("[A] ゾーンと上限")
_check("5ゾーン", ZONES == (ZONE_COMMUTE, ZONE_ADJACENT, ZONE_MIDDLE,
                            ZONE_FAR, ZONE_EXTRA_FAR))
for z, c in (("近郊通勤", 1000), ("隣接", 5000), ("中距離", 15000),
             ("遠方", 25000), ("特別遠方", 30000)):
    _check(f"{z} = ¥{c:,}", cap_of(z) == c, str(cap_of(z)))
_check("最大上限 ¥30,000", MAX_CAP == 30000)
_check("特別遠方＝最大上限", ZONE_CAPS[ZONE_EXTRA_FAR] == MAX_CAP)

print("[B] 中野さん提示の計算例")
_amt, _why = settle_amount(ZONE_EXTRA_FAR, one_way_receipt=14000)
_check("片道14,000×2=28,000 → 30,000以内なので28,000", _amt == 28000, _why)
_amt, _why = settle_amount(ZONE_EXTRA_FAR, one_way_receipt=18000)
_check("片道18,000×2=36,000 → 最大上限30,000に調整", _amt == 30000, _why)

print("[C] 3つの上限のうち最も低い額")
_check("地域別上限が効く（遠方25,000 < 片道14,000×2）",
       settle_amount(ZONE_FAR, one_way_receipt=14000)[0] == 25000)
_check("実費が効く（片道5,000×2=10,000 < 中距離15,000）",
       settle_amount(ZONE_MIDDLE, one_way_receipt=5000)[0] == 10000)
_check("隣接は5,000で頭打ち",
       settle_amount(ZONE_ADJACENT, one_way_receipt=4000)[0] == 5000)
_check("往復額での入力も可（同ルール）",
       settle_amount(ZONE_MIDDLE, round_trip_receipt=12000)[0] == 12000)
_check("領収書なしは0円（要提出）",
       settle_amount(ZONE_FAR)[0] == 0)

print("[D] 近郊通勤は日額×出勤日数（領収書不要）")
_check("3日勤務 → ¥3,000", settle_amount(ZONE_COMMUTE, days_worked=3)[0] == 3000)
_check("0日 → ¥0", settle_amount(ZONE_COMMUTE, days_worked=0)[0] == 0)
_check("領収書があっても日額計算",
       settle_amount(ZONE_COMMUTE, one_way_receipt=9999, days_worked=2)[0] == 2000)

print("[E] 会場ごとに同じ県でもゾーンが変わる")
_check("兵庫: 大阪=近郊通勤 / 福岡=遠方",
       zone_of("大阪", "兵庫県") == ZONE_COMMUTE
       and zone_of("福岡", "兵庫県") == ZONE_FAR)
_check("愛知: 大阪=中距離 / 東京=中距離 / 福岡=遠方",
       zone_of("大阪", "愛知県") == ZONE_MIDDLE
       and zone_of("東京", "愛知県") == ZONE_MIDDLE
       and zone_of("福岡", "愛知県") == ZONE_FAR)
_check("福岡県: 福岡=近郊通勤 / 東京=特別遠方",
       zone_of("福岡", "福岡県") == ZONE_COMMUTE
       and zone_of("東京", "福岡県") == ZONE_EXTRA_FAR)
_check("北海道はどこでも特別遠方",
       all(zone_of(v, "北海道") == ZONE_EXTRA_FAR for v in ("大阪", "福岡", "東京")))
_check("未定義県は特別遠方に寄せる（過少支給を避ける）",
       zone_of("大阪", "青森県") == ZONE_EXTRA_FAR)
_check("会場未設定なら空文字（呼び出し側で未設定扱い）",
       zone_of("", "大阪府") == "")

print("[F] 会場キーの推定")
_check("ヒルトン大阪 → 大阪",
       venue_key({"venue": "ヒルトン大阪", "name": "P1 CIRCUIT OSAKA"}) == "大阪")
_check("UnitedLab（福岡） → 福岡",
       venue_key({"venue": "UnitedLab", "name": "P1 福岡"}) == "福岡")
_check("EBiS303（東京） → 東京",
       venue_key({"venue": "EBiS303", "name": "P1 東京"}) == "東京")
_check("都道府県からも推定", venue_key({"prefecture": "福岡県"}) == "福岡")
_check("手掛かりなしは空文字", venue_key({"venue": "未定"}) == "")

print("=" * 60)
if failures:
    print(f"❌ 失敗 {len(failures)}件")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("✅ 全テスト成功")
