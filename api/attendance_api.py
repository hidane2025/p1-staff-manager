"""P1会員アプリ（TAKAさん側）からの勤怠実績を受けるAPI（2026-08-13）

背景:
    大会当日の出退勤はTAKAさんのPIT勤怠ツールが一次入力面。そこから
    実績（実出勤・実退勤）だけを本システムへプッシュしてもらい、
    給与計算（深夜割増・休憩控除・精勤・封筒・領収書）はこちらが正を持つ。
    先方仕様: attendance_key による upsert・再送あり・順不同あり。

設計:
    ・nginx の /api/ 配下（Basic認証はnginx層ではなくアプリ内で検証。
      Authorization ヘッダをBasicが占有するため、追加の鍵は X-API-Key）
    ・冪等性: 同一 (スタッフ, 日付) のシフト行へ常に「送られてきた最新の真実」を
      上書きする。順不同の再送は updated_at をシフト行 notes 内のマーカーと
      比較して古い更新を捨てる（skipped_stale）
    ・支払い保護: 実績が変わったら承認済み支払いを未承認へ差し戻す
      （ピット端末・出退勤ページと同じ内部統制を通す）
    ・リトライ規約: 4xx=payload起因（再送しない）／5xx=こちら起因（再送する）
"""
from __future__ import annotations

import hmac
import os
import re
from base64 import b64decode
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, field_validator

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402
from dbx.shifts import _revert_payment_if_amount_affected  # noqa: E402

JST = timezone(timedelta(hours=9))
# 深夜跨ぎ判定: この時刻より前の実出勤は「前日のシフトの続き」を先に探す
OVERNIGHT_BOUNDARY_HOUR = 9
_MARKER = re.compile(r"〔API連携 key=(?P<key>[^ 〕]+) updated=(?P<upd>[^〕]+)〕")

app = FastAPI(title="P1 Staff Manager 勤怠受信API", docs_url=None, redoc_url=None,
              openapi_url=None)


class AttendancePayload(BaseModel):
    attendance_key: str
    dealer_number: str
    clock_in_at: datetime
    clock_out_at: Optional[datetime] = None
    updated_at: datetime

    @field_validator("attendance_key", "dealer_number")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = str(v).strip()
        if not v:
            raise ValueError("空にできません")
        return v

    @field_validator("clock_in_at", "clock_out_at", "updated_at")
    @classmethod
    def _tz_required(cls, v):
        if v is not None and v.tzinfo is None:
            raise ValueError("タイムゾーン付きISO 8601（+09:00）で送ってください")
        return v


def _check_auth(authorization: Optional[str], api_key: Optional[str]) -> None:
    user = os.environ.get("ATTENDANCE_API_USER") or ""
    pw = os.environ.get("ATTENDANCE_API_PASSWORD") or ""
    key = os.environ.get("ATTENDANCE_API_KEY") or ""
    if not (user and pw and key):
        # 設定不備で無認証公開になるくらいなら全拒否（fail closed）
        raise HTTPException(503, {"status": "error", "error": "api_not_configured",
                                  "retry": True})
    ok_basic = False
    if authorization and authorization.startswith("Basic "):
        try:
            got_u, _, got_p = b64decode(authorization[6:]).decode("utf-8").partition(":")
            ok_basic = (hmac.compare_digest(got_u, user)
                        and hmac.compare_digest(got_p, pw))
        except Exception:
            ok_basic = False
    if not ok_basic:
        raise HTTPException(
            401, {"status": "error", "error": "unauthorized", "retry": False},
            headers={"WWW-Authenticate": 'Basic realm="P1 Attendance API"'})
    if not hmac.compare_digest(api_key or "", key):
        raise HTTPException(403, {"status": "error", "error": "bad_api_key",
                                  "retry": False})


def _staff_by_no(no: int) -> Optional[dict]:
    r = db.get_client().table("p1_staff").select("id, no, name_jp").eq(
        "no", no).limit(1).execute().data
    return r[0] if r else None


def _event_for_date(d: str) -> Optional[dict]:
    for e in db.get_all_events() or []:
        if str(e.get("start_date")) <= d <= str(e.get("end_date")):
            return e
    return None


def _shift_rows(staff_id: int, dates: list) -> list:
    return db.get_client().table("p1_shifts").select("*").eq(
        "staff_id", staff_id).in_("date", dates).execute().data or []


