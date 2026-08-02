-- =====================================================================
-- データ整合性のDB側ガード追加（2026-08-02）
-- =====================================================================
-- 外部エンジニアのDB点検で指摘された3件に対応する。
-- いずれもアプリの改修ではなくDB制約で塞ぐ（アプリ側のバグに依存しない防護）。
--
-- 適用前の実測（2026-08-02）:
--   ・p1_payments の (event_id, staff_id) 重複: 0件
--   ・p1_event_rates の (event_id, date) 重複: 0件
--   → 既存データに違反が無いため、制約追加はエラーなく通る
-- =====================================================================

-- ---------------------------------------------------------------------
-- 指摘1: スタッフ削除で契約書が連鎖削除される
-- ---------------------------------------------------------------------
-- p1_contracts.staff_id が ON DELETE CASCADE のため、スタッフを1行消すと
-- 締結済み契約書（署名・締結日時・内容ハッシュ）が確認なく道連れになる。
-- 契約書は報酬・労務の紛争時に会社を守る証拠なので、連鎖削除は不適切。
-- RESTRICT に変更し、契約書が残っている限りスタッフを削除できないようにする。
-- （p1_shifts / p1_payments は既に既定のRESTRICTなので挙動が揃う）
ALTER TABLE p1_contracts DROP CONSTRAINT IF EXISTS p1_contracts_staff_id_fkey;
ALTER TABLE p1_contracts
    ADD CONSTRAINT p1_contracts_staff_id_fkey
    FOREIGN KEY (staff_id) REFERENCES p1_staff(id) ON DELETE RESTRICT;

-- 同じ理由で、個別手当・交通費請求もスタッフ削除で消えないようにする
-- （金額の根拠資料であり、消えると支払額の説明がつかなくなる）
ALTER TABLE p1_staff_event_allowances DROP CONSTRAINT IF EXISTS p1_staff_event_allowances_staff_id_fkey;
ALTER TABLE p1_staff_event_allowances
    ADD CONSTRAINT p1_staff_event_allowances_staff_id_fkey
    FOREIGN KEY (staff_id) REFERENCES p1_staff(id) ON DELETE RESTRICT;

ALTER TABLE p1_transport_claims DROP CONSTRAINT IF EXISTS p1_transport_claims_staff_id_fkey;
ALTER TABLE p1_transport_claims
    ADD CONSTRAINT p1_transport_claims_staff_id_fkey
    FOREIGN KEY (staff_id) REFERENCES p1_staff(id) ON DELETE RESTRICT;

-- ---------------------------------------------------------------------
-- 指摘2: 同一イベント×同一スタッフの支払いを複数作れる
-- ---------------------------------------------------------------------
-- 交通費（p1_transport_claims）には UNIQUE(event_id, staff_id) があるのに、
-- 金額の大きい給与本体には無い。二重払いを構造的に防ぐため揃える。
ALTER TABLE p1_payments DROP CONSTRAINT IF EXISTS p1_payments_event_staff_key;
ALTER TABLE p1_payments
    ADD CONSTRAINT p1_payments_event_staff_key UNIQUE (event_id, staff_id);

-- ---------------------------------------------------------------------
-- 指摘3: 同じ日のレートを2件登録でき、どちらで計算されるか不定
-- ---------------------------------------------------------------------
ALTER TABLE p1_event_rates DROP CONSTRAINT IF EXISTS p1_event_rates_event_date_key;
ALTER TABLE p1_event_rates
    ADD CONSTRAINT p1_event_rates_event_date_key UNIQUE (event_id, date);

-- =====================================================================
-- 確認用:
--   SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
--   WHERE conrelid IN ('p1_contracts'::regclass,'p1_payments'::regclass,
--                      'p1_event_rates'::regclass);
-- =====================================================================
