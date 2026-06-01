-- =====================================================================
-- 20260601_add_paid_by.sql
-- A-2 (監査証跡): 支払実行者を記録する paid_by 列を p1_payments に追加。
--
-- 背景: 従来 mark_paid() は「誰が現金を支払済みにしたか」を記録しておらず、
--       監査ログ上も performed_by='system' 固定だった（approve_payment は
--       approved_by を持つのに非対称）。現金確定は最も不可逆な操作のため、
--       実行者を payment 行に永続化して承認者(approved_by)と対称化する。
--
-- 後方互換: db.mark_paid() は utils.db_schema.has_column("p1_payments","paid_by")
--           を見て、この列が無ければ書き込みをスキップする。よって本マイグレ
--           未適用でもアプリは動作する（監査ログ側には performed_by として残る）。
-- 冪等: IF NOT EXISTS。再実行しても安全。
-- =====================================================================

ALTER TABLE p1_payments
    ADD COLUMN IF NOT EXISTS paid_by TEXT;

COMMENT ON COLUMN p1_payments.paid_by IS
    '支払済みに確定した操作者（ログイン中の operator_name）。承認者 approved_by と対で内部統制の証跡に使う。';
