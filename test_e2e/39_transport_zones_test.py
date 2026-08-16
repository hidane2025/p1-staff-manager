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

from utils import transport_zones as tz  # noqa: E402
from utils.transport_zones import (  # noqa: E402
    MAX_CAP, ZONE_CAPS, ZONES, cap_of, settle_amount, venue_key, zone_of,
    ZONE_COMMUTE, ZONE_ADJACENT, ZONE_MIDDLE, ZONE_FAR, ZONE_EXTRA_FAR,
    ZONE_OVERSEAS,
)

failures: list = []


def _check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + ("" if cond else f" — {detail}"))
    if not cond:
        failures.append(name)


print("[A] ゾーンと上限")
# 2026-08-16: 海外招聘（台湾Dealer等・領収書不要の固定支給）を6つ目の区分に追加
_check("6区分", ZONES == (ZONE_COMMUTE, ZONE_ADJACENT, ZONE_MIDDLE,
                          ZONE_FAR, ZONE_EXTRA_FAR, ZONE_OVERSEAS))
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
# 2026-08-16 中野さん確定: 大阪開催の兵庫は「県としては隣接」。
# 会場寄りの市（兵庫東部）だけを住所で近郊通勤へ引き上げる（[F]で検証）。
_check("兵庫: 大阪=隣接 / 福岡=遠方",
       zone_of("大阪", "兵庫県") == ZONE_ADJACENT
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


print("[E] 交通区分ベースの上限引き（2026-08-16 木村さんシート個人別明細に準拠）")
import utils.transport_rules as _tr  # noqa: E402

RULES = {r["region"]: r for r in tz.default_zone_rules()}
for pref, want_zone, want_amt in (
        ("大阪府", "近郊通勤", 5000),   # 日額1,000×5日（領収書不要）
        ("滋賀県", "隣接", 0),          # 領収書が要る＝出るまで0
        ("愛知県", "中距離", 0),
        ("東京都", "遠方", 0),
        ("宮崎県", "特別遠方", 0)):     # 表に無い県は特別遠方へ寄せる
    st_ = {"prefecture": pref}
    got = tz.zone_for_staff(st_, "大阪")
    _check(f"{pref} → {want_zone}", got == want_zone, f"got={got}")
    amt, _w = _tr.payment_amount_for_staff(RULES, st_, 5, None, venue="大阪")
    _check(f"{pref} 領収書なしの支給額 ¥{want_amt:,}", int(amt) == want_amt, f"got={amt}")

_ov = {"region": "海外"}
_check("海外 → 海外区分", tz.zone_for_staff(_ov, "大阪") == ZONE_OVERSEAS)
_amt, _w = _tr.payment_amount_for_staff(RULES, _ov, 5, None, venue="大阪")
_check("海外は領収書不要で¥30,000固定", int(_amt) == 30000, f"got={_amt}")

# 住所が無い人を勝手に特別遠方へ寄せない（根拠なく上限だけ膨らむ事故の防止）
_check("住所なしは未判定（空文字）", tz.zone_for_staff({}, "大阪") == "")
_amt, _w = _tr.payment_amount_for_staff(RULES, {}, 5, None, venue="大阪")
_check("住所なしは0円（手入力に委ねる）", int(_amt) == 0, f"got={_amt}")

_claim = {"has_receipt": 1, "approved_amount": 9000}
_amt, _w = _tr.payment_amount_for_staff(
    RULES, {"prefecture": "愛知県"}, 5, _claim, venue="大阪")
_check("手入力額は区分ルールより優先", int(_amt) == 9000, f"got={_amt}")
_check("片道¥9,000×2は中距離の上限¥15,000で頭打ち",
       settle_amount("中距離", one_way_receipt=9000)[0] == 15000)


print("[F] 県内の一部だけ近郊通勤（兵庫東部・京都南部・奈良北部）")
# 県単位では隣接。住所の市区町村で会場寄りだけを近郊通勤へ引き上げる。
for pref, addr, want in (
        ("兵庫県", "兵庫県神戸市兵庫区新開地4-5-4", ZONE_COMMUTE),
        ("兵庫県", "兵庫県西宮市門戸西町4-25", ZONE_COMMUTE),
        ("兵庫県", "兵庫県宝塚市青葉台1-10", ZONE_COMMUTE),
        ("兵庫県", "兵庫県姫路市本町68", ZONE_ADJACENT),      # 西播磨は隣接のまま
        ("京都府", "京都府京都市伏見区日野野色町74", ZONE_COMMUTE),
        ("京都府", "京都府福知山市駅前町40", ZONE_ADJACENT),   # 京都北部は隣接
        ("奈良県", "奈良県生駒市北新町10-1", ZONE_COMMUTE),
        ("奈良県", "奈良県十津川村小原225", ZONE_ADJACENT),    # 奈良南部は隣接
        ("滋賀県", "滋賀県草津市野路東3-1-7", ZONE_ADJACENT),  # 滋賀に近郊通勤枠は無い
        ("和歌山県", "和歌山県和歌山市七番丁23", ZONE_ADJACENT)):
    got = tz.zone_for_staff({"prefecture": pref, "address": addr}, "大阪")
    _check(f"{addr[:14]}… → {want}", got == want, f"got={got}")

# 住所が県名までしか無い場合は県の区分（隣接）に落ちる＝勝手に近郊通勤へ上げない
_check("住所が県名だけなら隣接",
       tz.zone_for_staff({"prefecture": "兵庫県", "address": "兵庫県"}, "大阪")
       == ZONE_ADJACENT)
# 市区町村ルールは大阪開催だけ。福岡開催の神戸市は遠方のまま
_check("福岡開催の神戸市は遠方のまま",
       tz.zone_for_staff({"prefecture": "兵庫県", "address": "兵庫県神戸市"}, "福岡")
       == ZONE_FAR)

print("=" * 60)
if failures:
    print(f"❌ 失敗 {len(failures)}件")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("✅ 全テスト成功")
