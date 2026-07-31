-- =====================================================================
-- P1 Staff Manager — データベース スキーマ定義（DDL）
-- =====================================================================
-- 生成日時   : 2026-07-31 12:48:21 (JST)
-- データベース: PostgreSQL 17.6
-- 生成方法   : 本番データベースのシステムカタログ (pg_catalog) から自動生成
--              pg_dump --schema-only と同等の内容です
--
-- 対象範囲   : 本システムが使用するテーブルのみ（プレフィックス p1_）
--              ※本データベースは他事業と同居しているため、無関係な
--                テーブルは意図的に含めていません
--
-- 収録内容   : テーブル 14 / 列 183 / 制約 37
--              索引 32 / RLSポリシー 11 / トリガー 0
-- =====================================================================

SET search_path = public;

-- ---------------------------------------------------------------------
-- p1_admin_totp  … 管理者2要素認証
-- ---------------------------------------------------------------------
CREATE TABLE p1_admin_totp (
    id bigint DEFAULT nextval('p1_admin_totp_id_seq'::regclass) NOT NULL,
    account text NOT NULL,
    secret text NOT NULL,
    enabled integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    CONSTRAINT p1_admin_totp_account_key UNIQUE (account),
    CONSTRAINT p1_admin_totp_pkey PRIMARY KEY (id)
);

-- ⚠️ p1_admin_totp: 行レベルセキュリティ(RLS)は無効

-- ---------------------------------------------------------------------
-- p1_app_users  … アプリユーザー（個人アカウント）
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
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    last_login_at timestamp with time zone,
    CONSTRAINT p1_app_users_username_key UNIQUE (username),
    CONSTRAINT p1_app_users_pkey PRIMARY KEY (id)
);

CREATE INDEX idx_p1_app_users_lookup ON public.p1_app_users USING btree (active, username);

ALTER TABLE p1_app_users ENABLE ROW LEVEL SECURITY;
CREATE POLICY "p1_app_users_deny_anon" ON p1_app_users
    FOR ALL TO anon
    USING (false)
    WITH CHECK (false);
CREATE POLICY "p1_app_users_service_role_all" ON p1_app_users
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- ---------------------------------------------------------------------
-- p1_audit_log  … 監査ログ
-- ---------------------------------------------------------------------
CREATE TABLE p1_audit_log (
    id integer DEFAULT nextval('p1_audit_log_id_seq'::regclass) NOT NULL,
    event_id integer,
    action text NOT NULL,
    target_type text NOT NULL,
    target_id integer,
    detail text,
    performed_by text DEFAULT 'system'::text,
    created_at timestamp without time zone DEFAULT now(),
    CONSTRAINT p1_audit_log_pkey PRIMARY KEY (id)
);

ALTER TABLE p1_audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow_all" ON p1_audit_log
    FOR ALL TO public
    USING (true)
    WITH CHECK (true);

-- ---------------------------------------------------------------------
-- p1_contract_templates  … 契約書テンプレート
-- ---------------------------------------------------------------------
CREATE TABLE p1_contract_templates (
    id integer DEFAULT nextval('p1_contract_templates_id_seq'::regclass) NOT NULL,
    name text NOT NULL,
    version text DEFAULT 'v1.0'::text NOT NULL,
    doc_type text DEFAULT 'outsourcing'::text NOT NULL,
    body_markdown text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_active integer DEFAULT 1,
    is_provisional integer DEFAULT 1,
    CONSTRAINT p1_contract_templates_pkey PRIMARY KEY (id)
);

CREATE INDEX idx_contract_templates_provisional ON public.p1_contract_templates USING btree (is_provisional);

-- ⚠️ p1_contract_templates: 行レベルセキュリティ(RLS)は無効

-- ---------------------------------------------------------------------
-- p1_contracts  … 発行済み契約書
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
    signing_token_expires_at timestamp with time zone,
    sent_at timestamp with time zone,
    viewed_at timestamp with time zone,
    view_count integer DEFAULT 0,
    signed_at timestamp with time zone,
    signer_ip text,
    signer_user_agent text,
    signature_image_path text,
    content_hash text,
    revoked_at timestamp with time zone,
    revoke_reason text,
    variables_json text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    rendered_body_md text,
    template_version text,
    template_name_snapshot text,
    CONSTRAINT p1_contracts_contract_no_key UNIQUE (contract_no),
    CONSTRAINT p1_contracts_signing_token_key UNIQUE (signing_token),
    CONSTRAINT p1_contracts_pkey PRIMARY KEY (id),
    CONSTRAINT p1_contracts_event_id_fkey FOREIGN KEY (event_id) REFERENCES p1_events(id) ON DELETE SET NULL,
    CONSTRAINT p1_contracts_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES p1_staff(id) ON DELETE CASCADE,
    CONSTRAINT p1_contracts_template_id_fkey FOREIGN KEY (template_id) REFERENCES p1_contract_templates(id) ON DELETE SET NULL
);

