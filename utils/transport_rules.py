"""交通費ルールの解釈を1箇所に集約する（2026-08-06 リファクタリング）

背景:
    「開催地=日額×出勤日数／遠方=往復総額の上限」という同じ解釈が
    支払い計算・ピット端末・交通費ページの3箇所に別々に書かれており、
    片方だけ直して食い違う事故が実際に起きた（2026-08-02 に総額へ統一→
    2026-08-04 に承認済み業務ルールへ再統一、の2回とも3箇所を手で揃えた）。
    式をここへ集約し、画面側は必ず本モジュールを通す。

業務ルールの出典:
    交通費統一ルール（2026-07-22 TAKA起草・木村さん基本承認）
    - 近郊通勤エリア（開催地）: 出勤1日あたり一律（領収書不要）
    - それ以外: 往復総額の上限内で実費精算（領収書必須）
"""

from __future__ import annotations


def venue_amount(per_day: int, days_worked: int) -> int:
    """開催地: 日額 × 出勤日数（欠勤日は含めない）"""
    return int(per_day or 0) * max(0, int(days_worked or 0))


def clip_to_cap(receipt_amount: int, cap: int) -> int:
    """遠方: 領収書金額を往復総額の上限で頭打ち。上限0は「上限なし」"""
    r, c = int(receipt_amount or 0), int(cap or 0)
    return min(r, c) if c > 0 else r


# 片道の領収書は往復（×2）で精算する（2026-08-16 中野さん指示）。
# 現場が持ってくるのは片道分の領収書なので、入力値を往復に換算してから
# 上限（往復総額）で頭打ちにする。往復額をそのまま入れる運用も残す。
ROUND_TRIP_MULTIPLIER = 2


def round_trip_amount(one_way_amount: int, cap: int) -> int:
    """片道額 → 往復（×2）→ 上限で頭打ち。

    Args:
        one_way_amount: 片道の領収書金額
        cap: 往復総額の上限（0=上限なし）
    """
    return clip_to_cap(int(one_way_amount or 0) * ROUND_TRIP_MULTIPLIER, cap)


def approved_amount(rule: dict, days_worked: int,
                    receipt_amount: int = 0, has_receipt: bool = False) -> tuple:
    """地域ルールから精算額を決める。

    Returns:
        (精算額, 説明文字列)
    """
    max_amt = int(rule.get("max_amount") or 0)
    if rule.get("is_venue_region"):
        return venue_amount(max_amt, days_worked), "開催地一律（日額×勤務日数）"
    if rule.get("receipt_required") and not has_receipt:
        return 0, "領収書必須・未受領"
    return clip_to_cap(receipt_amount, max_amt), "領収書ベース（上限=往復総額）"


def payment_amount(rules_by_region: dict, region, days_worked: int,
                   claim: dict = None) -> tuple:
    """**支払いに載せる**交通費を決める（ピット端末・支払い計算の共通入口）。

    2026-08-12 追加。ピット端末だけがこの判定を持っておらず、領収書が未登録の
    遠方スタッフに対して「イベントレートの日額」を素通しで加算していた
    （transport_override=None → calculator が日額×日数を積む）。結果、同じ打刻でも
    ピットの表示額が支払い計算より 1,000円/日 多くなり、8月大阪の実データで
    54名・合計 269,000円の差が出ることを実測。現場はピット表示額で現金を渡すため、
    そのまま過払いになる。

    Returns: (amount or None, reason)
        None = 交通費ルール未設定 → 旧ロジック（イベントレートの日額）に委ねる
    """
    # 手入力（領収書/承認額の登録）は地域ルールより優先する。
    # 2026-08-13: 住所未登録の受付スタッフに実費を払う手段が無かった
    # （地域なし→無条件0円で、claimを入れても無視されていた）。
    # 開催地在住者への手入力も「新幹線等の実費大は都度相談」（TAKA案7/22）の
    # 上書き経路として機能する。
    if claim and claim.get("has_receipt"):
        return int(claim.get("approved_amount") or 0), "領収書/手入力額"
    if not rules_by_region:
        return None, ""
    rule = rules_by_region.get(region)
    if not rule:
        return 0, "住所未登録または圏外のため交通費0（手入力で支給可）"
    if rule.get("is_venue_region"):
        per_day = int(rule.get("max_amount") or 0)
        return (venue_amount(per_day, days_worked),
                f"開催地一律（¥{per_day:,}/日 × {days_worked}日）")
    # 2026-08-16: 領収書不要の固定支給（海外招聘の台湾Dealer等）。
    # 従来はここへ落ちて無条件0円になり、領収書を出しようがない海外スタッフに
    # 交通費が付かなかった（木村さんシートでは「台湾固定30,000円/人」）。
    if not rule.get("receipt_required"):
        amt = int(rule.get("max_amount") or 0)
        return amt, f"領収書不要の固定支給（¥{amt:,}）"
    return 0, "領収書が未提出のため0（提出後に精算）"


def payment_amount_for_staff(rules_by_zone: dict, staff: dict, days_worked: int,
                             claim: dict = None, venue: str = "") -> tuple:
    """交通区分（近郊通勤/隣接/中距離/遠方/特別遠方/海外）で交通費を決める。

    2026-08-16 中野さん指示で導入。従来は地方名（近畿・東海・関東…）を鍵に
    上限を引いていたが、同じ地方でも会場からの距離が違う（大阪開催なら
    香川=中距離15,000／愛媛=遠方25,000、岡山=中距離／広島=遠方）ため、
    地方単位では正しい上限を表現できなかった。都道府県から会場別の
    交通区分を機械判定して引く。

    区分と上限の出典:
        木村さんシート「P1_OSAKA_SUMMER_2026_スタッフ人件費_交通費」個人別明細
        ＋ P1共通ルール（2026-08-16 中野さん確定・utils/transport_zones）
    """
    from utils import transport_zones as _tz
    zone = _tz.zone_for_staff(staff or {}, venue)
    return payment_amount(rules_by_zone, zone, days_worked, claim)
