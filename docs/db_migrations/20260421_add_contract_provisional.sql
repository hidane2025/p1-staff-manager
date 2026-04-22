-- ============================================================
-- Contract Template Provisional Flag Migration (2026-04-21)
-- 契約書テンプレに「仮版 / 正規版」フラグを追加
--   is_provisional = 1 : AI生成など正式承認前の仮版（PDF右上に透かし）
--   is_provisional = 0 : 経理・法務レビュー済みの正規版
-- ============================================================

ALTER TABLE p1_contract_templates
    ADD COLUMN IF NOT EXISTS is_provisional INT DEFAULT 1;

-- 既存の全テンプレは仮版扱いとする（経理打合せの方針）。
UPDATE p1_contract_templates
    SET is_provisional = 1
    WHERE is_provisional IS NULL;

CREATE INDEX IF NOT EXISTS idx_contract_templates_provisional
    ON p1_contract_templates(is_provisional);
