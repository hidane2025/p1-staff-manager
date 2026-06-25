-- ============================================================
-- ディーラー弁当チェック機能（2026-06-18）
-- ============================================================
-- 背景:
--   大会期間中、ディーラー（出勤予定者）に毎日弁当を配布する。
--   現在は紙やLINEで「誰に渡したか」を管理していて、抜け漏れ・二重配布が起きる。
--   このマイグレで「シフト1人1日」単位の弁当配布状態をDBで管理する。
--
-- 設計判断:
--   - 新テーブルは作らず p1_shifts に 3 列だけ追加（シフト＝1人1日 と同じ粒度）
--   - lunch_status は 3 状態:
--       'pending'  : 未受領（既定）
--       'received' : 配布済
--       'cancelled': 辞退（休憩取らない／既に食べた／自前 等）
--   - 監査用に「いつ・誰が」更新したかを残す（後でクレーム時に追跡可能）
--   - 欠勤者は本来配布対象外。UI 側で `status = 'absent'` のシフトを除外する。
--
-- 実行: Supabase SQL Editor で本ファイル全体を貼り付けて Run（冪等・既実行可）
-- ============================================================

ALTER TABLE p1_shifts
    ADD COLUMN IF NOT EXISTS lunch_status TEXT
        NOT NULL DEFAULT 'pending'
        CHECK (lunch_status IN ('pending', 'received', 'cancelled'));

ALTER TABLE p1_shifts
    ADD COLUMN IF NOT EXISTS lunch_status_at TIMESTAMPTZ;

ALTER TABLE p1_shifts
    ADD COLUMN IF NOT EXISTS lunch_status_by TEXT
        NOT NULL DEFAULT '';

-- 日次集計（弁当配布数）が早く引けるようインデックス
CREATE INDEX IF NOT EXISTS idx_p1_shifts_event_date_lunch
    ON p1_shifts (event_id, date, lunch_status);

-- ============================================================
-- 確認用（実行後）:
--   SELECT date, lunch_status, COUNT(*) FROM p1_shifts
--   WHERE event_id = <YOUR_EVENT_ID>
--   GROUP BY date, lunch_status ORDER BY date, lunch_status;
-- ============================================================
