# 勤怠受信API 仕様（P1会員アプリ → P1 Staff Manager）

2026-08-13 作成。P1会員アプリのPIT勤怠から、給与計算用の実績データを受け取る。

## 1. エンドポイント

| 項目 | 値 |
|---|---|
| URL | `https://p1-staff-manager-production.up.railway.app/api/attendance` |
| メソッド | `POST`（JSON） |
| 死活確認 | `GET /api/health` → `{"status":"ok"}`（認証不要） |

## 2. 認証（二重）

| 層 | 方式 | 値の受け渡し |
|---|---|---|
| 1 | **Basic認証**（`Authorization: Basic ...`） | ユーザー名・パスワードは別途個別に連絡 |
| 2 | **APIキー**（`X-API-Key: ...` ヘッダ） | 同上 |

- 管理画面のBasic認証とは**別の専用アカウント**。API以外の画面には入れない
- どちらか欠けると 401 / 403（再送不要）

## 3. リクエストJSON（項目名はP1アプリ案のまま）

```json
{
  "attendance_key": "p1-5-23-123",
  "dealer_number": "0055",
  "clock_in_at": "2026-08-13T12:03:00+09:00",
  "clock_out_at": "2026-08-13T22:17:00+09:00",
  "updated_at": "2026-08-13T22:17:10+09:00"
}
```

- 日時は **タイムゾーン付き ISO 8601**（+09:00）。無い場合は 422
- `clock_out_at` は出勤登録時 `null`
- `dealer_number` はシフト表のNO.（`"0055"` → 55 として照合）

## 4. upsert の挙動

- **同一人物・同一日のシフト行へ常に最新の内容を上書き**（重複登録は発生しない）
- 順不同の再送対策: 行に記録済みの `updated_at` より**古い**送信は破棄し
  `"action": "skipped_stale"` を返す（200）
- 出勤のみ（`clock_out_at: null`）→ 出勤中として記録。退勤送信で確定
- 退勤済みに `null` を再送 → 出勤中へ戻る（打刻の取り消しに対応）
- 深夜跨ぎ: 出勤が朝9時より前の場合は**前日のシフトの続き**として解釈
  （例: 8/13 06:00 の退勤は 8/12 の勤務の 30:00 として記録）
- シフト表に無い日の勤務（当日追加）も受理し、新規行を作成
- 実績が変わった場合、承認済みの支払いは自動で未承認へ差し戻し（再計算対象）

## 5. レスポンス

**成功（200）**
```json
{"status":"ok","action":"created","attendance_key":"p1-5-23-123",
 "dealer_number":"0055","date":"2026-08-13"}
```
`action` は `created` / `updated` / `skipped_stale`

**失敗**
```json
{"detail":{"status":"error","error":"unknown_dealer","dealer_number":"9999","retry":false}}
```

| HTTP | error | 意味 | 再送 |
|---|---|---|---|
| 401 | unauthorized | Basic認証の誤り | しない |
| 403 | bad_api_key | X-API-Key の誤り | しない |
| 404 | unknown_dealer | NO.が本システムに未登録 | しない（要人間確認） |
| 404 | no_event_for_date | その日付に大会が無い | しない |
| 422 | （pydantic詳細） | JSON形式・日時形式の誤り | しない |
| 429 | — | レート制限（120回/分） | 少し待って再送 |
| 5xx / タイムアウト | — | こちら側の障害 | **再送する**（後から自動再送でOK） |

## 6. 運用メモ

- 送信頻度: PITでの保存・更新ごとで問題なし（毎分120回まで）
- 受信内容は監査ログに記録（attendance_key・NO.・時刻・操作主体=API）
- 障害時: `GET /api/health` が200を返さない間は蓄積→復旧後に再送でOK
