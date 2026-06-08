# ディーラー応募 GSS 連動 — デプロイ手順

設計書: `パシフィック/P1/5_システム開発部/設計_ディーラー応募GSS連動_v2`
構成: 本番GSS（不可侵）→ スタンドアロンGAS（読取専用）→ Edge Function（service_role隔離）→ Supabase 応募テーブル → Streamlit 応募管理

> ⚠️ **本番GSSには一切書き込まない・バインドしない。** GASは別プロジェクトから `openById` で読むだけ。

---

## 🚦 ステップ0：着手前ゲート（必須・PII保護）

ソースGSSは現状リンク公開で**未認証でも応募者の本名・住所・生年月日が取得できる**状態。連動前に必ず塞ぐ：

1. ソースGSS → 共有 → **「リンクを知っている全員」をオフ**（特定ユーザーのみに変更）
2. 連動実行用Googleアカウントを **「閲覧者(Viewer)」** で追加（✅ 2026-06 付与済み）
3. 確認: 未認証の別ブラウザで CSV エクスポートURLが **403/404** になること

この3点が済むまで以降に進まない。

---

## ステップ1：Supabase 受け皿を作る

1. Supabase SQL Editor で `docs/db_migrations/20260608_add_dealer_applications.sql` を実行
   - `p1_dealer_applications` / `p1_import_runs` / `p1_import_errors` / `promote_dealer_application()` が作られる
   - RLS は anon 全拒否・service_role のみ（既存方針どおり）

## ステップ2：Edge Function をデプロイ（service_role 隔離）

```bash
# シークレット生成（GASと共有するHMAC鍵）
openssl rand -hex 32            # → これを INGEST_SECRET として控える

supabase functions deploy ingest-dealer-applications --no-verify-jwt
supabase secrets set INGEST_SECRET="<生成した値>"
# SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY は Supabase が自動注入（手動設定不要な場合あり）
```

- `integrations/gss_dealer/edge_function/index.ts` を `supabase/functions/ingest-dealer-applications/index.ts` として配置してデプロイ。
- **service_role キーはこの関数内だけ**に存在する（GASには絶対に置かない）。

## ステップ3：スタンドアロンGASを作る（本番GSSにバインドしない）

1. https://script.google.com で**新規プロジェクト**を作成（※本番GSSの「拡張機能>Apps Script」からは作らない）
2. `integrations/gss_dealer/Code.gs` の内容を貼り付け
3. プロジェクトの設定 → **スクリプト プロパティ** に設定:

   | キー | 値 |
   |---|---|
   | `SOURCE_SPREADSHEET_ID` | 本番GSSのID（`1RUSh…`） |
   | `SOURCE_SHEET_NAME` | 回答シート名（例: `フォームの回答 1`） |
   | `EDGE_FN_URL` | `https://<project>.supabase.co/functions/v1/ingest-dealer-applications` |
   | `INGEST_SECRET` | ステップ2で生成した値（同一） |
   | `OVERLAP_HOURS` | `6`（既定でOK） |

4. 実行アカウントが本番GSSの**閲覧者**であること（ステップ0-2）。
5. **時間主導トリガー**を追加: 関数 `pollAndSync` / イベント「時間主導」/ 「分ベース」10分おき。
   - ⚠️ `onEdit` 等のバインドトリガーは使わない（本番GSSに紐づくため禁止）。

## ステップ4：動作確認（読み取りのみ）

1. GASエディタで `pollAndSync` を手動実行 → 実行ログに `ingested rows=N` が出る（**PIIはログに出ない**＝件数のみ）。
2. Supabase で `select count(*) from p1_dealer_applications;` が増えることを確認。
3. 重複実行しても二重登録されない（冪等）こと、内容変更が `source_changed` になることを確認。

## ステップ5：Streamlit 応募管理（次フェーズ）

- 応募一覧→採用判定→`promote_dealer_application()` で `p1_staff` 昇格。
- ※ アプリ側UI（`pages/12_応募管理.py`）は別コミットで実装予定（管理者ロール限定）。

---

## 運用上の約束（taka/木村さんと合意したい）

- **append-only**：応募行を後から編集・削除しない（編集/削除は検知不能なため）。
- ヘッダ名は維持（列順は変わってOK＝ヘッダ名で吸収）。必須列の改名時は連絡。
- 不採用者データの保持期限・削除方針を決める（PIIコンプライアンス）。

## セキュリティ要点（再掲）

- service_role は Edge Function のみ。GAS は HMAC シークレットのみ。
- GAS実行ログにPIIを出さない（件数だけ）。
- 応募テーブルは anon 全拒否（RLS）。閲覧は管理者ロールのアプリ経由のみ。
