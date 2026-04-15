"""P1 Staff Manager — 支払い計算エンジン v2"""

from dataclasses import dataclass
from typing import Optional


NIGHT_START_HOUR = 22  # 深夜割増の開始時刻


@dataclass(frozen=True)
class ShiftHours:
    """シフトの時間分解"""
    total_minutes: int
    regular_minutes: int
    night_minutes: int
    break_minutes: int
    date: str
    start_time: str
    end_time: str


@dataclass(frozen=True)
class DailyPay:
    """1日分の支払い内訳"""
    date: str
    regular_hours: float
    night_hours: float
    break_hours: float
    base_pay: int
    night_pay: int
    break_deduction: int
    transport: int
    floor_bonus: int
    mix_bonus: int
    daily_total: int


@dataclass(frozen=True)
class StaffPayment:
    """スタッフ1人の支払い合計"""
    staff_id: int
    name: str
    role: str
    days_worked: int
    total_regular_hours: float
    total_night_hours: float
    base_pay: int
    night_pay: int
    break_deduction: int
    transport_total: int
    floor_bonus_total: int
    mix_bonus_total: int
    attendance_bonus: int
    total_amount: int
    daily_breakdown: list


def parse_time_to_minutes(time_str: str) -> Optional[int]:
    """時刻文字列を0:00からの分数に変換。26:00 = 1560分"""
    if not time_str or time_str.strip() in ("", "×", "x", "X", "-"):
        return None
    clean = time_str.strip().replace("~", "~").replace("〜", "~").replace("-", "~")
    parts = clean.split(":")
    if len(parts) != 2:
        return None
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        return hours * 60 + minutes
    except ValueError:
        return None


def parse_shift_time(time_range: str) -> Optional[tuple]:
    """'13:00~23:00' → (start_minutes, end_minutes)"""
    if not time_range or time_range.strip() in ("", "×", "x", "X", "-"):
        return None
    clean = time_range.strip().replace("〜", "~").replace("－", "~").replace("-", "~")
    for sep in ["~", "~"]:
        if sep in clean:
            parts = clean.split(sep)
            if len(parts) == 2:
                start = parse_time_to_minutes(parts[0])
                end = parse_time_to_minutes(parts[1])
                if start is not None and end is not None:
                    return (start, end)
    return None


def calculate_break_minutes(total_minutes: int, break_6h: int = 45, break_8h: int = 60) -> int:
    """労働時間から休憩時間を計算

    6時間超: break_6h分（デフォルト45分）
    8時間超: break_8h分（デフォルト60分）
    """
    if total_minutes > 8 * 60:
        return break_8h
    if total_minutes > 6 * 60:
        return break_6h
    return 0


def calculate_shift_hours(start_minutes: int, end_minutes: int, date: str,
                          break_6h: int = 45, break_8h: int = 60) -> ShiftHours:
    """シフトの通常時間・深夜時間を分解（休憩控除込み）"""
    total = end_minutes - start_minutes
    if total <= 0:
        return ShiftHours(0, 0, 0, 0, date, "", "")

    break_min = calculate_break_minutes(total, break_6h, break_8h)
    working_minutes = total - break_min

    night_boundary = NIGHT_START_HOUR * 60

    if end_minutes <= night_boundary:
        regular = working_minutes
        night = 0
    elif start_minutes >= night_boundary:
        regular = 0
        night = working_minutes
    else:
        raw_regular = night_boundary - start_minutes
        raw_night = end_minutes - night_boundary
        # 休憩は通常時間から控除（深夜前に休憩を取る前提）
        regular = max(0, raw_regular - break_min)
        night = raw_night

    start_str = f"{start_minutes // 60}:{start_minutes % 60:02d}"
    end_str = f"{end_minutes // 60}:{end_minutes % 60:02d}"

    return ShiftHours(total, regular, night, break_min, date, start_str, end_str)


def calculate_daily_pay(shift_hours: ShiftHours, hourly_rate: int,
                        night_rate: int, transport: int,
                        role: str, is_mix: bool = False,
                        floor_bonus: int = 3000,
                        mix_bonus: int = 1500) -> DailyPay:
    """1日分の支払いを計算"""
    regular_hours = shift_hours.regular_minutes / 60
    night_hours = shift_hours.night_minutes / 60
    break_hours = shift_hours.break_minutes / 60

    base = round(regular_hours * hourly_rate)
    night = round(night_hours * night_rate)
    break_ded = round(break_hours * hourly_rate)

    f_bonus = floor_bonus if role == "Floor" else 0
    # MIX手当: シフト単位のis_mixフラグで判定（役職ではなく日別）
    m_bonus = mix_bonus if is_mix else 0

    daily_total = base + night + transport + f_bonus + m_bonus

    return DailyPay(
        date=shift_hours.date,
        regular_hours=round(regular_hours, 2),
        night_hours=round(night_hours, 2),
        break_hours=round(break_hours, 2),
        base_pay=base,
        night_pay=night,
        break_deduction=break_ded,
        transport=transport,
        floor_bonus=f_bonus,
        mix_bonus=m_bonus,
        daily_total=daily_total,
    )


