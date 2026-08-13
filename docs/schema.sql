-- ======================================================================
-- P1 Staff Manager — データベース スキーマ定義（DDL）
-- ======================================================================
-- 生成日時   : 2026-08-06 (JST)
-- 対象コード : p1-staff-manager @ 245b1b1
-- データベース : PostgreSQL（Supabase・他事業と同居のため p1_ 接頭辞のみ収録）
--
-- 生成方法   : 本番データベースの PostgREST スキーマ内省から自動生成
--              （列・型・既定値・NOT NULL・主キー・外部キーは live の実測値）
--              索引とRLSポリシーは docs/db_migrations/*.sql の適用済み定義を収録
--              ※前版(2026-07-31)は列3件とテーブル1件が欠落していたため再生成
--
-- 収録       : テーブル 15 / 列 197 / 外部キー 14
-- ======================================================================

SET search_path = public;

-- ---------------------------------------------------------------------
-- p1_admin_totp  … 管理者の2要素認証設定
--   行数(概算): 0 ／ 機微度: T3（TOTPシークレット＝認証情報）
-- ---------------------------------------------------------------------
CREATE TABLE p1_admin_totp (
    id bigint DEFAULT nextval('p1_admin_totp_id_seq'::regclass) NOT NULL,
    account text NOT NULL,
    secret text NOT NULL,
    enabled integer DEFAULT 0 NOT NULL,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    CONSTRAINT p1_admin_totp_pkey PRIMARY KEY (id)
);
ALTER TABLE p1_admin_totp ENABLE ROW LEVEL SECURITY;
CREATE POLICY "p1_admin_totp_deny_anon" ON p1_admin_totp FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);   -- 20260731_lock_down_p1_tables.sql
CREATE POLICY "p1_admin_totp_service_role_all" ON p1_admin_totp FOR ALL TO service_role USING (true) WITH CHECK (true);   -- 20260731_lock_down_p1_tables.sql

-- ---------------------------------------------------------------------
-- p1_app_users  … ログインアカウント（個人アカウント方式）
--   行数(概算): 2 ／ 機微度: T3（パスワードハッシュ＝認証情報）
-- ---------------------------------------------------------------------
CREATE TABLE p1_app_users (
    id bigint DEFAULT nextval('p1_app_users_id_seq'::regclass) NOT NULL,
    username text NOT NULL,
    display_name text DEFAULT ''::text NOT NULL,
    password_hash text NOT NULL,
    role text DEFAULT 'viewer'::text NOT NULL,
    active integer DEFAULT 1 NOT NULL,
    must_change_password integer DEFAULT 1 NOT NULL,
    created_by text DEFAULT ''::text NOT NULL,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    last_login_at timestamptz,
    CONSTRAINT p1_app_users_pkey PRIMARY KEY (id)
);
CREATE INDEX idx_p1_app_users_lookup ON p1_app_users (active, username);   -- 20260729_add_app_users.sql
ALTER TABLE p1_app_users ENABLE ROW LEVEL SECURITY;
CREATE POLICY "p1_app_users_deny_anon" ON p1_app_users FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);   -- 20260731_lock_down_p1_tables.sql
CREATE POLICY "p1_app_users_service_role_all" ON p1_app_users FOR ALL TO service_role USING (true) WITH CHECK (true);   -- 20260731_lock_down_p1_tables.sql

-- ---------------------------------------------------------------------
-- p1_audit_log  … 監査ログ（誰が・いつ・何をしたか）
--   行数(概算): 2453 ／ 機微度: T1（操作者名を含む）
-- ---------------------------------------------------------------------
CREATE TABLE p1_audit_log (
    id integer DEFAULT nextval('p1_audit_log_id_seq'::regclass) NOT NULL,
    event_id integer,
    action text NOT NULL,
    target_type text NOT NULL,
    target_id integer,
    detail text,
    performed_by text DEFAULT 'system'::text,
    created_at timestamp DEFAULT now(),
    CONSTRAINT p1_audit_log_pkey PRIMARY KEY (id)
);
ALTER TABLE p1_audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "p1_audit_log_deny_anon" ON p1_audit_log FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);   -- 20260731_lock_down_p1_tables.sql
CREATE POLICY "p1_audit_log_service_role_all" ON p1_audit_log FOR ALL TO service_role USING (true) WITH CHECK (true);   -- 20260731_lock_down_p1_tables.sql

-- ---------------------------------------------------------------------
-- p1_contract_templates  … 契約書テンプレート（本文Markdown）
--   行数(概算): 2
-- ---------------------------------------------------------------------
CREATE TABLE p1_contract_templates (
    id integer DEFAULT nextval('p1_contract_templates_id_seq'::regclass) NOT NULL,
    name text NOT NULL,
    version text DEFAULT 'v1.0'::text NOT NULL,
    doc_type text DEFAULT 'outsourcing'::text NOT NULL,
    body_markdown text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    is_active integer DEFAULT 1,
    is_provisional integer DEFAULT 1,
    CONSTRAINT p1_contract_templates_pkey PRIMARY KEY (id)
);
CREATE INDEX idx_contract_templates_provisional ON p1_contract_templates (is_provisional);   -- 20260421_add_contract_provisional.sql
ALTER TABLE p1_contract_templates ENABLE ROW LEVEL SECURITY;
CREATE POLICY "p1_contract_templates_deny_anon" ON p1_contract_templates FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);   -- 20260731_lock_down_p1_tables.sql
CREATE POLICY "p1_contract_templates_service_role_all" ON p1_contract_templates FOR ALL TO service_role USING (true) WITH CHECK (true);   -- 20260731_lock_down_p1_tables.sql

-- ---------------------------------------------------------------------
-- p1_contracts  … 発行済み契約書と電子署名の記録
--   行数(概算): 0 ／ 機微度: T2（署名画像・IP・UA＝個人情報）
-- ---------------------------------------------------------------------
CREATE TABLE p1_contracts (
    id integer DEFAULT nextval('p1_contracts_id_seq'::regclass) NOT NULL,
    template_id integer,
    staff_id integer,
    event_id integer,
    contract_no text NOT NULL,
    status text DEFAULT 'draft'::text,
    unsigned_pdf_path text,
    signed_pdf_path text,
    signing_token text,
    signing_token_expires_at timestamptz,
    sent_at timestamptz,
    viewed_at timestamptz,
    view_count integer DEFAULT 0,
    signed_at timestamptz,
    signer_ip text,
    signer_user_agent text,
    signature_image_path text,
    content_hash text,
    revoked_at timestamptz,
    revoke_reason text,
    variables_json text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    rendered_body_md text,
    template_version text,
    template_name_snapshot text,
    CONSTRAINT p1_contracts_pkey PRIMARY KEY (id),
    CONSTRAINT p1_contracts_template_id_fkey FOREIGN KEY (template_id) REFERENCES p1_contract_templates(id),
    CONSTRAINT p1_contracts_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES p1_staff(id) ON DELETE RESTRICT,
    CONSTRAINT p1_contracts_event_id_fkey FOREIGN KEY (event_id) REFERENCES p1_events(id)
);
CREATE INDEX idx_contracts_token ON p1_contracts (signing_token);   -- 20260417_02_add_contract_tables.sql
CREATE INDEX idx_contracts_staff ON p1_contracts (staff_id);   -- 20260417_02_add_contract_tables.sql
CREATE INDEX idx_contracts_status ON p1_contracts (status);   -- 20260417_02_add_contract_tables.sql
ALTER TABLE p1_contracts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "p1_contracts_deny_anon" ON p1_contracts FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);   -- 20260731_lock_down_p1_tables.sql
CREATE POLICY "p1_contracts_service_role_all" ON p1_contracts FOR ALL TO service_role USING (true) WITH CHECK (true);   -- 20260731_lock_down_p1_tables.sql

-- ---------------------------------------------------------------------
-- p1_day_codes  … 当日運用コード（現場端末の入場コード）
--   行数(概算): 10 ／ 機微度: T3（当日運用コード＝認証情報）
-- ---------------------------------------------------------------------
CREATE TABLE p1_day_codes (
    id bigint DEFAULT nextval('p1_day_codes_id_seq'::regclass) NOT NULL,
    code_hash text NOT NULL,
    label text DEFAULT ''::text NOT NULL,
    valid_date date NOT NULL,
    expires_at timestamptz NOT NULL,
    active integer DEFAULT 1 NOT NULL,
    created_by text DEFAULT ''::text NOT NULL,
    created_at timestamptz DEFAULT now(),
    CONSTRAINT p1_day_codes_pkey PRIMARY KEY (id)
);
CREATE INDEX idx_p1_day_codes_lookup ON p1_day_codes (active, code_hash);   -- 20260728_add_day_codes_and_totp.sql
ALTER TABLE p1_day_codes ENABLE ROW LEVEL SECURITY;
CREATE POLICY "p1_day_codes_deny_anon" ON p1_day_codes FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);   -- 20260731_lock_down_p1_tables.sql
CREATE POLICY "p1_day_codes_service_role_all" ON p1_day_codes FOR ALL TO service_role USING (true) WITH CHECK (true);   -- 20260731_lock_down_p1_tables.sql

-- ---------------------------------------------------------------------
-- p1_event_rates  … 日別の単価（時給・深夜・手当）
--   行数(概算): 5
-- ---------------------------------------------------------------------
CREATE TABLE p1_event_rates (
    id integer DEFAULT nextval('p1_event_rates_id_seq'::regclass) NOT NULL,
    event_id integer NOT NULL,
    date text NOT NULL,
    date_label text DEFAULT 'regular'::text,
    hourly_rate integer DEFAULT 1500 NOT NULL,
    night_rate integer DEFAULT 1875 NOT NULL,
    transport_allowance integer DEFAULT 1000 NOT NULL,
    floor_bonus integer DEFAULT 3000 NOT NULL,
    mix_bonus integer DEFAULT 1500 NOT NULL,
    CONSTRAINT p1_event_rates_pkey PRIMARY KEY (id),
    CONSTRAINT p1_event_rates_event_id_fkey FOREIGN KEY (event_id) REFERENCES p1_events(id)
);
ALTER TABLE p1_event_rates ADD CONSTRAINT p1_event_rates_event_date_key UNIQUE (event_id, date);   -- 20260802_add_integrity_guards.sql
ALTER TABLE p1_event_rates ENABLE ROW LEVEL SECURITY;
CREATE POLICY "p1_event_rates_deny_anon" ON p1_event_rates FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);   -- 20260731_lock_down_p1_tables.sql
CREATE POLICY "p1_event_rates_service_role_all" ON p1_event_rates FOR ALL TO service_role USING (true) WITH CHECK (true);   -- 20260731_lock_down_p1_tables.sql

-- ---------------------------------------------------------------------
-- p1_event_transport_rules  … 地域別の交通費ルール（11地域）
--   行数(概算): 12
-- ---------------------------------------------------------------------
CREATE TABLE p1_event_transport_rules (
    id integer DEFAULT nextval('p1_event_transport_rules_id_seq'::regclass) NOT NULL,
    event_id integer NOT NULL,
    region text NOT NULL,
    max_amount integer DEFAULT 0 NOT NULL,
    receipt_required integer DEFAULT 1 NOT NULL,
    is_venue_region integer DEFAULT 0 NOT NULL,
    note text,
    CONSTRAINT p1_event_transport_rules_pkey PRIMARY KEY (id),
    CONSTRAINT p1_event_transport_rules_event_id_fkey FOREIGN KEY (event_id) REFERENCES p1_events(id)
);
ALTER TABLE p1_event_transport_rules ENABLE ROW LEVEL SECURITY;
CREATE POLICY "p1_event_transport_rules_deny_anon" ON p1_event_transport_rules FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);   -- 20260731_lock_down_p1_tables.sql
CREATE POLICY "p1_event_transport_rules_service_role_all" ON p1_event_transport_rules FOR ALL TO service_role USING (true) WITH CHECK (true);   -- 20260731_lock_down_p1_tables.sql

-- ---------------------------------------------------------------------
-- p1_events  … 大会（イベント）マスター。すべての金額計算の起点
--   行数(概算): 1
-- ---------------------------------------------------------------------
CREATE TABLE p1_events (
    id integer DEFAULT nextval('p1_events_id_seq'::regclass) NOT NULL,
    name text NOT NULL,
    venue text,
    start_date text NOT NULL,
    end_date text NOT NULL,
    break_minutes_6h integer DEFAULT 45 NOT NULL,
    break_minutes_8h integer DEFAULT 60 NOT NULL,
    created_at timestamp DEFAULT now(),
    issuer_name text DEFAULT '株式会社パシフィック'::text,
    issuer_address text,
    issuer_tel text,
    invoice_number text,
    issuer_seal_url text,
    receipt_purpose text DEFAULT 'ポーカー大会運営業務委託費として'::text,
    show_tax_breakdown integer DEFAULT 0,
    prefecture text,
    rate_template_id text DEFAULT ''::text,
    rounding_unit integer DEFAULT 0,
    CONSTRAINT p1_events_pkey PRIMARY KEY (id)
);
ALTER TABLE p1_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "p1_events_deny_anon" ON p1_events FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);   -- 20260731_lock_down_p1_tables.sql
CREATE POLICY "p1_events_service_role_all" ON p1_events FOR ALL TO service_role USING (true) WITH CHECK (true);   -- 20260731_lock_down_p1_tables.sql

-- ---------------------------------------------------------------------
-- p1_payments  … 支払い（確定額・承認状態・領収書トークン）
--   行数(概算): 0 ／ 機微度: T2（報酬額＝給与情報。領収書トークンを含む）
-- ---------------------------------------------------------------------
CREATE TABLE p1_payments (
    id integer DEFAULT nextval('p1_payments_id_seq'::regclass) NOT NULL,
    event_id integer NOT NULL,
    staff_id integer NOT NULL,
    base_pay integer DEFAULT 0 NOT NULL,
    night_pay integer DEFAULT 0 NOT NULL,
    transport_total integer DEFAULT 0 NOT NULL,
    floor_bonus_total integer DEFAULT 0 NOT NULL,
    mix_bonus_total integer DEFAULT 0 NOT NULL,
    attendance_bonus integer DEFAULT 0 NOT NULL,
    break_deduction integer DEFAULT 0 NOT NULL,
    adjustment integer DEFAULT 0 NOT NULL,
    adjustment_note text,
    total_amount integer DEFAULT 0 NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    approved_by text,
    approved_at timestamp,
    receipt_received integer DEFAULT 0 NOT NULL,
    paid_at timestamp,
    created_at timestamp DEFAULT now(),
    notes text,
    receipt_pdf_path text,
    receipt_token text,
    receipt_token_expires_at timestamptz,
    receipt_generated_at timestamptz,
    receipt_downloaded_at timestamptz,
    receipt_download_count integer DEFAULT 0,
    receipt_no text,
    receipt_original_path text,
    payable_amount integer,
    CONSTRAINT p1_payments_pkey PRIMARY KEY (id),
    CONSTRAINT p1_payments_event_id_fkey FOREIGN KEY (event_id) REFERENCES p1_events(id),
    CONSTRAINT p1_payments_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES p1_staff(id)
);
CREATE INDEX idx_payments_receipt_token ON p1_payments (receipt_token);   -- 20260417_add_receipt_columns.sql
ALTER TABLE p1_payments ADD CONSTRAINT p1_payments_event_staff_key UNIQUE (event_id, staff_id);   -- 20260802_add_integrity_guards.sql
ALTER TABLE p1_payments ENABLE ROW LEVEL SECURITY;
CREATE POLICY "p1_payments_deny_anon" ON p1_payments FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);   -- 20260731_lock_down_p1_tables.sql
CREATE POLICY "p1_payments_service_role_all" ON p1_payments FOR ALL TO service_role USING (true) WITH CHECK (true);   -- 20260731_lock_down_p1_tables.sql

-- ---------------------------------------------------------------------
-- p1_petty_cash  … 小口現金の出納
--   行数(概算): 0 ／ 機微度: T1（金額）
-- ---------------------------------------------------------------------
CREATE TABLE p1_petty_cash (
    id integer DEFAULT nextval('p1_petty_cash_id_seq'::regclass) NOT NULL,
    event_id integer NOT NULL,
    date text NOT NULL,
    description text NOT NULL,
    amount integer NOT NULL,
    requester text,
    approver text,
    status text DEFAULT 'pending'::text NOT NULL,
    receipt_received integer DEFAULT 0 NOT NULL,
    created_at timestamp DEFAULT now(),
    CONSTRAINT p1_petty_cash_pkey PRIMARY KEY (id),
    CONSTRAINT p1_petty_cash_event_id_fkey FOREIGN KEY (event_id) REFERENCES p1_events(id)
);
ALTER TABLE p1_petty_cash ENABLE ROW LEVEL SECURITY;
CREATE POLICY "p1_petty_cash_deny_anon" ON p1_petty_cash FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);   -- 20260731_lock_down_p1_tables.sql
CREATE POLICY "p1_petty_cash_service_role_all" ON p1_petty_cash FOR ALL TO service_role USING (true) WITH CHECK (true);   -- 20260731_lock_down_p1_tables.sql

-- ---------------------------------------------------------------------
-- p1_shifts  … シフトと出退勤実績（予定/実績/欠勤・食事配布状況）
--   行数(概算): 641
-- ---------------------------------------------------------------------
CREATE TABLE p1_shifts (
    id integer DEFAULT nextval('p1_shifts_id_seq'::regclass) NOT NULL,
    event_id integer NOT NULL,
    staff_id integer NOT NULL,
    date text NOT NULL,
    planned_start text,
    planned_end text,
    actual_start text,
    actual_end text,
    is_mix integer DEFAULT 0 NOT NULL,
    status text DEFAULT 'scheduled'::text NOT NULL,
    notes text,
    lunch_status text DEFAULT 'pending'::text NOT NULL,
    lunch_status_at timestamptz,
    lunch_status_by text DEFAULT ''::text NOT NULL,
    lunch2_status text DEFAULT 'pending'::text NOT NULL,
    lunch2_status_at timestamptz,
    lunch2_status_by text DEFAULT ''::text NOT NULL,
    drink_status text DEFAULT 'pending'::text NOT NULL,
    drink_status_at timestamptz,
    drink_status_by text DEFAULT ''::text NOT NULL,
    CONSTRAINT p1_shifts_pkey PRIMARY KEY (id),
    CONSTRAINT p1_shifts_event_id_fkey FOREIGN KEY (event_id) REFERENCES p1_events(id),
    CONSTRAINT p1_shifts_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES p1_staff(id)
);
CREATE INDEX idx_p1_shifts_event_date_lunch ON p1_shifts (event_id, date, lunch_status);   -- 20260618_add_lunch_status.sql
CREATE INDEX idx_p1_shifts_event_date_lunch2 ON p1_shifts (event_id, date, lunch2_status);   -- 20260702_add_lunch2_drink_status.sql
CREATE INDEX idx_p1_shifts_event_date_drink ON p1_shifts (event_id, date, drink_status);   -- 20260702_add_lunch2_drink_status.sql
ALTER TABLE p1_shifts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "p1_shifts_deny_anon" ON p1_shifts FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);   -- 20260731_lock_down_p1_tables.sql
CREATE POLICY "p1_shifts_service_role_all" ON p1_shifts FOR ALL TO service_role USING (true) WITH CHECK (true);   -- 20260731_lock_down_p1_tables.sql

-- ---------------------------------------------------------------------
-- p1_staff  … スタッフ台帳。氏名・住所・地域・雇用区分
--   行数(概算): 149 ／ 機微度: T2（本名・住所・メール・電話＝個人情報）
-- ---------------------------------------------------------------------
CREATE TABLE p1_staff (
    id integer DEFAULT nextval('p1_staff_id_seq'::regclass) NOT NULL,
    no integer,
    name_jp text NOT NULL,
    name_en text,
    role text DEFAULT 'Dealer'::text NOT NULL,
    contact text,
    notes text,
    is_active integer DEFAULT 1 NOT NULL,
    created_at timestamp DEFAULT now(),
    updated_at timestamp DEFAULT now(),
    real_name text,
    address text,
    email text,
    employment_type text DEFAULT 'contractor'::text,
    custom_hourly_rate integer,
    nearest_station text,
    prefecture text,
    region text,
    CONSTRAINT p1_staff_pkey PRIMARY KEY (id)
);
ALTER TABLE p1_staff ENABLE ROW LEVEL SECURITY;
CREATE POLICY "p1_staff_deny_anon" ON p1_staff FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);   -- 20260731_lock_down_p1_tables.sql
CREATE POLICY "p1_staff_service_role_all" ON p1_staff FOR ALL TO service_role USING (true) WITH CHECK (true);   -- 20260731_lock_down_p1_tables.sql

-- ---------------------------------------------------------------------
-- p1_staff_event_allowances  … 個別手当（スタッフ×大会ごとの臨時支給）
--   行数(概算): 0 ／ 機微度: T1（金額）
-- ---------------------------------------------------------------------
CREATE TABLE p1_staff_event_allowances (
    id bigint DEFAULT nextval('p1_staff_event_allowances_id_seq'::regclass) NOT NULL,
    event_id bigint NOT NULL,
    staff_id bigint NOT NULL,
    allowance_type text NOT NULL,
    label text DEFAULT ''::text NOT NULL,
    amount integer DEFAULT 0 NOT NULL,
    is_off_record integer DEFAULT 0 NOT NULL,
    note text DEFAULT ''::text NOT NULL,
    created_at timestamptz DEFAULT now() NOT NULL,
    created_by text DEFAULT ''::text NOT NULL,
    CONSTRAINT p1_staff_event_allowances_pkey PRIMARY KEY (id),
    CONSTRAINT p1_staff_event_allowances_event_id_fkey FOREIGN KEY (event_id) REFERENCES p1_events(id),
    CONSTRAINT p1_staff_event_allowances_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES p1_staff(id) ON DELETE RESTRICT
);
CREATE INDEX idx_p1_staff_event_allowances_event_staff ON p1_staff_event_allowances (event_id, staff_id);   -- 20260508_add_individual_allowances.sql
ALTER TABLE p1_staff_event_allowances ENABLE ROW LEVEL SECURITY;
CREATE POLICY "p1_allowances_deny_anon" ON p1_staff_event_allowances FOR ALL TO anon USING (false) WITH CHECK (false);   -- 20260508_add_individual_allowances.sql
CREATE POLICY "p1_allowances_service_role_all" ON p1_staff_event_allowances FOR ALL TO service_role USING (true) WITH CHECK (true);   -- 20260508_add_individual_allowances.sql

-- ---------------------------------------------------------------------
-- p1_transport_claims  … 交通費の領収書と精算額
--   行数(概算): 5 ／ 機微度: T1（金額）
-- ---------------------------------------------------------------------
CREATE TABLE p1_transport_claims (
    id integer DEFAULT nextval('p1_transport_claims_id_seq'::regclass) NOT NULL,
    event_id integer NOT NULL,
    staff_id integer NOT NULL,
    receipt_amount integer DEFAULT 0 NOT NULL,
    approved_amount integer DEFAULT 0 NOT NULL,
    has_receipt integer DEFAULT 0 NOT NULL,
    note text,
    updated_at timestamp DEFAULT now(),
    CONSTRAINT p1_transport_claims_pkey PRIMARY KEY (id),
    CONSTRAINT p1_transport_claims_event_id_fkey FOREIGN KEY (event_id) REFERENCES p1_events(id),
    CONSTRAINT p1_transport_claims_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES p1_staff(id) ON DELETE RESTRICT
);
ALTER TABLE p1_transport_claims ENABLE ROW LEVEL SECURITY;
CREATE POLICY "p1_transport_claims_deny_anon" ON p1_transport_claims FOR ALL TO anon, authenticated USING (false) WITH CHECK (false);   -- 20260731_lock_down_p1_tables.sql
CREATE POLICY "p1_transport_claims_service_role_all" ON p1_transport_claims FOR ALL TO service_role USING (true) WITH CHECK (true);   -- 20260731_lock_down_p1_tables.sql

-- ======================================================================
-- 補足
-- ======================================================================
-- ・全 p1_ テーブルは anon / authenticated ロールの権限を剥奪済み
--   （docs/db_migrations/20260731_lock_down_p1_tables.sql）。
--   アプリは service_role キーでのみ接続する。
-- ・時刻列は文字列型（text）で 'HH:MM' 形式。深夜跨ぎは 24 時超え表記
--   （例 '27:00' = 翌3時）を用いるため、time型ではなく text で保持している。
-- ・日付列も text（'YYYY-MM-DD'）。既存データとの互換のため型変更していない。
