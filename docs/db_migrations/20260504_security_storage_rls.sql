-- ============================================================
-- Security P0 #3: Storage RLS（領収書PDF / 契約書PDF バケット）
-- 2026-05-04 追加
-- ============================================================
-- 目的: 領収書・契約書 PDF が「URLさえ知っていれば誰でもDL可能」な
--       状態を解消する。アプリは Signed URL 経由で配信するため、
--       直接アクセスはすべて拒否する。
--
-- 影響:
--   - スタッフが受け取った tokens 付きURL からのDLは引き続き機能する
--     （Signed URL は anon key 不要で動作するため）
--   - ダッシュボードの「直接URL一覧表示」は引き続き Signed URL を介する
--
-- 実行: Supabase SQL Editor で本ファイル全体を貼り付けて Run
-- ============================================================

-- =========================================================
-- 1. receipts バケット
-- =========================================================
-- 既存のゆるいポリシー（あれば）を削除
DROP POLICY IF EXISTS "receipts_anon_read"        ON storage.objects;
DROP POLICY IF EXISTS "receipts_anon_select"      ON storage.objects;
DROP POLICY IF EXISTS "receipts_public_select"    ON storage.objects;
DROP POLICY IF EXISTS "Public access to receipts" ON storage.objects;

-- anon ロールには receipts バケットの SELECT を完全禁止
-- （Signed URL 経由のアクセスはこのポリシーに影響されない）
CREATE POLICY "receipts_deny_anon_direct" ON storage.objects
    FOR SELECT TO anon
    USING (bucket_id <> 'receipts');

-- service_role / authenticated は全許可（既存の挙動を維持）
-- ※ 通常 service_role は RLS 自体をバイパスするため明示ポリシーは不要

-- =========================================================
-- 2. contracts バケット（契約書PDF + 署名画像）
-- =========================================================
DROP POLICY IF EXISTS "contracts_anon_read"        ON storage.objects;
DROP POLICY IF EXISTS "contracts_anon_select"      ON storage.objects;
DROP POLICY IF EXISTS "contracts_public_select"    ON storage.objects;
DROP POLICY IF EXISTS "Public access to contracts" ON storage.objects;

CREATE POLICY "contracts_deny_anon_direct" ON storage.objects
    FOR SELECT TO anon
    USING (bucket_id <> 'contracts');

-- =========================================================
-- 3. バケットを Public OFF に設定（保険の二重防御）
-- =========================================================
-- ※ Supabase ダッシュボード Storage > Settings からも確認・設定する
UPDATE storage.buckets
   SET public = false
 WHERE name IN ('receipts', 'contracts');

-- =========================================================
-- 4. 確認クエリ（実行後に貼り付けて挙動チェック）
-- =========================================================
-- 現在のバケット public/private 状態
--   SELECT name, public FROM storage.buckets WHERE name IN ('receipts','contracts');
-- 現在のポリシー一覧
--   SELECT policyname, cmd, roles, qual FROM pg_policies WHERE tablename = 'objects' AND schemaname = 'storage';

-- =========================================================
-- 5. ロールバック手順（万一アプリが動かなくなった場合）
-- =========================================================
-- DROP POLICY IF EXISTS "receipts_deny_anon_direct"  ON storage.objects;
-- DROP POLICY IF EXISTS "contracts_deny_anon_direct" ON storage.objects;
-- UPDATE storage.buckets SET public = true WHERE name IN ('receipts','contracts');
