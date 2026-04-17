-- ============================================================
-- Receipt Digitalization Migration (2026-04-17)
-- 領収書デジタル発行機能のためのスキーマ拡張
-- ============================================================
-- Run this in Supabase SQL Editor
-- ============================================================

-- 1. p1_payments に領収書関連カラム追加
ALTER TABLE p1_payments
    ADD COLUMN IF NOT EXISTS receipt_pdf_path TEXT,
    ADD COLUMN IF NOT EXISTS receipt_token TEXT UNIQUE,
    ADD COLUMN IF NOT EXISTS receipt_token_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS receipt_generated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS receipt_downloaded_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS receipt_download_count INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS receipt_no TEXT;

-- 2. p1_events に発行者情報カラム追加（インボイス後日追加OK設計）
ALTER TABLE p1_events
    ADD COLUMN IF NOT EXISTS issuer_name TEXT DEFAULT '株式会社パシフィック',
    ADD COLUMN IF NOT EXISTS issuer_address TEXT,
    ADD COLUMN IF NOT EXISTS issuer_tel TEXT,
    ADD COLUMN IF NOT EXISTS invoice_number TEXT,
    ADD COLUMN IF NOT EXISTS issuer_seal_url TEXT,
    ADD COLUMN IF NOT EXISTS receipt_purpose TEXT DEFAULT 'ポーカー大会運営業務委託費として';

-- 3. インデックス（トークン検索を高速化）
CREATE INDEX IF NOT EXISTS idx_payments_receipt_token ON p1_payments(receipt_token)
    WHERE receipt_token IS NOT NULL;

-- 4. Supabase Storage バケット作成（このSQLでは作らない、ダッシュボードで作成）
--    Storage > Create bucket:
--      Name: receipts
--      Public: OFF  （Signed URLでのみアクセス可）
--      File size limit: 5MB
--      Allowed MIME types: application/pdf

-- 5. バケットRLSポリシー（Dashboardで設定、参考SQL）
-- INSERT用（認証済みユーザーのみ）:
-- CREATE POLICY "Authenticated users can upload receipts"
--     ON storage.objects FOR INSERT
--     TO authenticated
--     WITH CHECK (bucket_id = 'receipts');
-- SELECT用（Signed URLで解決するので不要。anon禁止）
