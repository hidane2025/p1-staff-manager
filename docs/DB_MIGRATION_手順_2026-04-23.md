# DBマイグレーション実行手順（中野さん向け）

> **対象**: Supabase `p1_staff` プロジェクト
> **所要時間**: 5分
> **実行者**: 中野さん（管理者権限が必要なため）

---

## 実行する2本

1. `20260421_add_receipt_copy_and_tax.sql` — 領収書「原本／控え」＋消費税内訳
2. `20260421_add_contract_provisional.sql` — 契約書「仮版／正規版」フラグ

---

## 手順

### STEP 1. Supabase ダッシュボードを開く

1. https://supabase.com/dashboard にログイン
2. プロジェクト `p1-staff-manager`（または `p1_staff`）を選択
3. 左サイドバー → **SQL Editor** をクリック

---

### STEP 2. マイグレーション1本目を実行

「New query」をクリックして、以下のSQLを貼り付け → **Run** ボタン

```sql
-- 20260421_add_receipt_copy_and_tax.sql

-- 1. p1_payments に発行者保管用（原本）PDFパスを追加
ALTER TABLE p1_payments
    ADD COLUMN IF NOT EXISTS receipt_original_path TEXT;

-- 2. p1_events に消費税額の内訳表示ON/OFFフラグを追加
ALTER TABLE p1_events
    ADD COLUMN IF NOT EXISTS show_tax_breakdown INT DEFAULT 0;
```

**成功したら**: "Success. No rows returned" が表示されます。

---

### STEP 3. マイグレーション2本目を実行

同じSQL Editorで、クエリをクリアして以下を貼り付け → **Run**

```sql
-- 20260421_add_contract_provisional.sql

ALTER TABLE p1_contract_templates
    ADD COLUMN IF NOT EXISTS is_provisional INT DEFAULT 1;

UPDATE p1_contract_templates
    SET is_provisional = 1
    WHERE is_provisional IS NULL;

CREATE INDEX IF NOT EXISTS idx_contract_templates_provisional
    ON p1_contract_templates(is_provisional);
```

**成功したら**: "Success. No rows returned" と UPDATE 件数が表示されます。

---

### STEP 4. 動作確認

以下のクエリで、追加カラムが存在することを確認：

```sql
-- p1_payments に receipt_original_path カラムがあるか
SELECT column_name FROM information_schema.columns
WHERE table_name = 'p1_payments'
  AND column_name IN ('receipt_pdf_path', 'receipt_original_path');

-- p1_events に show_tax_breakdown カラムがあるか
SELECT column_name FROM information_schema.columns
WHERE table_name = 'p1_events'
  AND column_name = 'show_tax_breakdown';

-- p1_contract_templates に is_provisional カラムがあるか
SELECT column_name FROM information_schema.columns
WHERE table_name = 'p1_contract_templates'
  AND column_name = 'is_provisional';
```

3つとも結果が返ってきたら成功です。

---

## エラーが出た場合

### ケース1: `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` が使えない
→ Supabase の Postgres バージョンが古い可能性。以下に書き換え：
```sql
ALTER TABLE p1_payments ADD COLUMN receipt_original_path TEXT;
```
（すでに存在するとエラーになるが、無視してOK）

### ケース2: 権限エラー
→ 中野さんのアカウントが admin 権限を持っているか確認

### ケース3: テーブルが存在しない
→ `p1_payments` / `p1_events` / `p1_contract_templates` が未作成
→ 過去のマイグレーション（`20260417_*.sql`）を先に実行

---

## 完了したら

Streamlit Cloud で再デプロイ（または再起動）してから、以下の動作を確認：
- [ ] 領収書発行で「原本／控え」2バージョンが生成される
- [ ] 契約書プレビューで「仮版」バッジが表示される
- [ ] イベント設定画面で「消費税内訳を表示」トグルが動く

---

## 参考: マイグレーションファイル本体の場所

- `docs/db_migrations/20260421_add_receipt_copy_and_tax.sql`
- `docs/db_migrations/20260421_add_contract_provisional.sql`

作業時間の目安: **5分（コピペ×2とRunボタン×2のみ）**
