-- =====================================================================
-- 20260601_add_payable_amount_and_rounding.sql
-- A-5 / A-6（金額の一元化）: 支払額の「正」を丸め後額に統一する。
--
-- 背景（監査 A-6）:
--   従来は封筒リストが「端数丸め後額(adjusted_amount)」を画面表示するだけで DB 保存せず、
--   領収書PDF・年間累計は「丸め前の total_amount」を使っていた。結果、封筒で渡す現金額と
--   領収書の額面が一致しないことがあり、証憑の整合性が崩れていた。
--
-- 本マイグレで:
--   1) p1_payments.payable_amount … 実際に支払う確定額（= round_amount(total_amount, rounding_unit)）。
--      封筒・領収書・年間累計・精算レポート・ピット端末は全てこの列を「正」として参照する。
--   2) p1_events.rounding_unit … イベント単位の端数処理単位（0=なし/100/500/1000）。
--      丸めは「画面表示時の都合」ではなく「支払額の確定処理」に格上げし、save_payment が
--      この単位で payable_amount を算出して保存する。
--
-- A-5（adjustment 正式項目化）は p1_payments.adjustment（既存列）をそのまま使うため、
--   本マイグレでの列追加は不要（total_amount に adjustment を含めて保存する運用に変更）。
--
-- 後方互換: アプリは utils.db_schema.has_column で両列の存在を確認し、未適用環境では
--   payable_amount を total_amount で代替・rounding_unit=0 扱いにする。未適用でも動作する。
-- 冪等: IF NOT EXISTS / 条件付き UPDATE。再実行しても安全。
-- =====================================================================

-- 1) 支払確定額（丸め後）。既存行は total_amount で初期化（=丸めなし相当）。
ALTER TABLE p1_payments
    ADD COLUMN IF NOT EXISTS payable_amount INT;

COMMENT ON COLUMN p1_payments.payable_amount IS
    '実際に支払う確定額（端数丸め後）。封筒・領収書・年間累計が参照する唯一の正。NULL の旧行は total_amount を代替値とする。';

UPDATE p1_payments
    SET payable_amount = total_amount
    WHERE payable_amount IS NULL;

-- 2) イベント単位の端数処理単位（0=なし）。
ALTER TABLE p1_events
    ADD COLUMN IF NOT EXISTS rounding_unit INT DEFAULT 0;

COMMENT ON COLUMN p1_events.rounding_unit IS
    '端数処理単位（0=なし / 100 / 500 / 1000）。支払い計算ページで設定し、save_payment が payable_amount 算出に使う。';

UPDATE p1_events
    SET rounding_unit = 0
    WHERE rounding_unit IS NULL;
