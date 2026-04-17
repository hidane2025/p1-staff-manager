-- ============================================================
-- Contract Digitalization Migration (2026-04-17 Phase 2)
-- 契約書クラウド署名機能のためのスキーマ
-- ============================================================

-- 1. 契約書テンプレート
CREATE TABLE IF NOT EXISTS p1_contract_templates (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,                     -- "業務委託契約書 v1.0"
    version TEXT NOT NULL DEFAULT 'v1.0',
    doc_type TEXT NOT NULL DEFAULT 'outsourcing',  -- outsourcing/nda/privacy
    body_markdown TEXT,                     -- 契約書本文（Markdown / {{placeholder}} 対応）
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    is_active INT DEFAULT 1
);

-- 2. 契約書発行・署名履歴
CREATE TABLE IF NOT EXISTS p1_contracts (
    id SERIAL PRIMARY KEY,
    template_id INT REFERENCES p1_contract_templates(id) ON DELETE SET NULL,
    staff_id INT REFERENCES p1_staff(id) ON DELETE CASCADE,
    event_id INT REFERENCES p1_events(id) ON DELETE SET NULL,    -- 大会連動契約 or NULL
    contract_no TEXT UNIQUE NOT NULL,                            -- C-YYYYMMDD-T{template}-S{staff}
    status TEXT DEFAULT 'draft',                                 -- draft/sent/viewed/signed/expired/revoked
    unsigned_pdf_path TEXT,                                      -- 署名前PDFのStorageパス
    signed_pdf_path TEXT,                                        -- 署名済PDFのStorageパス
    signing_token TEXT UNIQUE,
    signing_token_expires_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    viewed_at TIMESTAMPTZ,
    view_count INT DEFAULT 0,
    signed_at TIMESTAMPTZ,
    signer_ip TEXT,
    signer_user_agent TEXT,
    signature_image_path TEXT,                                   -- 署名画像PNGのStorageパス
    content_hash TEXT,                                           -- SHA-256（改ざん検知）
    revoked_at TIMESTAMPTZ,
    revoke_reason TEXT,
    variables_json TEXT,                                         -- 埋め込み変数 {"staff_name": "...", ...}
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_contracts_token ON p1_contracts(signing_token)
    WHERE signing_token IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contracts_staff ON p1_contracts(staff_id);
CREATE INDEX IF NOT EXISTS idx_contracts_status ON p1_contracts(status);

-- 3. Storageバケット 'contracts' ポリシー
-- （バケット作成は後からダッシュボードで実施。RLSのみ事前投入可）
-- CREATE POLICY "allow_contracts_insert" ON storage.objects FOR INSERT
--     TO anon, authenticated WITH CHECK (bucket_id = 'contracts');
-- CREATE POLICY "allow_contracts_select" ON storage.objects FOR SELECT
--     TO anon, authenticated USING (bucket_id = 'contracts');
-- CREATE POLICY "allow_contracts_update" ON storage.objects FOR UPDATE
--     TO anon, authenticated USING (bucket_id = 'contracts')
--     WITH CHECK (bucket_id = 'contracts');
-- CREATE POLICY "allow_contracts_delete" ON storage.objects FOR DELETE
--     TO anon, authenticated USING (bucket_id = 'contracts');

-- 4. 初期テンプレートのサンプル挿入（あとから管理画面で編集可能）
INSERT INTO p1_contract_templates (name, version, doc_type, body_markdown)
VALUES (
    '業務委託契約書 標準版',
    'v1.0',
    'outsourcing',
    '# 業務委託契約書

{{issuer_name}}（以下「甲」という）と、{{staff_name}}（以下「乙」という）は、以下の通り業務委託契約を締結する。

## 第1条（業務内容）

甲は、乙に対し、ポーカー大会（P1シリーズ等）における下記の業務（以下「本件業務」という）を委託し、乙はこれを受託する。

- ディーラー業務、フロア業務、チップ管理、その他大会運営補助業務
- 担当役割: {{role}}

## 第2条（業務委託料）

1. 本件業務の委託料は、大会終了後に精算する。
2. 金額は時給および各種手当（深夜割増・フロア手当・MIX手当・精勤手当・交通費）の合算額とする。
3. 支払日は大会終了後、速やかに行うものとする。

## 第3条（独立した業務委託関係）

本契約は業務委託契約であり、雇用契約ではない。乙は独立した事業者として自己の責任において本件業務を遂行する。

## 第4条（守秘義務）

乙は、本件業務を通じて知り得た甲の営業秘密、スタッフ・参加者の個人情報、および大会運営に関する一切の情報を、第三者に開示・漏洩してはならない。本契約終了後もこの義務を継続する。

## 第5条（損害賠償）

乙の故意または重過失により甲に損害を与えた場合、乙はその損害を賠償する責任を負う。

## 第6条（契約期間）

本契約は{{event_name}}の期間において有効とする。継続的な業務関係を想定する場合は、別途覚書を締結する。

## 第7条（契約の解除）

甲または乙が本契約に違反した場合、相手方は書面による通知をもって本契約を解除することができる。

## 第8条（合意管轄）

本契約に関する紛争は、名古屋地方裁判所を第一審の専属的合意管轄裁判所とする。

## 第9条（協議事項）

本契約に定めのない事項、または解釈上の疑義が生じた事項については、甲乙誠意をもって協議の上、解決する。

---

{{issue_date}}

**甲（発注者）**
{{issuer_name}}
{{issuer_address}}

**乙（受託者）**
氏名: {{staff_name}}
住所: {{staff_address}}

_上記契約を締結した証として、本書面に乙が電子署名を行う。_
'
) ON CONFLICT DO NOTHING;

INSERT INTO p1_contract_templates (name, version, doc_type, body_markdown)
VALUES (
    '秘密保持契約書（NDA）',
    'v1.0',
    'nda',
    '# 秘密保持契約書（NDA）

{{issuer_name}}（以下「甲」という）と、{{staff_name}}（以下「乙」という）は、ポーカー大会業務に関して知り得る秘密情報について、以下の通り合意する。

## 第1条（秘密情報の定義）

本契約における「秘密情報」とは、甲が乙に開示する下記の情報をいう。

- スタッフ名簿、参加者名簿、電話番号・住所・メールアドレス等の個人情報
- 大会の収支情報、プライズプール、賞金配分ルール
- 運営ノウハウ、マニュアル、業務フロー
- 甲の取引先、提携先に関する情報

## 第2条（秘密保持義務）

乙は、秘密情報を善良な管理者の注意をもって管理し、第三者に開示・漏洩してはならない。また、本件業務以外の目的で使用してはならない。

## 第3条（SNS等での発信禁止）

乙は、本件業務に関する情報を、SNS、ブログ、ネットニュース、動画投稿サイト等で発信してはならない。大会の写真・動画の個人的公開も原則禁止とし、公開する場合は事前に甲の書面による承諾を要する。

## 第4条（違反時の措置）

乙が本契約に違反した場合、甲は損害賠償を請求することができる。また、甲は乙との業務委託契約を即時解除する権利を有する。

## 第5条（有効期間）

本契約は締結日から有効とし、契約終了後も{{confidentiality_years}}年間は秘密保持義務を継続するものとする。

---

{{issue_date}}

**甲**: {{issuer_name}}
**乙**: {{staff_name}}

_上記の内容に同意したことの証として、乙は電子署名を行う。_
'
) ON CONFLICT DO NOTHING;
