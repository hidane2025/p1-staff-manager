"""P1会員アプリ（TAKAさん側）からの勤怠実績を受けるAPI（2026-08-13 v2）

背景:
    大会当日の出退勤はTAKAさんのPIT勤怠ツールが一次入力面。実績（実出勤・実退勤）
    だけを本システムへプッシュしてもらい、給与計算（深夜割増・休憩控除・精勤・
    封筒・領収書）はこちらが正を持つ。

v2（2026-08-13 15時・先方がschema.sqlを読んで更新した仕様に全面適合）:
    ・ペイロードは p1_shifts の語彙そのもの:
      dealer_number / date / actual_start / actual_end（"25:17" 等の24時超表記）
    ・日付の解釈（深夜跨ぎでどの日の勤務か）は送信側の責務になった
      → v1にあった朝9時境界の推測ロジックは廃止（解釈の二重化を避ける）
    ・event_id は任意（省略時は date の属する大会をこちらで解決）
    ・actual_start / actual_end を null に戻す更新に対応（打刻の取り消し）
    ・updated_at（任意・推奨）が付いていれば順不同の再送を破棄できる

設計:
    ・認証はASGIミドルウェアで実施（Basic＋X-API-Key の二重）。
      v1はハンドラ内検証だったため、本文の形式エラーが認証より先に
      422を返していた（本番実測）。ミドルウェアなら常に 401/403 が先
    ・冪等性: (event, スタッフ, 日付) のシフト行へ常に最新を上書き。
      p1_shifts に一意制約が無いため、重複行があれば先頭を更新し件数を返す
    ・実績が変わったら承認済み支払いを未承認へ差し戻す（既存の内部統制を再利用）
    ・リトライ規約: 4xx=payload起因（再送しない）／5xx=こちら起因（再送する）
"""
from __future__ import annotations

import hmac
import os
import re
import sys
from base64 import b64decode
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402
from dbx.shifts import _revert_payment_if_amount_affected  # noqa: E402

