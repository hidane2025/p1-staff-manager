-- =====================================================================
-- A-1 是正（本丸）: anon ロールから public スキーマの全アクセスを剥奪する
-- 2026-06-09
--
-- 背景: 公開リポジトリに anon キーが直書き＋既存テーブルが allow_all RLS のため、
--   匿名キーで本番PII（p1_staff/p1_payments 等）が誰でも読める状態だった。
--
-- ⚠️⚠️ 実行順序を厳守 ⚠️⚠️
--   このSQLは「アプリが service_role で動く」ことを前提に anon を完全遮断する。
--   先に流すと anon 依存のアプリ（現状）が即停止する。必ず次の順で行うこと:
--     1) Streamlit Secrets に SUPABASE_SERVICE_KEY（service_role キー）を設定
--     2) アプリを再起動し、ログイン～各ページが正常動作することを確認
--     3) その確認後に、このSQLを Supabase SQL Editor で実行
--   ※ service_role は RLS をバイパスするため、anon 遮断後もアプリは動作する。
-- =====================================================================

-- 既存テーブル・今後のテーブルとも anon からアクセスできないようにする
REVOKE ALL ON ALL TABLES    IN SCHEMA public FROM anon;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon;
REVOKE USAGE ON SCHEMA public FROM anon;

-- 今後 service_role 等が新規作成するオブジェクトにも anon 権限を付与しない
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES    FROM anon;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon;

-- 確認用（実行後にこのSELECTで anon に残存権限が無いことを確認）:
--   SELECT grantee, table_name, privilege_type
--   FROM information_schema.role_table_grants
--   WHERE grantee = 'anon' AND table_schema = 'public';
--   → 0件になっていれば anon からの読み取りは塞がれている。
