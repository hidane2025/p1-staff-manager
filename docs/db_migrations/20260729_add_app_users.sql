-- ============================================================
-- アプリユーザー（個人アカウント）のDB管理化（2026-07-29）
-- ============================================================
-- 背景:
--   個人アカウントは従来 secrets.toml / 環境変数でしか定義できず、
--   1人追加するのにコマンド実行と再デプロイが必要だった。
--   2人目の管理者（伊藤さん）を迎えるにあたり、画面から追加・削除できるようにする。
--
-- 設計:
--   ・パスワードは平文を保存しない（pbkdf2-hmac-sha256・ソルト付き）
--   ・管理者が初期パスワードを設定して渡し、初回ログインで本人に変更させる
--     （must_change_password=1）。変更後は本人以外パスワードを知らない状態になる
--   ・無効化(active=0)は削除と違い、監査ログとの紐付けを保ったまま締め出せる
--
-- 実行: Supabase SQL Editor で本ファイル全体をRun（冪等）
-- ============================================================

CREATE TABLE IF NOT EXISTS p1_app_users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer',
    active INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_p1_app_users_lookup
    ON p1_app_users (active, username);

-- ============================================================
-- RLS: anon 拒否 / service_role のみ許可
--   認証情報そのものを持つテーブルなので、当日運用コード・TOTPと同じ扱いにする。
-- ============================================================
ALTER TABLE p1_app_users ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "p1_app_users_deny_anon"        ON p1_app_users;
DROP POLICY IF EXISTS "p1_app_users_service_role_all" ON p1_app_users;

CREATE POLICY "p1_app_users_deny_anon" ON p1_app_users
    FOR ALL TO anon USING (false) WITH CHECK (false);
CREATE POLICY "p1_app_users_service_role_all" ON p1_app_users
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- ============================================================
-- 確認用:
--   SELECT username, role, active, must_change_password FROM p1_app_users;
-- ============================================================
