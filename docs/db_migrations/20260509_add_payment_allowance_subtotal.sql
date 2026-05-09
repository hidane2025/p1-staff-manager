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

-- ============================================================
-- Backfill: Phase 3-I 適用前に作成済みの p1_payments レコードに対して
-- 個別手当の合計を補完する。これがないと、approved/paid レコードは
-- save_payment の保護で再計算されないため、ずっと内訳と合計がズレたままになる。
-- ============================================================
UPDATE p1_payments p
SET    individual_allowance_total = COALESCE(sub.allowance_total, 0)
FROM   (
    SELECT event_id, staff_id, SUM(amount)::INT AS allowance_total
    FROM   p1_staff_event_allowances
    GROUP  BY event_id, staff_id
) sub
WHERE  p.event_id = sub.event_id
  AND  p.staff_id = sub.staff_id
  AND  p.individual_allowance_total = 0;   -- 既に値が入っている行は触らない

-- 確認用クエリ（実行後に貼ってチェック）:
--   SELECT event_id, staff_id, total_amount, individual_allowance_total
--   FROM   p1_payments WHERE individual_allowance_total > 0 LIMIT 20;

-- マイグレ未実行でも utils/db_schema.has_column 経由で後方互換動作
