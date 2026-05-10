-- ============================================================
-- Phase 3 #I: 個別手当システム（2026-05-08）
-- ============================================================
-- 背景:
--   現場フィードバック（伊藤さん経由）：
--   人により手当がつく人とつかない人がいる（言語手当・人材確保手当 等）。
--   この手当はオフレコの時もあるため、ピットでの操作は不可。
--   給与支給時に操作が必要。
--
-- 設計判断:
--   - 新テーブル p1_staff_event_allowances（イベント×スタッフ×手当タイプ）
--   - allowance_type: language / recruitment / leadership / other
--   - is_off_record: TRUE なら ピット端末では「設定済み（額非表示）」のみ表示、
--     金額・内訳は require_admin な画面でのみ閲覧可能
--   - 計算エンジン: total_amount に加算（内訳は別途取得して詳細画面で表示）
--   - 監査ログ: add_individual_allowance / remove_individual_allowance
--
-- 実行: Supabase SQL Editor で本ファイル全体を貼り付けて Run
-- ============================================================

CREATE TABLE IF NOT EXISTS p1_staff_event_allowances (
    id BIGSERIAL PRIMARY KEY,
    event_id BIGINT NOT NULL REFERENCES p1_events(id) ON DELETE CASCADE,
    staff_id BIGINT NOT NULL REFERENCES p1_staff(id) ON DELETE CASCADE,
    allowance_type TEXT NOT NULL,           -- "language" / "recruitment" / "leadership" / "other"
    label TEXT NOT NULL DEFAULT '',         -- 表示用ラベル（例: "中国語対応"）
    amount INTEGER NOT NULL DEFAULT 0,      -- 円単位
    is_off_record INT NOT NULL DEFAULT 0,   -- 1 なら オフレコ扱い（ピット端末で詳細非表示）
    note TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL DEFAULT '',    -- 付与した管理者名
    UNIQUE (event_id, staff_id, allowance_type, label)
);

-- インデックス: イベント×スタッフ で頻繁に引く
CREATE INDEX IF NOT EXISTS idx_p1_staff_event_allowances_event_staff
    ON p1_staff_event_allowances (event_id, staff_id);

-- ============================================================
-- Codex 4回目 P1 #7 (2026-05-09): RLS有効化 + anon拒否ポリシー
-- ============================================================
-- 個別手当（特にオフレコ手当）は支払い金額・スタッフ氏名を含む高機微データ。
-- アプリは現在 anon-key フォールバック構成のため、テーブルに RLS が無いと
-- ページレベルの require_admin だけでは Supabase API 直叩きを防げない。
-- ここで明示的に anon を拒否し、サービスロール（バックエンド）のみアクセス可能に。
-- ============================================================
ALTER TABLE p1_staff_event_allowances ENABLE ROW LEVEL SECURITY;

-- 既存ポリシーがあれば置き換え（再実行可能性のため）
DROP POLICY IF EXISTS "p1_allowances_deny_anon" ON p1_staff_event_allowances;
DROP POLICY IF EXISTS "p1_allowances_service_role_all" ON p1_staff_event_allowances;

-- anon ロールは何もできない
CREATE POLICY "p1_allowances_deny_anon" ON p1_staff_event_allowances
    FOR ALL TO anon USING (false) WITH CHECK (false);

-- service_role / authenticated は全許可（管理画面はこちらを使う）
CREATE POLICY "p1_allowances_service_role_all" ON p1_staff_event_allowances
    FOR ALL TO service_role, authenticated USING (true) WITH CHECK (true);

-- 確認用クエリ:
--   SELECT policyname, cmd, roles, qual FROM pg_policies
--   WHERE tablename = 'p1_staff_event_allowances';

-- ============================================================
-- 参考: 手当タイプの想定例
-- ============================================================
--   language       中国語対応 / 韓国語対応 / 英語対応 等（イベント1日 ¥3,000など）
--   recruitment    人材確保手当（採用優遇枠での参加に対する追加報酬）
--   leadership     シフトリーダー手当 / TD補佐手当
--   other          特別な事情に基づく追加手当（オフレコ運用しやすい）
--
-- ============================================================
-- ロールバック
-- ============================================================
-- DROP TABLE IF EXISTS p1_staff_event_allowances;
