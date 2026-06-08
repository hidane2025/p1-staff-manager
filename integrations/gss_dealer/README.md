# ディーラー応募 GSS 連動（案A: 各大会対応） — デプロイ手順

設計書: `パシフィック/P1/5_システム開発部/設計_ディーラー応募GSS連動_v3`

構成: 各大会の応募フォーム(GSS) → スタンドアロンGAS（読取専用・全大会巡回）→ Edge Function（service_role隔離）→ Supabase → Streamlit（大会登録／応募管理）

> ⚠️ 本番GSSには書き込まない・バインドしない。GASは別プロジェクトから `openById` で読むだけ。

## 案A の肝：新しい大会の増やし方
**大会が増えたら、アプリの「応募フォーム設定」画面で大会を選び、GSSのURLを貼って保存するだけ。**
GASはその一覧(`p1_application_sources`)をEdge経由で読み、全 active 大会を自動巡回します。**GAS/コードの編集は不要**。

---

## 🚦 ステップ0：着手前ゲート（必須・PII保護）

各大会のソースGSSは、リンク公開だと未認証で応募者の本名・住所が取れてしまう。連動前に必ず：
1. 各GSS → 共有 → **「リンクを知っている全員」をオフ**
2. 連動実行用Googleアカウントを **「閲覧者(Viewer)」** で追加
3. 未認証の別ブラウザでCSVエクスポートが **403/404** になることを確認

## ステップ1：Supabase 受け皿を作る
Supabase SQL Editor で `docs/db_migrations/20260608_add_dealer_applications.sql` を実行。
- `p1_application_sources`（大会↔GSS対応表）/ `p1_dealer_applications`（event_id付き）/ `p1_import_runs` / `p1_import_errors` / `promote_dealer_application()` が作られる。

## ステップ2：Edge Function をデプロイ（service_role 隔離）
```bash
openssl rand -hex 32                 # → INGEST_SECRET として控える
supabase functions deploy ingest-dealer-applications --no-verify-jwt
supabase secrets set INGEST_SECRET="<生成値>"
```
- `integrations/gss_dealer/edge_function/index.ts` を `supabase/functions/ingest-dealer-applications/index.ts` に配置。
- 2アクション: `sources`（大会一覧返却）/ `ingest`（応募取込）。**service_roleはこの関数内のみ**。

## ステップ3：スタンドアロンGASを作る（本番GSSにバインドしない）
1. https://script.google.com で**新規プロジェクト**を作成（本番GSSの拡張機能からは作らない）。
2. `integrations/gss_dealer/Code.gs` を貼り付け。
3. スクリプト プロパティ:

   | キー | 値 |
   |---|---|
   | `EDGE_FN_URL` | `https://<project>.supabase.co/functions/v1/ingest-dealer-applications` |
   | `INGEST_SECRET` | ステップ2の値（同一） |
   | `OVERLAP_HOURS` | `6` |

   ※ `SOURCE_SPREADSHEET_ID` は**不要**になりました（大会一覧はDBから取得）。
4. 実行アカウントが**各大会GSSの閲覧者**であること（ステップ0-2）。
5. **時間主導トリガー**: 関数 `pollAndSync` / 時間主導 / 10分おき。

## ステップ4：大会↔GSS を登録する（案Aの中心）
- 推奨: アプリの「応募フォーム設定」画面で大会を選び、GSS URLを貼って保存（※UIは次フェーズで実装）。
- UI実装前の暫定: Supabase で1行入れる。
  ```sql
  INSERT INTO p1_application_sources (event_id, label, spreadsheet_id, sheet_name)
  VALUES (<対象大会のp1_events.id>, 'OSAKA SUMMER',
          '1RUShCGNrFm70E7_04JAnCxenxDFeq1SzjtSAld33vx8', 'フォームの回答 1');
  ```

## ステップ5：動作確認（読み取りのみ）
1. GASで `pollAndSync` 手動実行 → ログに `ingested total=N`（PIIはログに出ない）。
2. `select count(*) from p1_dealer_applications where event_id = <id>;` が増える。
3. 重複実行で二重登録されない（冪等）。内容変更が `source_changed` になる。

## 次フェーズ（アプリUI）
- **応募フォーム設定ページ**: 大会↔GSS URLの登録/有効化（案Aの登録画面）。
- **応募管理ページ**: 大会で絞って一覧→採用/却下→`promote_dealer_application()` で `p1_staff` 昇格（同一メールは既存スタッフ再利用）。
- 応募(PII)の閲覧は管理者ロール＋サーバ側 service_role 経由（A-1是正と整合）。

---

## 運用上の約束（taka/木村さんと合意したい）
- **append-only**: 応募行を後から編集・削除しない（冪等キーが行番号基準のため）。
- ヘッダ名は維持（列順は変わってOK。勤務可能日は日付/「勤務可能」を自動検出）。
- 不採用者データの保持期限・削除方針を決める（PIIコンプライアンス）。
