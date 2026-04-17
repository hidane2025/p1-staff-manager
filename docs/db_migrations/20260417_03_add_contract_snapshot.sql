-- ============================================================
-- Contract Snapshot Fix (2026-04-17 Ultra Review CR-1)
-- 署名時にテンプレートが入れ替わる脆弱性を防ぐ
-- ============================================================

-- 1. 発行時点のレンダリング済み本文をスナップショット保存するカラム
ALTER TABLE p1_contracts
    ADD COLUMN IF NOT EXISTS rendered_body_md TEXT,
    ADD COLUMN IF NOT EXISTS template_version TEXT,
    ADD COLUMN IF NOT EXISTS template_name_snapshot TEXT;

-- 2. 既存データへのマイグレーションはしない（既発行の契約はそのままの振る舞いを維持、
--    再発行時に自動でスナップショット記録される）

COMMENT ON COLUMN p1_contracts.rendered_body_md IS
    '発行時点のレンダリング済み契約本文。署名時はこれを使いテンプレ改変の影響を受けない。';
COMMENT ON COLUMN p1_contracts.template_version IS
    '発行時点のテンプレートバージョン文字列のスナップショット。';
COMMENT ON COLUMN p1_contracts.template_name_snapshot IS
    '発行時点のテンプレート名のスナップショット。';