def calculate_attendance_bonus(days_worked: int, total_event_days: int) -> int:
    """精勤手当を計算"""
    if days_worked <= 0:
        return 0
    if days_worked >= total_event_days:
        return 10000
    if total_event_days <= 3:
        if days_worked >= (total_event_days * 2 // 3):
            return 6000
        return 0
    if days_worked >= 4:
        return 6000
    return 0


def calculate_staff_payment(
    staff_id: int,
    name: str,
    role: str,
    shifts: list,
    rates_by_date: dict,
    total_event_days: int,
    break_6h: int = 45,
    break_8h: int = 60,
    employment_type: str = "contractor",
    custom_hourly_rate: Optional[int] = None,
) -> StaffPayment:
    """スタッフ1人の全日程支払いを計算

    Args:
        shifts: [{"date": "2025-12-29", "start": "13:00", "end": "23:00", "is_mix": False}, ...]
        rates_by_date: {"2025-12-29": {"hourly": 1500, ...}, ...}
        break_6h: 6h超の休憩時間（分）
        break_8h: 8h超の休憩時間（分）
        employment_type: "contractor"(業務委託) / "timee"(タイミー) / "fulltime"(正社員)
        custom_hourly_rate: タイミー等の個別時給。指定時は通常時給を上書き

    タイミー:
        - 個別時給を使用（深夜も同一時給で計算。割増・手当なし）
        - 交通費は支給、フロア/MIX/精勤は対象外
    業務委託・正社員:
        - 通常の計算（時給×時間+深夜+手当+精勤）
    """
    daily_results = []
    is_timee = employment_type == "timee"

    for shift in shifts:
        time_range = f"{shift['start']}~{shift['end']}"
        parsed = parse_shift_time(time_range)
        if not parsed:
            continue

        start_min, end_min = parsed
        shift_hours = calculate_shift_hours(start_min, end_min, shift["date"],
                                            break_6h, break_8h)

        rate = rates_by_date.get(shift["date"], {})
        is_mix = shift.get("is_mix", False)

        if is_timee and custom_hourly_rate:
            # タイミー: 個別時給で計算。深夜割増/手当なし
            daily = calculate_daily_pay(
                shift_hours,
                hourly_rate=custom_hourly_rate,
                night_rate=custom_hourly_rate,  # 深夜も同じ時給
                transport=rate.get("transport", 1000),
                role="Timee",  # フロア手当対象外にする
                is_mix=False,  # MIX手当対象外
                floor_bonus=0,
                mix_bonus=0,
            )
        else:
            daily = calculate_daily_pay(
                shift_hours,
                hourly_rate=rate.get("hourly", 1500),
                night_rate=rate.get("night", 1875),
                transport=rate.get("transport", 1000),
                role=role,
                is_mix=is_mix,
                floor_bonus=rate.get("floor_bonus", 3000),
                mix_bonus=rate.get("mix_bonus", 1500),
            )
        daily_results.append(daily)

    days_worked = len(daily_results)
    # タイミーは精勤手当対象外
    if is_timee:
        att_bonus_override = 0
    else:
        att_bonus_override = None
    total_regular = sum(d.regular_hours for d in daily_results)
    total_night = sum(d.night_hours for d in daily_results)
    base_pay = sum(d.base_pay for d in daily_results)
    night_pay = sum(d.night_pay for d in daily_results)
    break_ded = sum(d.break_deduction for d in daily_results)
    transport_total = sum(d.transport for d in daily_results)
    floor_total = sum(d.floor_bonus for d in daily_results)
    mix_total = sum(d.mix_bonus for d in daily_results)
    att_bonus = (att_bonus_override if att_bonus_override is not None
                 else calculate_attendance_bonus(days_worked, total_event_days))

    total = base_pay + night_pay + transport_total + floor_total + mix_total + att_bonus

    return StaffPayment(
        staff_id=staff_id,
        name=name,
        role=role,
        days_worked=days_worked,
        total_regular_hours=round(total_regular, 2),
        total_night_hours=round(total_night, 2),
        base_pay=base_pay,
        night_pay=night_pay,
        break_deduction=break_ded,
        transport_total=transport_total,
        floor_bonus_total=floor_total,
        mix_bonus_total=mix_total,
        attendance_bonus=att_bonus,
        total_amount=total,
        daily_breakdown=daily_results,
    )
