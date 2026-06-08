-- =====================================================================
-- P1 Staff Manager — ディーラー応募GSS連動（案A: 各大会対応・DB駆動）
-- 2026-06-08
--
-- 適用は Supabase ダッシュボード（SQL Editor）か CLI で中野さんが実行。
-- 既存テーブルには触れない（新規追加のみ）。
--
-- 【案A】大会(p1_events)ごとに応募フォーム(GSS)が分かれる前提。
--   - 「大会 ↔ GSS」の対応を p1_application_sources で持つ（アプリ画面でURL登録）。
--   - 1つのGASが全 active source を巡回し、各応募に event_id を付与して取り込む。
--   - 同じ人が複数大会に応募しうる → 採用時は既存スタッフ(同一メール)を再利用。
--
-- ⚠️ p1_dealer_applications は T2個人情報（本名/メール/生年月日/住所/電話）。RLS anon全拒否。
--    p1_application_sources は PII を含まない（GSSのIDのみ）。
-- =====================================================================

-- ---------- 大会 ↔ 応募フォーム(GSS) 対応表（案A の肝） ----------
CREATE TABLE IF NOT EXISTS p1_application_sources (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id        BIGINT NOT NULL REFERENCES p1_events(id),  -- 必須: どの大会か（null active を禁止）
    label           TEXT,                              -- 表示名（任意・例「OSAKA SUMMER」）
    spreadsheet_id  TEXT NOT NULL,                     -- GSS のID
    sheet_name      TEXT NOT NULL DEFAULT 'フォームの回答 1',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (spreadsheet_id, sheet_name)
);
COMMENT ON TABLE p1_application_sources IS
  '大会↔応募フォーム(GSS)対応。アプリ画面で登録し、GASがactiveを巡回して取込む。PIIなし。';

-- ---------- 応募の受け皿（event_id 付き） ----------
CREATE TABLE IF NOT EXISTS p1_dealer_applications (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_row_key  TEXT NOT NULL UNIQUE,    -- 冪等キー（GAS: spreadsheet_id+sheetId+行番号）
    source_row_hash TEXT,                    -- 行内容ハッシュ（変更検知）
    event_id        BIGINT REFERENCES p1_events(id),  -- どの大会への応募か（案A）
    applied_at      TIMESTAMPTZ,
    email           TEXT,
    name_jp         TEXT,
    real_name       TEXT,
    gender          TEXT,
    birthday        TEXT,
    address         TEXT,
    prefecture      TEXT,
    region          TEXT,
    nearest_station TEXT,
    role_hint       TEXT,
    can_mix         BOOLEAN DEFAULT FALSE,
    mix_games       TEXT,
    available_dates JSONB,                   -- 勤務可能日（配列）
    affiliation     TEXT,
    experience      TEXT,
    sns_x           TEXT,
    sns_other       TEXT,
    cash_on_day     TEXT,
    phone           TEXT,
    consent         TEXT,
    self_pr         TEXT,
    questions       TEXT,
    raw_payload     JSONB,                   -- 未知列・原文全体を退避
    status          TEXT NOT NULL DEFAULT 'new'
                    CHECK (status IN ('new','reviewed','accepted','rejected',
                                      'source_changed','source_missing')),
    promoted_staff_id BIGINT REFERENCES p1_staff(id),
    reviewed_by     TEXT,
    import_run_id   BIGINT,
    imported_at     TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
-- 既存DB（v2を適用済み等）でも列を確実に追加（再実行安全・index作成より前に置く）
ALTER TABLE p1_dealer_applications ADD COLUMN IF NOT EXISTS event_id BIGINT REFERENCES p1_events(id);
CREATE INDEX IF NOT EXISTS idx_dealer_apps_event  ON p1_dealer_applications(event_id);
CREATE INDEX IF NOT EXISTS idx_dealer_apps_status ON p1_dealer_applications(status);
CREATE INDEX IF NOT EXISTS idx_dealer_apps_email  ON p1_dealer_applications(email);
COMMENT ON TABLE p1_dealer_applications IS
  'ディーラー応募(GSS連動・大会別)。本名/メール/生年月日/住所/電話=T2個人情報。anon禁止。';

-- ---------- 取込実行ログ / 失敗行（dead-letter） ----------
CREATE TABLE IF NOT EXISTS p1_import_runs (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id      BIGINT,
    started_at    TIMESTAMPTZ DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    rows_seen     INT DEFAULT 0,
    rows_upserted INT DEFAULT 0,
    rows_failed   INT DEFAULT 0,
    note          TEXT
);
-- 既存DBでも event_id 列を確実に追加（Edge が import_runs.event_id に書き込むため）
ALTER TABLE p1_import_runs ADD COLUMN IF NOT EXISTS event_id BIGINT;
CREATE TABLE IF NOT EXISTS p1_import_errors (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    import_run_id  BIGINT,
    source_row_key TEXT,
    reason         TEXT,
    payload        JSONB,
    created_at     TIMESTAMPTZ DEFAULT now()
);

-- ---------- RLS ----------
-- 応募/取込ログ/エラー: anon 全拒否・service_role のみ（PIIを含む）
ALTER TABLE p1_dealer_applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE p1_import_runs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE p1_import_errors      ENABLE ROW LEVEL SECURITY;
-- 対応表: PIIなし。サービス側で読書きする想定（service_role）。
ALTER TABLE p1_application_sources ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname='dealer_apps_service_all') THEN
    CREATE POLICY dealer_apps_service_all ON p1_dealer_applications
      FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname='dealer_apps_deny_anon') THEN
    CREATE POLICY dealer_apps_deny_anon ON p1_dealer_applications
      FOR ALL TO anon USING (false) WITH CHECK (false);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname='import_runs_service_all') THEN
    CREATE POLICY import_runs_service_all ON p1_import_runs
      FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname='import_errors_service_all') THEN
    CREATE POLICY import_errors_service_all ON p1_import_errors
      FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname='app_sources_service_all') THEN
    CREATE POLICY app_sources_service_all ON p1_application_sources
      FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname='app_sources_deny_anon') THEN
    CREATE POLICY app_sources_deny_anon ON p1_application_sources
      FOR ALL TO anon USING (false) WITH CHECK (false);
  END IF;
