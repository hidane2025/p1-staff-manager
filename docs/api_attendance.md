# 勤怠受信API 仕様 v2（P1会員アプリ → P1 Staff Manager）

2026-08-13 15時版の先方仕様（schema.sql準拠のペイロード）に対応。

## 1. エンドポイント

| 項目 | 値 |
|---|---|
| URL | `https://p1-staff-manager-production.up.railway.app/api/attendance` |
| メソッド | `POST`（JSON） |
| 死活確認 | `GET /api/health` → `{"status":"ok"}`（認証不要） |

## 2. 認証（二重・本文検証より必ず先に判定）

| 層 | 方式 |
|---|---|
| 1 | **Basic認証**（`Authorization: Basic ...`）＝API専用アカウント |
| 2 | **APIキー**（`X-API-Key` ヘッダ） |

値は別途個別に連絡。管理画面のBasic認証とは別物で、API以外には入れない。

## 3. リクエストJSON

```json
{
  "event_id": 11,
  "dealer_number": "0055",
  "date": "2026-08-12",
  "actual_start": "12:03",
  "actual_end": "25:17"
}
```

| 項目 | 必須 | 備考 |
|---|---|---|
| dealer_number | ○ | シフト表のNO.（"0055"→55 として照合） |
| date | ○ | YYYY-MM-DD。**深夜跨ぎはどの日の勤務かを送信側で決める**（翌6:00退勤なら前日dateで actual_end="30:00"） |
| actual_start | △ | HH:MM。**null=出勤の取り消し**（両方nullでシフト予定状態へ戻る） |
| actual_end | △ | HH:MM・24時超表記可（`25:17`）。**null=退勤未定（出勤中）** |
| event_id | 任意 | **現在の大会は 11**。省略時は date から自動解決（推奨: 省略） |
| updated_at | 任意・推奨 | ISO 8601（+09:00）。**付いていれば順不同の再送を自動破棄**できる |
| attendance_key | 任意 | 監査ログに記録（トレース用） |

## 4. upsert（Q6/Q8）

- キー = **(event_id, staff_id, date)**。既存行があれば常に上書き＝重複登録しない
  （p1_shifts に一意制約が無い件はAPI側で吸収。万一重複行があれば先頭を更新し
  `warning` を返す）
- `actual_start`/`actual_end` の **null戻しに対応**（取り消し→出勤前の状態へ）
- シフト表に無い日の勤務（当日追加）は行を新規作成
- 実績が変わった場合、承認済みの支払いは自動で未承認へ差し戻し（再計算対象）

## 5. レスポンス

**成功（200）** `action` = `created` / `updated` / `skipped_stale` / `skipped_noop`
```json
{"status":"ok","action":"updated","dealer_number":"0055","date":"2026-08-12"}
```

**失敗** `{"detail":{"status":"error","error":"...","retry":false}}`

| HTTP | error | 意味 | 再送 |
|---|---|---|---|
| 401 / 403 | unauthorized / bad_api_key | 認証誤り | しない |
| 404 | unknown_dealer / no_event_for_date | NO.未登録／大会なし | しない（人間へ連絡） |
| 422 | end_without_start / end_before_start ほか | 形式・整合性エラー | しない |
| 429 | — | レート制限（120回/分） | 少し待って再送 |
| 5xx／タイムアウト | — | こちら側の障害 | **再送する** |

## 6. 運用メモ

- 保存・修正のたびの送信でOK（毎分120回まで）
- 受信は全件監査ログに記録（NO.・時刻・attendance_key・操作主体=API）
- 障害時は蓄積→復旧後に自動再送で問題ない設計（4xxだけは再送せず内容修正）
