-- ============================================================
-- Receipt Original/Copy + Tax Breakdown Migration (2026-04-21)
-- 領収書の原本／控え2バージョン生成 & 消費税額の内訳表示
-- ============================================================
-- Run this in Supabase SQL Editor
-- ============================================================

-- 1. p1_payments に発行者保管用（原本）PDFパスを追加
--    既存 receipt_pdf_path は後方互換として残し、
--    運用上は「控え（receipt_pdf_path）」に対する「原本（receipt_original_path）」を併存させる
ALTER TABLE p1_payments
    ADD COLUMN IF NOT EXISTS receipt_original_path TEXT;

-- 2. p1_events に消費税額の内訳表示ON/OFFフラグを追加
--    0 = 表示しない（デフォルト。従来どおり「税込」のみ表記）
--    1 = 表示する（本体価格・消費税額を2行で明記）
ALTER TABLE p1_events
    ADD COLUMN IF NOT EXISTS show_tax_breakdown INT DEFAULT 0;

-- 3. 参考: 既存の receipt_pdf_path は「控え（スタッフ配布用）」のパスとして運用する。
--    今回のマイグレーションでリネームはしない（後方互換を優先）。