_MARKER = re.compile(r"〔API連携( key=(?P<key>[^ 〕]+))? updated=(?P<upd>[^〕]+)〕")
_TIME = re.compile(r"^(\d{1,2}):([0-5]\d)$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

app = FastAPI(title="P1 Staff Manager 勤怠受信API", docs_url=None, redoc_url=None,
              openapi_url=None)


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


@app.middleware("http")
async def _auth_middleware(request, call_next):
    """認証は本文の検証より必ず先に行う（v1の 422 が先に出る問題の修正）"""
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        try:
            _check_auth(request.headers.get("authorization"),
                        request.headers.get("x-api-key"))
        except HTTPException as e:
            return JSONResponse({"detail": e.detail}, status_code=e.status_code,
                                headers=getattr(e, "headers", None))
    return await call_next(request)


class AttendancePayload(BaseModel):
    """先方仕様（2026-08-13 15時版）の項目名そのまま＋任意の拡張2つ"""
    dealer_number: str
    date: str
    actual_start: Optional[str] = None
    actual_end: Optional[str] = None
    event_id: Optional[int] = None
    updated_at: Optional[datetime] = None      # 任意・推奨（順不同再送の破棄に使用）
    attendance_key: Optional[str] = None       # 任意（監査ログに記録）

    @field_validator("dealer_number")
    @classmethod
    def _dealer(cls, v: str) -> str:
        v = str(v).strip()
        if not v:
            raise ValueError("dealer_number は空にできません")
        return v

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        if not _DATE.match(str(v).strip()):
            raise ValueError("date は YYYY-MM-DD 形式で送ってください")
        return str(v).strip()

    @field_validator("actual_start", "actual_end")
    @classmethod
    def _time(cls, v: Optional[str]) -> Optional[str]:
        if v is None or str(v).strip() == "":
            return None
        m = _TIME.match(str(v).strip())
        if not m or not (0 <= int(m.group(1)) < 48):
            raise ValueError("時刻は HH:MM（深夜は 25:17 のような24時超表記）で送ってください")
        return f"{int(m.group(1)):02d}:{m.group(2)}"   # 09:30 に正規化

    @field_validator("updated_at")
    @classmethod
    def _tz(cls, v):
        if v is not None and v.tzinfo is None:
            raise ValueError("updated_at はタイムゾーン付きISO 8601で送ってください")
        return v


def _staff_by_no(no: int) -> Optional[dict]:
    r = db.get_client().table("p1_staff").select("id, no, name_jp").eq(
        "no", no).limit(1).execute().data
    return r[0] if r else None


def _event_for_date(d: str) -> Optional[dict]:
    for e in db.get_all_events() or []:
        if str(e.get("start_date")) <= d <= str(e.get("end_date")):
            return e
    return None


def _shift_rows(staff_id: int, date: str) -> list:
    return db.get_client().table("p1_shifts").select("*").eq(
        "staff_id", staff_id).eq("date", date).execute().data or []


def _minutes(t: Optional[str]) -> Optional[int]:
    if t is None:
        return None
    h, m = t.split(":")
    return int(h) * 60 + int(m)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/attendance")
def upsert_attendance(payload: AttendancePayload) -> dict:
    try:
        no = int(payload.dealer_number)
    except ValueError:
        raise HTTPException(422, {"status": "error", "error": "bad_dealer_number",
                                  "retry": False})
    # 整合性: 退勤だけ・退勤が出勤より前、は受理しない
    if payload.actual_end is not None and payload.actual_start is None:
        raise HTTPException(422, {"status": "error", "error": "end_without_start",
                                  "retry": False})
    if (payload.actual_start is not None and payload.actual_end is not None
            and _minutes(payload.actual_end) < _minutes(payload.actual_start)):
        raise HTTPException(422, {
            "status": "error", "error": "end_before_start",
            "detail": "退勤は出勤以降にしてください（深夜は 25:17 のような24時超表記）",
            "retry": False})

    staff = _staff_by_no(no)
    if not staff:
        raise HTTPException(404, {"status": "error", "error": "unknown_dealer",
                                  "dealer_number": payload.dealer_number,
                                  "retry": False})

    rows = _shift_rows(staff["id"], payload.date)
    if payload.event_id is not None:
        scoped = [r for r in rows if r.get("event_id") == payload.event_id]
        rows = scoped or rows
    duplicates = max(0, len(rows) - 1)

    status = ("checked_out" if payload.actual_end is not None
              else "checked_in" if payload.actual_start is not None
              else "scheduled")
    jst_updated = (payload.updated_at.isoformat()
                   if payload.updated_at is not None else None)
    marker = (f"〔API連携 key={payload.attendance_key or '-'} "
              f"updated={jst_updated}〕" if jst_updated else "")

    client = db.get_client()
    if not rows:
        if status == "scheduled":
            # 行が無いところへ「取り消し」だけ来た＝何もすることがない
            return {"status": "ok", "action": "skipped_noop",
                    "dealer_number": payload.dealer_number, "date": payload.date}
        ev_id = payload.event_id
        if ev_id is None:
            ev = _event_for_date(payload.date)
            if not ev:
                raise HTTPException(404, {"status": "error",
                                          "error": "no_event_for_date",
                                          "date": payload.date, "retry": False})
            ev_id = ev["id"]
        client.table("p1_shifts").insert({
            "event_id": ev_id, "staff_id": staff["id"], "date": payload.date,
            # 予定なしの当日勤務。支払い計算は planned が空だと対象外になるため
            # 実績と同値を入れる（計算は実績優先なので金額への影響はない）
            "planned_start": payload.actual_start,
            "planned_end": payload.actual_end or payload.actual_start,
            "actual_start": payload.actual_start,
            "actual_end": payload.actual_end,
            "status": status,
            "notes": ("〔API当日追加〕" + marker).strip(),
        }).execute()
        action = "created"
    else:
        row = rows[0]
        m = _MARKER.search(row.get("notes") or "")
        if m and jst_updated:
            try:
                stored = datetime.fromisoformat(m.group("upd"))
                if payload.updated_at <= stored:
                    return {"status": "ok", "action": "skipped_stale",
                            "dealer_number": payload.dealer_number,
                            "date": payload.date}
            except ValueError:
                pass
        changed = (row.get("actual_start") != payload.actual_start
                   or row.get("actual_end") != payload.actual_end)
        base_notes = _MARKER.sub("", row.get("notes") or "").strip()
        client.table("p1_shifts").update({
            "actual_start": payload.actual_start,
            "actual_end": payload.actual_end,
            "status": status,
            "notes": (base_notes + (" " + marker if marker else "")).strip(),
        }).eq("id", row["id"]).execute()
        if changed:
            # 実績が変わったら承認済み支払いを未承認へ（支払済みは内部で保護）
            _revert_payment_if_amount_affected(
                row, reason=(f"API勤怠更新 {payload.actual_start or '—'}〜"
                             f"{payload.actual_end or '—'}（要再計算）"))
        action = "updated"

    db.log_action(
        "api_attendance_upsert", "shifts",
        detail=(f"key={payload.attendance_key or '-'} NO.{no} {staff['name_jp']} "
                f"{payload.date} {payload.actual_start or '—'}〜"
                f"{payload.actual_end or '—'} [{action}]"
                + (f" 重複行{duplicates}" if duplicates else "")),
        performed_by="api:P1会員アプリ")
    res = {"status": "ok", "action": action,
           "dealer_number": payload.dealer_number, "date": payload.date}
    if payload.attendance_key:
        res["attendance_key"] = payload.attendance_key
    if duplicates:
        res["warning"] = f"同一キーのシフト行が{duplicates + 1}件あり先頭を更新しました"
    return res
