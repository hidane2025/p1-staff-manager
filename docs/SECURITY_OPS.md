# P1 Staff Manager — セキュリティ運用ガイド

最終更新: 2026-05-04（v3.7 セキュリティ対策投入時）

このドキュメントは「個人情報を扱うシステムを安全に運用する」ための手順書です。
中野さん／伊藤さんが日常的に守るべき作業と、定期的にやるべきメンテを記載します。

---

## 1. 取扱う個人情報の範囲

| 項目 | 該当データ | リスク等級 |
|---|---|---|
| 本名 | `p1_staff.real_name` | 高 |
| 住所 | `p1_staff.address` | 高 |
| メール | `p1_staff.email` | 中 |
| 連絡先（LINE等） | `p1_staff.contact` | 中 |
| 支払額・年間累計 | `p1_payments.*` | 高（経済的状況） |
| 領収書PDF | Storage `receipts/*.pdf` | 高 |
| 契約書PDF（署名付き） | Storage `contracts/*.pdf` | 高 |
| 契約署名画像 | Storage `signatures/*.png` | 中 |

「漏れたら一発アウト」の優先度: **領収書／契約書 PDF ＞ 本名＋住所 ＞ メール**。

---

## 2. アクセス権限の体系（2026-05-04 時点）

```
[Internet]
   │
   ▼
[Streamlit Cloud Viewer 認証] ← 招待された人だけアプリに到達できる
   │
   ▼
[アプリ全画面（ホーム・イベント設定・シフト等）]
   │
   ▼
[require_admin パスワードゲート] ← PII 直接表示するページに二重ガード
   │
   ▼
[スタッフ一覧 / 精算レポート / 年間累計 / 領収書発行 / 契約書発行 等]
```

### 管理者パスワードを設定する（最初に1回）

1. Streamlit Cloud → 該当アプリ → **Settings** → **Secrets** を開く
2. 以下を追加:
   ```toml
   ADMIN_PASSWORD = "強いパスワード（16文字以上推奨）"
   ```
3. **Save** → アプリは自動再起動
4. 全管理ページが「🔒 管理者認証が必要です」のゲートを表示するようになる

### Viewer 認証の招待

1. Streamlit Cloud → アプリ → **Settings** → **Sharing**
2. 招待するメールアドレスを追加（中野さん・伊藤さん・キム鉄さん等）
3. 招待されていない人は URL を知ってもアプリ画面に到達できない

### パスワード共有

- ADMIN_PASSWORD は中野さん／伊藤さんだけが知る
- 1Password / Bitwarden 等のパスワードマネージャで共有
- **チャットや LINE で平文送信しない**

### パスワード変更（90日に1回）

カレンダーで90日リマインダ → Secrets を更新するだけ。
直近のログイン試行ログは Supabase の `p1_audit_log` で確認可能。

---

## 3. RLS（Row Level Security）の現状と推奨形

### 現状（2026-05-04 のスタート点）

- アプリは Supabase の **anon key** で接続（`db.py:18-25`）
- RLS は ON だが、ポリシーが「allow_all（誰でも全許可）」に近い設定の可能性
- 詳細は `docs/db_migrations/20260504_security_table_rls_audit.sql` の手順 A で確認

### 推奨形（移行先）

1. `service_role` key を Streamlit Cloud Secrets の `SUPABASE_KEY` に保存
2. アプリは service_role で接続（RLS をバイパス）
3. anon ロールには「token 検証付き SELECT のみ」を許可
4. `receipt_download` / `contract_sign` ページだけ anon を使う

### Storage RLS（即時実行）

`docs/db_migrations/20260504_security_storage_rls.sql` を Supabase SQL Editor で実行:

- receipts / contracts バケットを **public OFF**
- anon ロールから直接 SELECT を禁止
- アプリは Signed URL を介して配信（既存挙動に影響なし）

---

## 4. バックアップ戦略

### Supabase 側

| プラン | バックアップ | 保持期間 |
|---|---|---|
| Free（現状の可能性大） | 自動バックアップなし | — |
| Pro ($25/月) | 日次自動バックアップ | 7日間 |

**推奨: Pro プランへの昇格** — 月¥3,800 で日次バックアップが付く。
法定調書／会計監査のために**最低3年保持**は必要なため、月次で `pg_dump` を取って外部保管するのが理想。

### 月次手動バックアップ（Pro プラン未利用時の最低運用）

中野さん月初の作業（5分）:

```bash
# 例: ローカルから Supabase に直接接続して dump
.venv/bin/python -c "
import db, json
from datetime import date
data = {
    'staff':    db.get_all_staff(),
    'events':   db.get_all_events(),
    'date':     date.today().isoformat(),
}
with open(f'backup_p1_{date.today().isoformat()}.json', 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print('OK')
"
```