CREATE INDEX idx_contracts_staff ON public.p1_contracts USING btree (staff_id);
CREATE INDEX idx_contracts_status ON public.p1_contracts USING btree (status);
CREATE INDEX idx_contracts_token ON public.p1_contracts USING btree (signing_token) WHERE (signing_token IS NOT NULL);

-- ⚠️ p1_contracts: 行レベルセキュリティ(RLS)は無効

-- ---------------------------------------------------------------------
-- p1_day_codes  … 当日運用コード
-- ---------------------------------------------------------------------
CREATE TABLE p1_day_codes (
    id bigint DEFAULT nextval('p1_day_codes_id_seq'::regclass) NOT NULL,
    code_hash text NOT NULL,
    label text DEFAULT ''::text NOT NULL,
    valid_date date NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    active integer DEFAULT 1 NOT NULL,
    created_by text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT p1_day_codes_pkey PRIMARY KEY (id)
);

CREATE INDEX idx_p1_day_codes_lookup ON public.p1_day_codes USING btree (active, code_hash);

-- ⚠️ p1_day_codes: 行レベルセキュリティ(RLS)は無効

-- ---------------------------------------------------------------------
-- p1_event_rates  … 日別レート
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

ALTER TABLE p1_event_rates ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow_all" ON p1_event_rates
    FOR ALL TO public
    USING (true)
    WITH CHECK (true);

-- ---------------------------------------------------------------------
-- p1_event_transport_rules  … 地域別 交通費ルール
-- ---------------------------------------------------------------------
CREATE TABLE p1_event_transport_rules (
    id integer DEFAULT nextval('p1_event_transport_rules_id_seq'::regclass) NOT NULL,
    event_id integer NOT NULL,
    region text NOT NULL,
    max_amount integer DEFAULT 0 NOT NULL,
    receipt_required integer DEFAULT 1 NOT NULL,
    is_venue_region integer DEFAULT 0 NOT NULL,
    note text,
    CONSTRAINT p1_event_transport_rules_event_id_region_key UNIQUE (event_id, region),
    CONSTRAINT p1_event_transport_rules_pkey PRIMARY KEY (id),
    CONSTRAINT p1_event_transport_rules_event_id_fkey FOREIGN KEY (event_id) REFERENCES p1_events(id) ON DELETE CASCADE
);

ALTER TABLE p1_event_transport_rules ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow_all" ON p1_event_transport_rules
    FOR ALL TO public
    USING (true)
    WITH CHECK (true);

-- ---------------------------------------------------------------------
-- p1_events  … イベント（大会）マスター
-- ---------------------------------------------------------------------
CREATE TABLE p1_events (
    id integer DEFAULT nextval('p1_events_id_seq'::regclass) NOT NULL,
    name text NOT NULL,
    venue text,
    start_date text NOT NULL,
    end_date text NOT NULL,
    break_minutes_6h integer DEFAULT 45 NOT NULL,
    break_minutes_8h integer DEFAULT 60 NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    issuer_name text DEFAULT '株式会社パシフィック'::text,
    issuer_address text,
    issuer_tel text,
    invoice_number text,
    issuer_seal_url text,
    receipt_purpose text DEFAULT 'ポーカー大会運営業務委託費として'::text,
    show_tax_breakdown integer DEFAULT 0,
    CONSTRAINT p1_events_pkey PRIMARY KEY (id)
);

ALTER TABLE p1_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow_all" ON p1_events
    FOR ALL TO public
    USING (true)
    WITH CHECK (true);

-- ---------------------------------------------------------------------
-- p1_payments  … 支払い
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
    approved_at timestamp without time zone,
    receipt_received integer DEFAULT 0 NOT NULL,
    paid_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now(),
    notes text,
    receipt_pdf_path text,
    receipt_token text,
    receipt_token_expires_at timestamp with time zone,
    receipt_generated_at timestamp with time zone,
    receipt_downloaded_at timestamp with time zone,
    receipt_download_count integer DEFAULT 0,
    receipt_no text,
    receipt_original_path text,
    CONSTRAINT p1_payments_receipt_token_key UNIQUE (receipt_token),
    CONSTRAINT p1_payments_pkey PRIMARY KEY (id),
    CONSTRAINT p1_payments_event_id_fkey FOREIGN KEY (event_id) REFERENCES p1_events(id),
    CONSTRAINT p1_payments_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES p1_staff(id)
);

CREATE INDEX idx_payments_receipt_token ON public.p1_payments USING btree (receipt_token) WHERE (receipt_token IS NOT NULL);

