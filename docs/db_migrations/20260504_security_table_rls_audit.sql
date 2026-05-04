-- ============================================================
-- Security P0 #1: テーブルRLS の現状調査と再設定（2段階）
-- 2026-05-04 追加
-- ============================================================
-- 背景:
--   db.py のコメントに「RLS有効＋allow_allポリシー」と記載されており、
--   anon key で全テーブルが読み書き可能な状態の可能性がある。
--   GitHub公開リポジトリで anon key が露出しているため、
--   情報漏洩リスクが顕在化している。
--
-- 推奨運用（最終形）:
--   - anon ロール: receipt_token / contract_token を介した SELECT のみ許可
--   - service_role: 全許可（管理画面はこちらを使う）
--   - Streamlit Cloud Secrets に SUPABASE_KEY として service_role key を設定
--
-- ⚠️ 重要: いきなり全部絞ると現行アプリが動かなくなる可能性がある。
--   まず「現状調査」セクションを実行して、どのポリシーがあるか確認してから、
--   段階的にポリシーを絞ること。
-- ============================================================

-- =========================================================
-- ステップ A: 現状調査（実行しても何も変わらない・読み取り専用）
-- =========================================================
-- 1) 各テーブルの RLS が有効か確認
SELECT
    schemaname, tablename,
    rowsecurity AS rls_enabled
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename LIKE 'p1_%'
ORDER BY tablename;

-- 2) 現在のポリシー一覧（roles に anon が含まれていれば要対応）
SELECT
    schemaname, tablename, policyname,
    cmd, roles, qual
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename LIKE 'p1_%'
ORDER BY tablename, policyname;

-- =========================================================
-- ステップ B: 推奨アクション（手動で1つずつ判断して実行）
-- =========================================================
-- 上記調査の結果、anon ロール向けの "allow_all" ポリシー（USING (true)）が
-- 残っていれば、それを **読み取り専用** に縮小、もしくは完全に取り除く。
--
-- ただし切替には Streamlit Cloud Secrets への service_role key 設定が
-- 必要になるため、本ファイルでは自動実行しない。
--
-- 中野さん：以下の手順で順次実行してください：
--
-- (1) Supabase Project Settings → API → Service Role Key をコピー
-- (2) Streamlit Cloud → アプリ Secrets に追加:
--         SUPABASE_KEY = "<service_role key>"
-- (3) アプリを Reboot（service_role に切替）
-- (4) アプリの動作確認（イベント設定・スタッフ一覧・支払い計算 等）
-- (5) 問題なければ以下を実行して anon を絞る:
--
--     -- 例: p1_staff の anon 全許可ポリシーを削除
--     DROP POLICY IF EXISTS "Allow all access" ON p1_staff;
--     DROP POLICY IF EXISTS "Enable read access for all users" ON p1_staff;
--     -- ↑ ステップ A で見えたポリシー名に合わせて DROP 文を書く
--
--     -- anon は何もできないポリシーに統一
--     CREATE POLICY "p1_staff_deny_anon" ON p1_staff
--         FOR ALL TO anon USING (false);
--
-- (6) (5) を p1_events / p1_event_rates / p1_shifts / p1_payments /
--     p1_petty_cash / p1_audit_log / p1_event_transport_rules /
--     p1_transport_claims / p1_receipt_issuers / p1_contract_templates /
--     p1_contracts に対しても同様に実行
--
-- (7) スタッフ用エンドポイント（receipt_download / contract_sign）は
--     トークン経由で動作するため anon ロールでもアクセス可能にする必要あり。
--     ここは別途 token-validated SELECT ポリシーを設計する（次回マイグレ）。

-- =========================================================
-- ステップ C: ロールバック（service_role 切替後にアプリが動かない場合）
-- =========================================================
-- Streamlit Cloud Secrets の SUPABASE_KEY を anon key に戻す。
-- すでに anon を絞ってしまっていた場合は、CREATE POLICY ... USING (true)
-- で一時的に開放してから根本対応する。