→ できた JSON を **暗号化された外部ストレージ**（1Password Vault、暗号化Drive 等）に保管。

### Storage バケット（PDF）のバックアップ

Supabase ダッシュボード → Storage → バケットごとに「Download all」できる。
四半期に1回、暗号化外部ストレージにアーカイブ。

---

## 5. データ保持とパージ（個人情報保護法対応）

### 保持期間

| データ種別 | 保持期間 | 根拠 |
|---|---|---|
| スタッフ本名・住所 | 退職から **7年** | 税務関連書類の保存義務 |
| 支払い記録 | **7年** | 法人税法・所得税法 |
| 領収書PDF | **7年** | 同上 |
| 契約書PDF（署名付き） | **5年** | 民法上の時効＋税務 |
| 監査ログ | **3年** | 内部管理用 |

### パージ手順（年1回・1月実施推奨）

1. 7年前以前にイベント参加し、その後一度も参加していないスタッフを抽出
2. 該当スタッフの個人情報フィールドを匿名化（real_name="退会者", address="", email="" 等）
3. 匿名化前のスナップショットを暗号化外部保管（後日再連絡が必要になった時のため）

> 実装は未着手。年内に `scripts/purge_expired.py` を追加予定。

---

## 6. インシデント対応フロー

### 個人情報漏洩を疑った場合（最初の30分）

1. **アプリを停止** — Streamlit Cloud → アプリ → **Settings** → **Pause app**
2. **anon key を rotate** — Supabase → Project Settings → API → **Reset service role / anon key**
3. **直近30日の監査ログを保全** — Supabase SQL Editor で:
   ```sql
   SELECT * FROM p1_audit_log
   WHERE created_at >= NOW() - INTERVAL '30 days'
   ORDER BY created_at DESC;
   ```
   → CSV エクスポート → 暗号化保管
4. **影響範囲を特定**: どの PII がどこから漏れた可能性があるか
5. **個人情報保護委員会へ報告**: 法律上、個人情報の漏洩等が発生した場合は所轄の個人情報保護委員会への報告と本人通知が必要(個人情報保護法第26条)

### 不審ログ検知

監査ログで以下を週1回チェック:

```sql
-- 失敗ログイン試行（10回以上は要注意）
SELECT performed_by, COUNT(*) AS failed
FROM p1_audit_log
WHERE action = 'admin_login_failed'
  AND created_at >= NOW() - INTERVAL '7 days'
GROUP BY performed_by
HAVING COUNT(*) >= 10;

-- 深夜帯（0:00-6:00 JST）の管理ページ閲覧
SELECT * FROM p1_audit_log
WHERE action LIKE 'view_%'
  AND EXTRACT(HOUR FROM (created_at AT TIME ZONE 'Asia/Tokyo')) BETWEEN 0 AND 6
  AND created_at >= NOW() - INTERVAL '7 days';
```

---

## 7. 月次・四半期チェックリスト

### 月次（中野さん・5分）

- [ ] 監査ログの異常検知クエリ実行（上記 §6）
- [ ] `pip list --outdated` を実行 → 脆弱性アップデートがあれば `requirements.txt` 更新
- [ ] 月初の手動バックアップ実行（§4）
- [ ] Streamlit Cloud Sharing の招待リスト確認（退職者が残っていないか）

### 四半期（中野さん・30分）

- [ ] ADMIN_PASSWORD の更新（90日サイクル）
- [ ] Storage バケット全件のローカル保管バックアップ
- [ ] RLS ポリシーが期待通りに効いているか抜き打ちテスト（anon key で直接アクセス試行）
- [ ] 退職スタッフの個人情報を匿名化（年1回でも可）

### 年次（1月・60分）

- [ ] 7年経過分のスタッフデータをパージ
- [ ] Supabase / Streamlit Cloud のプラン見直し
- [ ] 契約書テンプレの法務レビュー（仮版→正規版への昇格）

---

## 8. 「やらない」と決めていること（明示）

- スタッフの**マイナンバー**は本システムでは扱わない（年末調整時のみ別途オフラインで取得→紙ベース）
- **クレジットカード情報**は扱わない
- **銀行口座情報**は将来必要になっても本DBには保存しない（払込先別管理）
- ログには**パスワード本文**を書かない（長さだけ記録）

---

## 9. 関連ドキュメント

- [docs/db_migrations/20260504_security_storage_rls.sql](db_migrations/20260504_security_storage_rls.sql) — Storage RLS 適用SQL
- [docs/db_migrations/20260504_security_table_rls_audit.sql](db_migrations/20260504_security_table_rls_audit.sql) — Table RLS 調査・移行手順
- [utils/admin_guard.py](../utils/admin_guard.py) — 管理者パスワードゲート
- [.gitignore](../.gitignore) — 認証情報の commit 防止リスト

質問・運用相談は社内ヒダネチャネル → ソウ／ミナまで。
