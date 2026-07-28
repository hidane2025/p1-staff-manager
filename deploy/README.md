# デプロイ手順（Basic認証つき本番構成）

2026-07-28 作成。木村さんの指摘「社内サービスが全公開・Basic認証を前段に」への対応。

## この構成が何をするか

```
インターネット
   ↓
[nginx]  ← Basic認証。ここを通らないと中に入れない
   ├─ /                      … 管理画面すべて → 認証必須
   ├─ /receipt_download?…    … スタッフの領収書DL → 認証免除（トークンURLが鍵）
   ├─ /contract_sign?…       … スタッフの契約締結 → 認証免除（同上）
   └─ /_stcore/…             … Streamlit内部通信 → 認証免除（初回認証が引き継がれる）
   ↓
[Streamlit]  ← 127.0.0.1 でのみ待受。外部から直接叩けない
```

スタッフ用2ページを免除するのは、125名にID/パスワードを配るのが現実的でないため。
この2ページは推測不能トークン＋7日期限＋失効機能で保護している。

## Railway へのデプロイ手順

1. https://railway.app/ を GitHub アカウントでサインアップ
2. New Project → Deploy from GitHub repo → `hidane2025/p1-staff-manager` を選択
   （Dockerfile が自動検出される）
3. Variables に以下を設定
   | 変数 | 値 |
   |---|---|
   | `BASIC_AUTH_USER` | 任意のID（英数字。例: `p1admin`） |
   | `BASIC_AUTH_PASSWORD` | 強いパスワード（20文字以上推奨） |
   | `SUPABASE_URL` | Supabase の URL |
   | `SUPABASE_SERVICE_KEY` | Supabase の service_role キー |
   | `ADMIN_PASSWORD` | アプリ内ログインのパスワード |
   | `SMTP_HOST` `SMTP_PORT` `SMTP_USER` `SMTP_PASSWORD` `MAIL_FROM` `MAIL_FROM_NAME` | メール送信設定 |
4. Settings → Networking → Generate Domain で公開URLを発行
5. `APP_BASE_URL` に発行されたURLを設定（領収書・契約書のリンク生成に使う）

## 安全装置

- `BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD` が未設定なら**起動しない**
  （認証なしで公開してしまう事故を構造的に防ぐ）
- 起動時セルフテストで「未認証=401」「認証済み=通過」を実測し、
  どちらか失敗したら起動を中止する（公開事故・全員締め出し事故の両方を検出）
- 資格情報はイメージにもリポジトリにも含まれない（起動時に環境変数から生成）

## 検証済みの動作（2026-07-28 ローカルnginx実測）

| 経路 | 認証なし | 期待 | 結果 |
|---|---|---|---|
| `/`（管理画面） | 401 | 401 | ✅ |
| `/`（誤パスワード） | 401 | 401 | ✅ |
| `/`（正しい認証） | 200 | 200 | ✅ |
| `/3_payment`（管理ページ） | 401 | 401 | ✅ |
| `/receipt_download?token=…` | 200 | 200 | ✅ |
| `/contract_sign?token=…` | 到達 | 到達 | ✅ |
| `/_stcore/health` | 200 | 200 | ✅ |