def _clock_str(dt: datetime, base_date: str) -> str:
    """シフト日付基準の 'HH:MM'（24時超は 25:00 式）へ変換する"""
    base = datetime.fromisoformat(base_date + "T00:00:00+09:00")
    minutes = int((dt.astimezone(JST) - base).total_seconds() // 60)
    if not (0 <= minutes < 48 * 60):
        raise HTTPException(422, {"status": "error", "error": "time_out_of_range",
                                  "detail": f"{dt.isoformat()} は {base_date} の勤務として解釈できません",
                                  "retry": False})
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/attendance")
def upsert_attendance(payload: AttendancePayload,
                      authorization: Optional[str] = Header(None),
                      x_api_key: Optional[str] = Header(None)) -> dict:
    _check_auth(authorization, x_api_key)

    try:
        no = int(payload.dealer_number)
    except ValueError:
        raise HTTPException(422, {"status": "error", "error": "bad_dealer_number",
                                  "retry": False})
    staff = _staff_by_no(no)
    if not staff:
        raise HTTPException(404, {"status": "error", "error": "unknown_dealer",
                                  "dealer_number": payload.dealer_number,
                                  "retry": False})

    jst_in = payload.clock_in_at.astimezone(JST)
    d0 = jst_in.strftime("%Y-%m-%d")
    candidates = [d0]
    if jst_in.hour < OVERNIGHT_BOUNDARY_HOUR:
        candidates.append((jst_in - timedelta(days=1)).strftime("%Y-%m-%d"))
    rows = {r["date"]: r for r in _shift_rows(staff["id"], candidates)}
    # 当日行を優先。無ければ「前日の深夜跨ぎシフトの続き」とみなす
    row = rows.get(d0) or (rows.get(candidates[1]) if len(candidates) > 1 else None)

    client = db.get_client()
    if row is None:
        ev = _event_for_date(d0)
        if not ev:
            raise HTTPException(404, {"status": "error", "error": "no_event_for_date",
                                      "date": d0, "retry": False})
        target_date = d0
        cin = _clock_str(payload.clock_in_at, target_date)
        cout = (_clock_str(payload.clock_out_at, target_date)
                if payload.clock_out_at else None)
        client.table("p1_shifts").insert({
            "event_id": ev["id"], "staff_id": staff["id"], "date": target_date,
            # 予定なしの当日勤務。支払い計算は planned が空だと対象外になるため
            # 実績と同値を入れる（実績優先で計算されるので金額への影響はない）
            "planned_start": cin, "planned_end": cout or cin,
            "actual_start": cin, "actual_end": cout,
            "status": "checked_out" if cout else "checked_in",
            "notes": f"〔API当日追加〕〔API連携 key={payload.attendance_key} "
                     f"updated={payload.updated_at.astimezone(JST).isoformat()}〕",
        }).execute()
        action = "created"
    else:
        target_date = row["date"]
        # 順不同の再送対策: 记録済みの updated より古い更新は捨てる
        m = _MARKER.search(row.get("notes") or "")
        if m:
            try:
                stored = datetime.fromisoformat(m.group("upd"))
                if payload.updated_at.astimezone(JST) <= stored:
                    return {"status": "ok", "action": "skipped_stale",
                            "attendance_key": payload.attendance_key}
            except ValueError:
                pass
        cin = _clock_str(payload.clock_in_at, target_date)
        cout = (_clock_str(payload.clock_out_at, target_date)
                if payload.clock_out_at else None)
        changed = (row.get("actual_start") != cin or row.get("actual_end") != cout)
        base_notes = _MARKER.sub("", row.get("notes") or "").strip()
        marker = (f"〔API連携 key={payload.attendance_key} "
                  f"updated={payload.updated_at.astimezone(JST).isoformat()}〕")
        client.table("p1_shifts").update({
            "actual_start": cin, "actual_end": cout,
            "status": "checked_out" if cout else "checked_in",
            "notes": (base_notes + " " + marker).strip(),
        }).eq("id", row["id"]).execute()
        if changed:
            # 実績が変わったら承認済み支払いを未承認へ（支払済みは内部で保護される）
            _revert_payment_if_amount_affected(
                row, reason=f"API勤怠更新 {cin}〜{cout or '—'}（要再計算）")
        action = "updated"

    db.log_action(
        "api_attendance_upsert", "shifts",
        detail=(f"key={payload.attendance_key} NO.{no} {staff['name_jp']} "
                f"{target_date} {payload.clock_in_at.astimezone(JST).strftime('%H:%M')}"
                f"〜{payload.clock_out_at.astimezone(JST).strftime('%H:%M') if payload.clock_out_at else '—'}"
                f" [{action}]"),
        performed_by="api:P1会員アプリ")
    return {"status": "ok", "action": action,
            "attendance_key": payload.attendance_key,
            "dealer_number": payload.dealer_number, "date": target_date}
