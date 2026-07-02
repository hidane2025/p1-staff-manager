-- ============================================================
-- 弁当2個目・ドリンクチケット配布チェック（2026-07-02）
-- ============================================================
-- 背景:
--   スタッフへ弁当（基本1個・12時間以上のシフト者は2個）と
--   ドリンクチケット（一律2枚）を配布している。
--   1個目の弁当は lunch_status（20260618）で管理済み。
--   このマイグレで「2個目の弁当」と「ドリンクチケット」の配布状態を追加する。
--
-- 設計判断:
--   - 20260618_add_lunch_status.sql と同じ流儀（p1_shifts に列追加・3状態・監査列）
--   - lunch2_status: 12時間以上のシフト者のみUIに表示（対象判定は予定シフト時間からアプリ側で行う）
--   - drink_status: 全員一律2枚なので「配布済みか」の1チェックで管理（枚数列は持たない）
--   - 状態: 'pending'（未配布・既定）/ 'received'（配布済）/ 'cancelled'（辞退）
--
-- 実行: Supabase SQL Editor で本ファイル全体を貼り付けて Run（冪等・既実行可）
-- ============================================================

-- 弁当2個目（12時間以上シフト者用）
ALTER TABLE p1_shifts
    ADD COLUMN IF NOT EXISTS lunch2_status TEXT
        NOT NULL DEFAULT 'pending'
        CHECK (lunch2_status IN ('pending', 'received', 'cancelled'));

ALTER TABLE p1_shifts
    ADD COLUMN IF NOT EXISTS lunch2_status_at TIMESTAMPTZ;

ALTER TABLE p1_shifts
    ADD COLUMN IF NOT EXISTS lunch2_status_by TEXT
        NOT NULL DEFAULT '';

-- ドリンクチケット（一律2枚）
ALTER TABLE p1_shifts
    ADD COLUMN IF NOT EXISTS drink_status TEXT
        NOT NULL DEFAULT 'pending'
        CHECK (drink_status IN ('pending', 'received', 'cancelled'));

ALTER TABLE p1_shifts
    ADD COLUMN IF NOT EXISTS drink_status_at TIMESTAMPTZ;

ALTER TABLE p1_shifts
    ADD COLUMN IF NOT EXISTS drink_status_by TEXT
        NOT NULL DEFAULT '';

-- 日次集計用インデックス（lunch_status と同じ流儀）
CREATE INDEX IF NOT EXISTS idx_p1_shifts_event_date_lunch2
    ON p1_shifts (event_id, date, lunch2_status);

CREATE INDEX IF NOT EXISTS idx_p1_shifts_event_date_drink
    ON p1_shifts (event_id, date, drink_status);

-- ============================================================
-- 確認用（実行後）:
--   SELECT date,
--          COUNT(*) FILTER (WHERE lunch2_status = 'received') AS lunch2_done,
--          COUNT(*) FILTER (WHERE drink_status  = 'received') AS drink_done
--   FROM p1_shifts
--   WHERE event_id = <YOUR_EVENT_ID>
--   GROUP BY date ORDER BY date;
-- ============================================================
