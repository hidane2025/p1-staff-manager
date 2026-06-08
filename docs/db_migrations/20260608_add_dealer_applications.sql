-- =====================================================================
-- P1 Staff Manager — ディーラー応募GSS連動 受け皿（設計v2 §4 準拠）
-- 2026-06-08
--
-- 適用は Supabase ダッシュボード（SQL Editor）か CLI で中野さんが実行。
-- 既存テーブルには触れない（新規追加のみ）。
--
-- ⚠️ T2個人情報（本名/メール/生年月日/住所/電話）を保持する。RLSで anon 全拒否。
--    取込・昇格は service_role（Edge Function / RPC）からのみ行う。
-- =====================================================================

-- ---------- 応募の受け皿 ----------
CREATE TABLE IF NOT EXISTS p1_dealer_applications (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_row_key  TEXT NOT NULL UNIQUE,    -- 冪等キー（GAS側で生成: §5.3）
    source_row_hash TEXT,                    -- 行内容ハッシュ（変更検知）
    applied_at      TIMESTAMPTZ,             -- GSS タイムスタンプ
    email           TEXT,
    name_jp         TEXT,                    -- 活動名義（ディーラーネーム）
    real_name       TEXT,
    gender          TEXT,
    birthday        TEXT,
    address         TEXT,
    prefecture      TEXT,
    region          TEXT,
    nearest_station TEXT,
    role_hint       TEXT,                    -- 業務種別
    can_mix         BOOLEAN DEFAULT FALSE,
    mix_games       TEXT,                    -- 対応MIX種目（原文）
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
CREATE INDEX IF NOT EXISTS idx_dealer_apps_status ON p1_dealer_applications(status);
CREATE INDEX IF NOT EXISTS idx_dealer_apps_email  ON p1_dealer_applications(email);
COMMENT ON TABLE p1_dealer_applications IS
  'ディーラー応募(GSS連動)。本名/メール/生年月日/住所/電話=T2個人情報。anon禁止。';

-- ---------- 取込実行ログ / 失敗行（dead-letter） ----------
CREATE TABLE IF NOT EXISTS p1_import_runs (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at   TIMESTAMPTZ DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    rows_seen    INT DEFAULT 0,
    rows_upserted INT DEFAULT 0,
    rows_failed  INT DEFAULT 0,
    note         TEXT
);
CREATE TABLE IF NOT EXISTS p1_import_errors (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    import_run_id BIGINT,
    source_row_key TEXT,
    reason        TEXT,
    payload       JSONB,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- ---------- RLS（anon 全拒否・service_role のみ） ----------
ALTER TABLE p1_dealer_applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE p1_import_runs        ENABLE ROW LEVEL SECURITY;
ALTER TABLE p1_import_errors      ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  -- service_role: 全許可 / anon: 全拒否（3テーブル共通）
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
END $$;

-- ---------- 採用昇格 RPC（トランザクション・冪等／設計v2 §6・Codex P2-11） ----------
-- 応募1件を p1_staff へ昇格し、応募を accepted に更新するのを1トランザクションで行う。
-- 既に accepted 済みなら既存スタッフIDを返す（二重昇格しない）。
-- prefecture/region は呼び出し側(Streamlit)が住所から既存 address_to_region() で
-- 算出して渡す（交通費・支払が region キーで動くため・Codex P2）。未指定時は応募値を使う。
CREATE OR REPLACE FUNCTION promote_dealer_application(
    p_app_id BIGINT, p_operator TEXT,
    p_prefecture TEXT DEFAULT NULL, p_region TEXT DEFAULT NULL)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_app     p1_dealer_applications%ROWTYPE;
  v_staff_id BIGINT;
  v_next_no INT;
BEGIN
  SELECT * INTO v_app FROM p1_dealer_applications WHERE id = p_app_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'application % not found', p_app_id;
  END IF;

  -- 冪等: 既に採用済みなら既存スタッフIDを返す
  IF v_app.status = 'accepted' AND v_app.promoted_staff_id IS NOT NULL THEN
    RETURN v_app.promoted_staff_id;
  END IF;
  IF v_app.status = 'rejected' THEN
    RAISE EXCEPTION 'application % is rejected', p_app_id;
  END IF;

  -- NO 採番の競合を直列化（同時昇格での重複/一意制約違反を防ぐ・Codex P2）。
  -- トランザクション終了で自動解放されるアドバイザリロックを使う。
  PERFORM pg_advisory_xact_lock(hashtext('p1_staff_no_alloc'));
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

  UPDATE p1_dealer_applications
     SET status = 'accepted',
         promoted_staff_id = v_staff_id,
         reviewed_by = p_operator,
         updated_at = now()
   WHERE id = p_app_id;

  RETURN v_staff_id;
END $$;

-- service_role からのみ実行可能にする（anon/authenticated/PUBLIC は明示的に剥奪）。
REVOKE ALL ON FUNCTION promote_dealer_application(BIGINT, TEXT, TEXT, TEXT)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION promote_dealer_application(BIGINT, TEXT, TEXT, TEXT)
  TO service_role;
