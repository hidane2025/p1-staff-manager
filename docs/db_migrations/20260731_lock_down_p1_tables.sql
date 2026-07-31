-- =====================================================================
-- P1テーブルへの匿名アクセスを遮断（2026-07-31）
-- =====================================================================
-- 背景: 公開リポジトリに含まれていたanonキーで、p1_staff（氏名・住所）や
--       p1_day_codes（当日運用コードのハッシュ）が実際に読める状態だった。
--       原因は ①anon/authenticated にテーブル権限が付いたまま
--             ②RLSポリシーが allow_all（USING true）
--             ③一部テーブルはRLS自体が無効
--
-- 適用条件: アプリが service_role で接続していること（確認済み）。
--          service_role は RLS をバイパスするため、遮断後もアプリは動作する。
-- 対象範囲: p1_ プレフィックスのテーブルのみ。
--          同一DBに同居する他事業のテーブルには一切触れない。
-- =====================================================================
-- P1テーブルのみを対象に匿名アクセスを遮断（他事業のテーブルには触れない）

REVOKE ALL ON TABLE public.p1_admin_totp FROM anon, authenticated;
ALTER TABLE public.p1_admin_totp ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "allow_all" ON public.p1_admin_totp;
DROP POLICY IF EXISTS "p1_admin_totp_deny_anon" ON public.p1_admin_totp;
DROP POLICY IF EXISTS "p1_admin_totp_service_role_all" ON public.p1_admin_totp;
CREATE POLICY "p1_admin_totp_deny_anon" ON public.p1_admin_totp
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY "p1_admin_totp_service_role_all" ON public.p1_admin_totp
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON TABLE public.p1_app_users FROM anon, authenticated;
ALTER TABLE public.p1_app_users ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "allow_all" ON public.p1_app_users;
DROP POLICY IF EXISTS "p1_app_users_deny_anon" ON public.p1_app_users;
DROP POLICY IF EXISTS "p1_app_users_service_role_all" ON public.p1_app_users;
CREATE POLICY "p1_app_users_deny_anon" ON public.p1_app_users
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY "p1_app_users_service_role_all" ON public.p1_app_users
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON TABLE public.p1_audit_log FROM anon, authenticated;
ALTER TABLE public.p1_audit_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "allow_all" ON public.p1_audit_log;
DROP POLICY IF EXISTS "p1_audit_log_deny_anon" ON public.p1_audit_log;
DROP POLICY IF EXISTS "p1_audit_log_service_role_all" ON public.p1_audit_log;
CREATE POLICY "p1_audit_log_deny_anon" ON public.p1_audit_log
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY "p1_audit_log_service_role_all" ON public.p1_audit_log
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON TABLE public.p1_contract_templates FROM anon, authenticated;
ALTER TABLE public.p1_contract_templates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "allow_all" ON public.p1_contract_templates;
DROP POLICY IF EXISTS "p1_contract_templates_deny_anon" ON public.p1_contract_templates;
DROP POLICY IF EXISTS "p1_contract_templates_service_role_all" ON public.p1_contract_templates;
CREATE POLICY "p1_contract_templates_deny_anon" ON public.p1_contract_templates
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY "p1_contract_templates_service_role_all" ON public.p1_contract_templates
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON TABLE public.p1_contracts FROM anon, authenticated;
ALTER TABLE public.p1_contracts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "allow_all" ON public.p1_contracts;
DROP POLICY IF EXISTS "p1_contracts_deny_anon" ON public.p1_contracts;
DROP POLICY IF EXISTS "p1_contracts_service_role_all" ON public.p1_contracts;
CREATE POLICY "p1_contracts_deny_anon" ON public.p1_contracts
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY "p1_contracts_service_role_all" ON public.p1_contracts
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON TABLE public.p1_day_codes FROM anon, authenticated;
ALTER TABLE public.p1_day_codes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "allow_all" ON public.p1_day_codes;
DROP POLICY IF EXISTS "p1_day_codes_deny_anon" ON public.p1_day_codes;
DROP POLICY IF EXISTS "p1_day_codes_service_role_all" ON public.p1_day_codes;
CREATE POLICY "p1_day_codes_deny_anon" ON public.p1_day_codes
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY "p1_day_codes_service_role_all" ON public.p1_day_codes
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON TABLE public.p1_event_rates FROM anon, authenticated;
ALTER TABLE public.p1_event_rates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "allow_all" ON public.p1_event_rates;
DROP POLICY IF EXISTS "p1_event_rates_deny_anon" ON public.p1_event_rates;
DROP POLICY IF EXISTS "p1_event_rates_service_role_all" ON public.p1_event_rates;
CREATE POLICY "p1_event_rates_deny_anon" ON public.p1_event_rates
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY "p1_event_rates_service_role_all" ON public.p1_event_rates
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON TABLE public.p1_event_transport_rules FROM anon, authenticated;
ALTER TABLE public.p1_event_transport_rules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "allow_all" ON public.p1_event_transport_rules;
DROP POLICY IF EXISTS "p1_event_transport_rules_deny_anon" ON public.p1_event_transport_rules;
DROP POLICY IF EXISTS "p1_event_transport_rules_service_role_all" ON public.p1_event_transport_rules;
CREATE POLICY "p1_event_transport_rules_deny_anon" ON public.p1_event_transport_rules
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY "p1_event_transport_rules_service_role_all" ON public.p1_event_transport_rules
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON TABLE public.p1_events FROM anon, authenticated;
ALTER TABLE public.p1_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "allow_all" ON public.p1_events;
DROP POLICY IF EXISTS "p1_events_deny_anon" ON public.p1_events;
DROP POLICY IF EXISTS "p1_events_service_role_all" ON public.p1_events;
CREATE POLICY "p1_events_deny_anon" ON public.p1_events
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY "p1_events_service_role_all" ON public.p1_events
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON TABLE public.p1_payments FROM anon, authenticated;
ALTER TABLE public.p1_payments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "allow_all" ON public.p1_payments;
DROP POLICY IF EXISTS "p1_payments_deny_anon" ON public.p1_payments;
DROP POLICY IF EXISTS "p1_payments_service_role_all" ON public.p1_payments;
CREATE POLICY "p1_payments_deny_anon" ON public.p1_payments
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY "p1_payments_service_role_all" ON public.p1_payments
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON TABLE public.p1_petty_cash FROM anon, authenticated;
ALTER TABLE public.p1_petty_cash ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "allow_all" ON public.p1_petty_cash;
DROP POLICY IF EXISTS "p1_petty_cash_deny_anon" ON public.p1_petty_cash;
DROP POLICY IF EXISTS "p1_petty_cash_service_role_all" ON public.p1_petty_cash;
CREATE POLICY "p1_petty_cash_deny_anon" ON public.p1_petty_cash
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY "p1_petty_cash_service_role_all" ON public.p1_petty_cash
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON TABLE public.p1_shifts FROM anon, authenticated;
ALTER TABLE public.p1_shifts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "allow_all" ON public.p1_shifts;
DROP POLICY IF EXISTS "p1_shifts_deny_anon" ON public.p1_shifts;
DROP POLICY IF EXISTS "p1_shifts_service_role_all" ON public.p1_shifts;
CREATE POLICY "p1_shifts_deny_anon" ON public.p1_shifts
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY "p1_shifts_service_role_all" ON public.p1_shifts
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON TABLE public.p1_staff FROM anon, authenticated;
ALTER TABLE public.p1_staff ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "allow_all" ON public.p1_staff;
DROP POLICY IF EXISTS "p1_staff_deny_anon" ON public.p1_staff;
DROP POLICY IF EXISTS "p1_staff_service_role_all" ON public.p1_staff;
CREATE POLICY "p1_staff_deny_anon" ON public.p1_staff
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY "p1_staff_service_role_all" ON public.p1_staff
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON TABLE public.p1_transport_claims FROM anon, authenticated;
ALTER TABLE public.p1_transport_claims ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "allow_all" ON public.p1_transport_claims;
DROP POLICY IF EXISTS "p1_transport_claims_deny_anon" ON public.p1_transport_claims;
DROP POLICY IF EXISTS "p1_transport_claims_service_role_all" ON public.p1_transport_claims;
CREATE POLICY "p1_transport_claims_deny_anon" ON public.p1_transport_claims
    FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);
CREATE POLICY "p1_transport_claims_service_role_all" ON public.p1_transport_claims
    FOR ALL TO service_role USING (true) WITH CHECK (true);
