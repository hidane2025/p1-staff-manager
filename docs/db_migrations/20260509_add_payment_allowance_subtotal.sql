-- ============================================================
-- Codex P2 fix #3 (2026-05-09): 支払いに個別手当の小計カラム追加
-- ============================================================
-- 背景:
--   Phase 3-I で個別手当（言語手当・人材確保手当 等）の合計が
--   p1_payments.total_amount に加算されるが、内訳カラムが無いため
--   「合計と内訳の和が一致しない」状態になっていた。
--
--   個別手当 ¥5,000 を持つスタッフ:
--     base + night + transport + floor + mix + attendance = ¥51,000
--     total_amount                                          = ¥56,000
--                                                            ↑ ¥5,000 行方不明
--
-- 修正:
--   p1_payments.individual_allowance_total INT DEFAULT 0 を追加。
--   db.save_payment / 表示・CSV 出力でこのカラムを利用する。
--
-- 実行: Supabase SQL Editor で本ファイル全体を貼り付けて Run
-- ============================================================

ALTER TABLE p1_payments
    ADD COLUMN IF NOT EXISTS individual_allowance_total INT NOT NULL DEFAULT 0;

-- マイグレ未実行でも utils/db_schema.has_column 経由で後方互換動作
