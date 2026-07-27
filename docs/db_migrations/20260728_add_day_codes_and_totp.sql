-- ============================================================
-- 当日運用コード + TOTP 2要素認証（2026-07-28）
-- ============================================================
-- 背景:
--   ①管理者パスワードが1本の共有制で有効期限がない
--     → 大会当日のTD・給与窓口には「その日だけ有効なコード」を配る方式に変更
--   ②パスワード単要素 → 管理者ログインにTOTP（認証アプリの30秒コード）を追加
--
-- 実行: Supabase SQL Editor または管理APIで本ファイル全体をRun（冪等）
-- ============================================================

-- 当日運用コード（平文は保存しない。SHA-256ハッシュのみ）
CREATE TABLE IF NOT EXISTS p1_day_codes (
    id BIGSERIAL PRIMARY KEY,
    code_hash TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    valid_date DATE NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_p1_day_codes_lookup
    ON p1_day_codes (active, code_hash);

-- 管理者TOTP設定（account='admin'=単一パスワード運用 / 多ユーザー時はユーザーID）
CREATE TABLE IF NOT EXISTS p1_admin_totp (
    id BIGSERIAL PRIMARY KEY,
    account TEXT NOT NULL UNIQUE,
    secret TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- 確認用:
--   SELECT count(*) FROM p1_day_codes;
--   SELECT account, enabled FROM p1_admin_totp;
-- ============================================================

-- ============================================================
-- RLS: anon 拒否 / service_role のみ許可（敵対レビュー指摘対応 2026-07-28）
-- ⚠️ 適用順序が重要:
--   1. Streamlit Secrets に SUPABASE_SERVICE_KEY を設定
--   2. 発行者設定ページ「🩺 DB接続診断」が service_role 接続を示すのを確認
--   3. その後にこのRLSブロックを実行
--   （先に流すとアプリ(anon接続)が当日コード・TOTPを読めなくなり機能が黙って停止する）
-- ============================================================
ALTER TABLE p1_day_codes  ENABLE ROW LEVEL SECURITY;
ALTER TABLE p1_admin_totp ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "p1_day_codes_deny_anon"         ON p1_day_codes;
DROP POLICY IF EXISTS "p1_day_codes_service_role_all"  ON p1_day_codes;
DROP POLICY IF EXISTS "p1_admin_totp_deny_anon"        ON p1_admin_totp;
DROP POLICY IF EXISTS "p1_admin_totp_service_role_all" ON p1_admin_totp;

CREATE POLICY "p1_day_codes_deny_anon" ON p1_day_codes
    FOR ALL TO anon USING (false) WITH CHECK (false);
CREATE POLICY "p1_day_codes_service_role_all" ON p1_day_codes
    FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "p1_admin_totp_deny_anon" ON p1_admin_totp
    FOR ALL TO anon USING (false) WITH CHECK (false);
CREATE POLICY "p1_admin_totp_service_role_all" ON p1_admin_totp
    FOR ALL TO service_role USING (true) WITH CHECK (true);