ALTER TABLE p1_payments ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow_all" ON p1_payments
    FOR ALL TO public
    USING (true)
    WITH CHECK (true);

-- ---------------------------------------------------------------------
-- p1_petty_cash  … 小口経費
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
    created_at timestamp without time zone DEFAULT now(),
    CONSTRAINT p1_petty_cash_pkey PRIMARY KEY (id),
    CONSTRAINT p1_petty_cash_event_id_fkey FOREIGN KEY (event_id) REFERENCES p1_events(id)
);

ALTER TABLE p1_petty_cash ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow_all" ON p1_petty_cash
    FOR ALL TO public
    USING (true)
    WITH CHECK (true);

-- ---------------------------------------------------------------------
-- p1_shifts  … シフト・出退勤実績
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
    lunch_status_at timestamp with time zone,
    lunch_status_by text DEFAULT ''::text NOT NULL,
    lunch2_status text DEFAULT 'pending'::text NOT NULL,
    lunch2_status_at timestamp with time zone,
    lunch2_status_by text DEFAULT ''::text NOT NULL,
    drink_status text DEFAULT 'pending'::text NOT NULL,
    drink_status_at timestamp with time zone,
    drink_status_by text DEFAULT ''::text NOT NULL,
    CONSTRAINT p1_shifts_event_id_staff_id_date_key UNIQUE (event_id, staff_id, date),
    CONSTRAINT p1_shifts_pkey PRIMARY KEY (id),
    CONSTRAINT p1_shifts_event_id_fkey FOREIGN KEY (event_id) REFERENCES p1_events(id),
    CONSTRAINT p1_shifts_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES p1_staff(id),
    CONSTRAINT p1_shifts_drink_status_check CHECK ((drink_status = ANY (ARRAY['pending'::text, 'received'::text, 'cancelled'::text]))),
    CONSTRAINT p1_shifts_lunch2_status_check CHECK ((lunch2_status = ANY (ARRAY['pending'::text, 'received'::text, 'cancelled'::text]))),
    CONSTRAINT p1_shifts_lunch_status_check CHECK ((lunch_status = ANY (ARRAY['pending'::text, 'received'::text, 'cancelled'::text])))
);

CREATE INDEX idx_p1_shifts_event_date_drink ON public.p1_shifts USING btree (event_id, date, drink_status);
CREATE INDEX idx_p1_shifts_event_date_lunch ON public.p1_shifts USING btree (event_id, date, lunch_status);
CREATE INDEX idx_p1_shifts_event_date_lunch2 ON public.p1_shifts USING btree (event_id, date, lunch2_status);

ALTER TABLE p1_shifts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow_all" ON p1_shifts
    FOR ALL TO public
    USING (true)
    WITH CHECK (true);

-- ---------------------------------------------------------------------
-- p1_staff  … スタッフマスター
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
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
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
CREATE POLICY "allow_all" ON p1_staff
    FOR ALL TO public
    USING (true)
    WITH CHECK (true);

-- ---------------------------------------------------------------------
-- p1_transport_claims  … 交通費請求
-- ---------------------------------------------------------------------
CREATE TABLE p1_transport_claims (
    id integer DEFAULT nextval('p1_transport_claims_id_seq'::regclass) NOT NULL,
    event_id integer NOT NULL,
    staff_id integer NOT NULL,
    receipt_amount integer DEFAULT 0 NOT NULL,
    approved_amount integer DEFAULT 0 NOT NULL,
    has_receipt integer DEFAULT 0 NOT NULL,
    note text,
    updated_at timestamp without time zone DEFAULT now(),
    CONSTRAINT p1_transport_claims_event_id_staff_id_key UNIQUE (event_id, staff_id),
    CONSTRAINT p1_transport_claims_pkey PRIMARY KEY (id),
    CONSTRAINT p1_transport_claims_event_id_fkey FOREIGN KEY (event_id) REFERENCES p1_events(id) ON DELETE CASCADE,
    CONSTRAINT p1_transport_claims_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES p1_staff(id) ON DELETE CASCADE
);

ALTER TABLE p1_transport_claims ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow_all" ON p1_transport_claims
    FOR ALL TO public
    USING (true)
    WITH CHECK (true);

-- =====================================================================
-- 補足
-- =====================================================================
-- ・アプリケーションは service_role で接続し、DBへの直接アクセス経路は
--   公開していません（Basic認証つきリバースプロキシの内側からのみ到達）
-- ・認証情報を持つテーブル（p1_app_users / p1_day_codes / p1_admin_totp）は
--   RLSで anon ロールを拒否し、service_role のみ許可しています
-- ・パスワードと当日運用コードは平文を保存せず、
--   pbkdf2-hmac-sha256（ソルト付き）／SHA-256 のハッシュのみ保持します
-- =====================================================================