END $$;

-- ---------- 採用昇格 RPC（冪等・トランザクション・スタッフ再利用） ----------
-- 応募1件を p1_staff へ昇格し、応募を accepted に更新するのを1トランザクションで行う。
--  - 既に accepted 済みなら既存スタッフIDを返す（二重昇格しない）。
--  - 同一メールの既存スタッフが居れば再利用する（同じ人が複数大会に応募する前提・案A）。
--  - prefecture/region は呼び出し側(Streamlit)が住所から address_to_region() で算出して渡す。
CREATE OR REPLACE FUNCTION promote_dealer_application(
    p_app_id BIGINT, p_operator TEXT,
    p_prefecture TEXT DEFAULT NULL, p_region TEXT DEFAULT NULL)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_app      p1_dealer_applications%ROWTYPE;
  v_staff_id BIGINT;
  v_next_no  INT;
BEGIN
  SELECT * INTO v_app FROM p1_dealer_applications WHERE id = p_app_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'application % not found', p_app_id;
  END IF;
  IF v_app.status = 'accepted' AND v_app.promoted_staff_id IS NOT NULL THEN
    RETURN v_app.promoted_staff_id;  -- 冪等
  END IF;
  IF v_app.status = 'rejected' THEN
    RAISE EXCEPTION 'application % is rejected', p_app_id;
  END IF;

  -- 昇格処理全体を直列化（同一メール同時昇格での重複作成・NO採番競合の両方を防ぐ）。
  -- 昇格は低頻度の管理者操作なので単一ロックで十分。reuse lookup より前に取得する。
  PERFORM pg_advisory_xact_lock(hashtext('p1_staff_promote'));

  -- 既存スタッフ再利用（同一メール・大文字小文字無視・有効なスタッフのみ）。
  -- 複数大会応募で同一人物の重複登録を防ぐ。非activeを再利用すると採用後も一覧に出ず
  -- 割当不能になるため active 限定。該当が無ければ下で新規作成する。
  -- is_active は環境により boolean/integer のため ::int で型非依存に比較。
  -- role='Dealer' に限定: 同一メールでも Floor/TD 等の既存スタッフを再利用すると、
  -- 支払・シフトがその役職で計算され誤支払になる。非Dealerは別人格として下で新規作成する。
  IF v_app.email IS NOT NULL AND v_app.email <> '' THEN
    SELECT id INTO v_staff_id FROM p1_staff
     WHERE lower(email) = lower(v_app.email) AND (is_active)::int = 1 AND role = 'Dealer'
     LIMIT 1;
  END IF;

  IF v_staff_id IS NULL THEN
    SELECT COALESCE(MAX(no), 0) + 1 INTO v_next_no FROM p1_staff;
    INSERT INTO p1_staff (
      no, name_jp, name_en, role, contact, notes,
      real_name, address, email, employment_type,
      nearest_station, prefecture, region
    ) VALUES (
      v_next_no,
      COALESCE(NULLIF(v_app.name_jp, ''), v_app.real_name, 'unknown'),
      '', 'Dealer',
      v_app.phone,
      NULLIF(CONCAT_WS(' / ',
        NULLIF(v_app.affiliation, ''),
        NULLIF(v_app.experience, ''),
        NULLIF(v_app.self_pr, '')), ''),
      v_app.real_name, v_app.address, v_app.email, 'contractor',
      v_app.nearest_station,
      COALESCE(p_prefecture, v_app.prefecture),
      COALESCE(p_region, v_app.region)
    ) RETURNING id INTO v_staff_id;
  END IF;

  UPDATE p1_dealer_applications
     SET status = 'accepted',
         promoted_staff_id = v_staff_id,
         reviewed_by = p_operator,
         updated_at = now()
   WHERE id = p_app_id;

  RETURN v_staff_id;
END $$;

-- service_role からのみ実行可能に（anon/authenticated/PUBLIC は明示剥奪）
REVOKE ALL ON FUNCTION promote_dealer_application(BIGINT, TEXT, TEXT, TEXT)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION promote_dealer_application(BIGINT, TEXT, TEXT, TEXT)
  TO service_role;
