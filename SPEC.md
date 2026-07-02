# P1 Staff Manager 仕様書

| 項目 | 値 |
|---|---|
| 最終更新 | 2026-06-15 |
| 現行バージョン表記 | **app.py フッター: v3.10**（ただし v3.10 以降は v番号未付与でコミットベース進化中） |
| git HEAD（執筆時点） | `7391c95`（chore: trigger Streamlit Cloud rebuild）／機能上の最新は1つ前の `1dff1aa`（feat(staff): 同一人物の名寄せ） |
| 主要機能の搭載状態 | 多ユーザー認証 / SUPABASE_SERVICE_KEY 対応 / スタッフ名寄せ / PII ガード14ページ — **すべて搭載済**（コミットメッセージ上は v番号未付与だが、`utils/admin_guard.py:1` のコメントには `v3.15 多ユーザー認証` の表記あり）。※応募管理・応募フォーム設定は 2026-07-02 に機能ごと削除 |
| 本番URL | https://hidane2025-p1-staff-manager-app-fw8ggg.streamlit.app/ |
| ソース | https://github.com/hidane2025/p1-staff-manager |
| 公開元 | 株式会社ヒダネ |
| 1人運用前提 | フル権限=伊藤さん／閲覧=中野さん（KIMURA_REVIEW_1PERSON_SCOPE 準拠） |

---

## 目次
1. [システム概要](#1-システム概要)
2. [動作環境とアーキテクチャ](#2-動作環境とアーキテクチャ)
3. [画面一覧（全20ページ（ホーム + pages/ 配下19ファイル））](#3-画面一覧全20ページ（ホーム + pages/ 配下19ファイル）)
4. [データモデル](#4-データモデル)
5. [認証と認可](#5-認証と認可)
6. [PII保護（個人情報の取扱）](#6-pii保護個人情報の取扱)
7. [計算ルール](#7-計算ルール)
8. [スタッフ取込と名寄せ](#8-スタッフ取込と名寄せ)
9. [領収書・契約書（電子発行・署名）](#9-領収書契約書電子発行署名)
10. [業務フロー（4ステップ）](#10-業務フロー4ステップ)
11. [テストとCI](#11-テストとci)
12. [デプロイと運用](#12-デプロイと運用)
13. [既知の制限と将来課題](#13-既知の制限と将来課題)
14. [バージョン履歴](#14-バージョン履歴)

---

## 1. システム概要

### 目的
ポーカー大会（P1事業）の **スタッフ給与計算・電子契約・経理処理を一元化** する Web アプリ。

「①作る → ②入れる → ③計算 → ④渡す」の4ステップ業務フローを単一画面体系で完結させる。

### 主要機能
- イベント単位の **大会型** プロジェクト管理（日別レート・地域別交通費）
- スタッフ登録（手入力／CSV／Google フォーム連携・**同一人物の名寄せ強化**）
- シフト取込（CSV/TSV）と出退勤管理（チェックイン/アウト・凍結退勤・欠勤マーク）
- **時給×時間＋深夜＋手当＋精勤＋交通費** の自動計算（個別時給・タイミー対応）
- ピット端末モード（タブレット片手で退勤打刻＋確定計算）
- 封筒リスト・**紙幣内訳**（1万円札・5千円札・千円札の枚数提示）
- 領収書PDF・**業務委託契約書／NDA** のクラウド電子発行＋電子署名フロー
- 年間累計レポート（**法定調書対象 年¥50万超 自動フラグ**・経理引き渡し用CSV）

### スコープ外（やらないと決めていること）
- マイナンバーの保持（年末調整時にオフライン取得）
- クレジットカード情報
- 銀行口座情報（払込先別管理）
- 源泉徴収「税額」の計算（経理担当が外で実施 — システムは人別の支払額の正確性を保証する）

---

## 2. 動作環境とアーキテクチャ

### 本番環境
| 層 | 採用技術 |
|---|---|
| ホスト | Streamlit Community Cloud（Python ランタイムは Streamlit Cloud 側で選定。執筆時点の本番 Manage app ログでは `Python 3.14.6` と表示・**ただし `runtime.txt` 等の repo 固定指定はなく将来変動の可能性あり**） |
| Web フレームワーク | Streamlit 1.50.0 |
| DB | Supabase（PostgreSQL）— プロジェクト `fmqalkwkxckbxxijiprp`（命名: zion-telecom-tool・流用） |
| 認証（DB） | service_role キー（推奨）／ anon キー（後方互換） |
| 認証（アプリ） | 多ユーザーID/PASS＋ロール（pbkdf2-hmac-sha256 200,000回） |
| ストレージ | Supabase Storage（receipts/contracts/signatures バケット） |
| PDF 生成 | ReportLab 4.5（IPAex フォント埋め込み） |

### ローカル開発環境
| 項目 | 値 |
|---|---|
| Python | **3.9系**（`.github/workflows/test.yml` の `python-version: '3.9'`／`.venv/pyvenv.cfg` の `3.9.6`）。本番との差は標準ライブラリ範囲で吸収 |
| 起動 | `make run`（http://localhost:8511） |
| 依存ピン | `requirements.txt`（全行 `==` でマイナーバージョン固定） |

### データフロー
```
ブラウザ（HTTPS）
    ↓
Streamlit Community Cloud（Python実行・セッション状態管理）
    ↓ REST
Supabase API（service_role でアクセス、RLSバイパス）
    ↓
PostgreSQL（p1_events / p1_staff / p1_payments / p1_shifts / p1_audit_log ほか）

別ルート:
ブラウザ → /receipt_download?token=...  → トークン検証 → サーバーが download_pdf() で取得 → bytes を st.download_button で直接配信
ブラウザ → /contract_sign?token=...     → トークン検証 → 署名→ contracts/*.pdf を更新
```

---

## 3. 画面一覧（全20ページ（ホーム + pages/ 配下19ファイル））

`pages/` 配下の Streamlit マルチページアプリ。**16ページ** が `require_admin()` で管理者ゲート付き。スタッフ向けトークンページ（receipt_download / contract_sign）は **token必須・PII個別配信**。

| # | ファイル | 画面 | 用途 | 管理者ゲート | PII表示 |
|---|---|---|---|---|---|
| ホーム | `app.py` | P1 Staff Manager トップ | 今日のTo-Do・KPI・フロー導線 | — | — |
| 0 | `0_イベント設定.py` | イベント設定 | 大会の作成・JSONテンプレ取込・プリセット | — | なし |
| 1 | `1_スタッフ管理.py` | スタッフ管理 | 登録/編集/CSV/フォーム連携 | ✅ | あり（本名・住所・連絡先） |
| 2 | `2_シフト取込.py` | シフト取込 | CSV/TSV → 日別シフト | ✅ | あり（氏名） |
| 3 | `3_支払い計算.py` | 支払い計算 | 時給×時間＋手当の自動計算 | ✅ | あり（支払額） |
| 4 | `4_封筒リスト.py` | 封筒リスト | 封筒ラベル＋紙幣内訳出力 | ✅ | あり（源氏名・支払額） |
| 5 | `5_出退勤.py` | 出退勤管理 | チェックイン/アウト・例外記録 | ✅ | あり（氏名） |
| 6 | `6_精算レポート.py` | 精算レポート | 現金照合・小口・CSV | ✅ | あり |
| 7 | `7_年間累計.py` | 年間累計 | 法定調書対象（年¥50万超）自動検出 | ✅ | あり（本名・住所・支払額） |
| 8 | `8_交通費.py` | 交通費 | 地域別ルール・領収書入力 | ✅ | あり（住所） |
| 9 | `9_receipt_download.py` | 領収書ダウンロード | トークンURL専用（スタッフ向け） | — | 自分のみ |
| 10 | `10_ピット端末.py` | ピット端末 | 退勤打刻＋計算確定の1画面化 | ✅ | あり |
| 11 | `11_個別手当.py` | 個別手当 | 言語/人材確保/リーダー手当 | ✅ | あり |
| 91 | `91_領収書発行.py` | 領収書発行 | 一括PDF生成＋DL用URL配信 | ✅ | あり |
| 92 | `92_発行者設定.py` | 発行者設定 | Pacific情報・インボイス番号 | ✅ | なし |
| 93 | `93_契約書テンプレ.py` | 契約書テンプレ | 業務委託契約・NDAテンプレ編集 | ✅ | なし |
| 94 | `94_契約書発行.py` | 契約書発行・管理 | 一括送付＋署名状況追跡 | ✅ | あり |
| 99 | `99_contract_sign.py` | 電子署名 | トークンURL専用（スタッフ向け） | — | 自分のみ |

> 「PII表示」は画面上で本名・住所・支払額など個人情報を直接表示することを示す。表示があるページは原則として `require_admin()` で守られる。

---

## 4. データモデル

### 主要テーブル（Supabase / public スキーマ）

すべて主キーは `id`（`BIGSERIAL` / `BIGINT IDENTITY` / `SERIAL` のいずれか — 採用は追加時期により異なる）。同一性は UNIQUE 制約で別途担保される。

| テーブル | 内容 | PII等級 |
|---|---|---|
| `p1_events` | イベント（大会）。**発行者情報（issuer_name / issuer_address / issuer_tel / issuer_seal_url）もこのテーブルの列** | 中（会場情報） |
| `p1_event_rates` | 日別レート（通常時給／深夜時給／精勤上限）。`(event_id, date)` を UNIQUE | 低 |
| `p1_event_transport_rules` | 地域別交通費ルール。`(event_id, region)` を UNIQUE | 低 |
| `p1_staff` | スタッフ。`no` が業務上の通番 | **高**（本名・住所・連絡先） |
| `p1_shifts` | シフト1人1日。**弁当配布状態**（`lunch_status` / `lunch_status_at` / `lunch_status_by`）も列として保持（2026-06-18 追加） | 中（氏名参照） |
| `p1_payments` | 支払い1人1イベント | **高**（金額・支払先） |
| `p1_staff_event_allowances` ★ | 個別手当（言語／人材確保／リーダー、オフレコ） | 中 |
| `p1_transport_claims` | スタッフ別交通費請求（領収書付き） | 中 |
| `p1_petty_cash` | 小口経費（精算レポート連動） | 中 |
| `p1_audit_log` | 監査ログ（PII閲覧・ログイン履歴含む） | 中 |
| `p1_contract_templates` | 業務委託契約／NDA テンプレ本文 | 低 |
| `p1_contracts` | 契約書メタ・署名状態・本文スナップショット | 中 |

> 領収書は独立テーブルを持たず、`p1_payments` の状態列（receipt_received 等）と Storage `receipts/` バケットで管理される。発行者情報も `p1_events` の列として保持される。
>
> **★ = リポにマイグレ SQL あり・本番DB未適用**（2026-07-02 時点）。個別手当は本番アプリでは未稼働。本番適用は `docs/db_migrations/20260508_add_individual_allowances.sql` を Supabase SQL Editor で実行する必要あり。
>
> ※応募管理・応募フォーム設定（`p1_dealer_applications` / `p1_application_sources`）は **2026-07-02 に機能ごと削除**（中野さん判断：シートを自作してCSVアップロードする運用に一本化）。マイグレ未適用のまま削除したため本番DBに残骸なし。

### Storage バケット
| バケット | 用途 | 公開 | 配信 |
|---|---|---|---|
| `receipts` | 領収書PDF | **OFF** | アプリがトークン検証 → `receipt_storage.download_pdf()` → `st.download_button` で bytes 配信 |
| `contracts` | 契約書PDF（未署名／署名済） ＋ 署名画像（`signatures/<safe>.png` パス配下） | **OFF** | 同上（`contract_storage.download_bytes()`）。**Signed URL は一部の旧経路にのみ残存** |

### 状態遷移（支払い）
```
pending（未承認）
   ├── approve（承認） → approved
   │      ├── receipt（領収書受領） → 受領済フラグ
   │      └── pay（現金支払） → paid
   └── reset（凍結再計算） → pending に戻る
```
状態遷移は `approve_payment` / `mark_paid` 関数でガード（pending→approved→paid の順を強制）。

---

## 5. 認証と認可

### 認証モード（`utils/admin_guard.py`）
解決順：**多ユーザー（推奨）> 単一パスワード > パスワードレス（開発のみ）**

1. **多ユーザー（推奨）**
   - Secrets に `[auth.users]` セクション
   - 各エントリ：`username = { password_hash = "pbkdf2$200000$<salt>$<hash>", role = "admin" | "viewer" }`
   - `scripts/make_app_user.py` で生成（CLI）
   - パスワードは **pbkdf2-hmac-sha256 200,000回 + 16Byte ソルト**・**定数時間比較**
   - role 省略・空白は **viewer に倒す**（最小権限）／未知文字列はそのまま保存されるが、各ゲートが `roles` 完全一致で判定するため**どのページにも入れず実質拒否**になる

2. **単一パスワード（後方互換）**
   - Secrets `ADMIN_PASSWORD` または環境変数
   - role は admin 扱い

3. **パスワードレス（ローカル開発のみ）**
   - 警告を出して通過。本番では使わない

### ロール
| ロール | 操作 |
|---|---|
| `admin` | 全画面・全操作 |
| `viewer` | 各ページの `roles=("admin","viewer")` で許可された画面のみ閲覧 |

> 1人運用方針（KIMURA_REVIEW）に従い **2ロール体系**。3段階ロールはスコープ外。

### Fail Closed
`[auth.users]` セクションは存在するが全エントリが不正（password_hash 欠落・形式エラー）な場合、**パスワードレスに落とさず必ずブロック**（無認証アクセス禁止）。

### 監査ログ
- ログイン成功／失敗、admin_login / admin_logout、PII閲覧（`view_*` アクション）を `p1_audit_log` に記録
- パスワード本文は記録しない（長さのみ）

---

## 6. PII保護（個人情報の取扱）

### 取扱対象
| 項目 | テーブル列 | リスク等級 |
|---|---|---|
| 本名 | `p1_staff.real_name` | 高 |
| 住所 | `p1_staff.address` | 高 |
| メール | `p1_staff.email` | 中 |
| 連絡先（LINE等） | `p1_staff.contact` | 中 |
| 支払額・年間累計 | `p1_payments.*` | 高 |
| 領収書PDF | Storage `receipts/*.pdf` | 高 |
| 契約書PDF（署名付） | Storage `contracts/*.pdf` | 高 |

### 防御層
| 層 | 仕組み |
|---|---|
| 招待 | Streamlit Cloud Sharing で配布範囲を限定 |
| 多ユーザー認証 | 16ページに `require_admin()` |
| RLS（テーブル） | service_role でアプリ実行・anon 直接アクセスは将来 REVOKE で締める（移行手順は §13） |
| RLS（Storage） | バケット public OFF・Signed URL のみで配信 |
| HTML エスケープ | DB値を `<HTML>` に出すページ（封筒明細・契約書PDF）で `html.escape()` |
| 監査ログ | PII閲覧・ログイン失敗を `p1_audit_log` に永続化 |
| 依存ピン留め | `requirements.txt` 全行 `==`、CIで毎push検証 |

### CSVダウンロード時の二重確認
PII（本名・住所・メール）を含むCSVには「⚠️ T2個人情報・最高濃度」警告 + 「受取先を確認しました」チェックを必須化。

---

## 7. 計算ルール

### 一律時給×時間
- 通常時給は `p1_event_rates.normal_rate`（日別）
- スタッフ個別の `custom_hourly_rate`（タイミー希望時給）があれば優先

### 深夜手当
- `p1_event_rates.night_rate` を 22:00〜翌5:00 に適用
- 深夜跨ぎシフトは `pages/10_ピット端末.py` の `_is_overnight_shift` で「前日の続き」と判定

### 精勤手当
- 全日出勤で `p1_event_rates.attendance_bonus` を最終日に付与
- 欠勤・大幅な遅刻早退があれば剥奪

### 個別手当（オフレコ）
- 言語手当・人材確保手当・リーダー手当を `p1_staff_event_allowances` で個別付与
- **給与窓口担当のみ閲覧可能**（封筒明細 `require_admin` 必須・最終封筒額に統合）

### 交通費
- 地域別上限 `p1_event_transport_rules.max_amount`
- 領収書必須フラグ `receipt_required` でルート決定
- スタッフ住所の都道府県→地域マッピング（`utils/region.py`）

### 弁当配布チェック（2026-06-18 追加機能 / マイグレ `20260618_add_lunch_status.sql`）
大会期間中の弁当配布を **シフト1人1日** 単位で管理。

| 列 | 意味 |
|---|---|
| `p1_shifts.lunch_status` | `pending`（未受領）／`received`（配布済）／`cancelled`（辞退） |
| `p1_shifts.lunch_status_at` | 最終更新時刻 |
| `p1_shifts.lunch_status_by` | 更新したオペレーター名（監査用） |

- 集計 `db.get_lunch_summary(event_id, date)` → `{received, pending, cancelled, total_active}`
- 一括設定 `db.bulk_set_lunch_status(event_id, date, status, performed_by)` — 欠勤者（`status='absent'`）は対象外
- UI は `pages/10_ピット端末.py` に「📦 配布チェック」エキスパンダーで内蔵（タブレット運用想定）

### 弁当2個目・ドリンクチケット配布（2026-07-02 追加 / マイグレ `20260702_add_lunch2_drink_status.sql` ★本番未適用）
運用ルール：弁当は基本1個・**予定シフト12時間以上の人は2個**。ドリンクチケットは**一律2枚**。

| 列 | 意味 |
|---|---|
| `p1_shifts.lunch2_status` (+`_at`/`_by`) | 弁当2個目。状態3値は lunch_status と同じ |
| `p1_shifts.drink_status` (+`_at`/`_by`) | ドリンク券（2枚1セット＝1チェック） |

- 12h判定は**予定シフト時間ベース**（`db.planned_shift_minutes(planned_start, planned_end)` ≥ `LUNCH2_THRESHOLD_MINUTES`=720。'26:00'等の24h超え表記対応）。対象者の行にだけ「🍱② 2個目」トグルと 12h+ バッジが出る
- 汎用API：`db.update_distribution_status(shift_id, kind, status)` / `db.bulk_set_distribution_status(...)` / `db.get_handout_summary(event_id, date)`（kind=`lunch`/`lunch2`/`drink`・1クエリで3種集計・列未追加時は `migrated: False` でグレースフル劣化）
- ピット端末に日次の必要数目安（弁当◯個／ドリンク券◯枚）を表示（発注数の突合用）

### 出勤チェック列（2026-07-02 追加）
出退勤ページ「③本日の状況一覧」に「✅出勤」チェックボックス列。チェック＝**予定時刻どおり出勤として確定**（`checkin_staff`）、解除＝未確定に戻す（実到着クリア）。退勤済・欠勤の行は変更を弾いて個別リセットへ誘導。遅刻等の実時刻記録は従来どおり「②例外を記録」。

### 端数処理（紙幣最適化）
- 1万円札・5千円札・千円札の枚数を最小化する端数調整：**100円・500円・1000円単位の切り上げのみ**（切り下げ処理は無い）
- 端数調整額は明細 `tanchosei_row` に明示し、内訳和＋端数調整＝合計 を成立

### 確定額（A-6）
- 封筒・領収書・年間累計はすべて `get_payable(payment)` で取得した **確定額（payable_amount）** で集計し、端数処理含む金額が3画面で一致

---

## 8. スタッフ取込と名寄せ

### 入口
1. 手入力（`pages/1_スタッフ管理.py`）
2. CSV / TSV アップロード（テンプレ提供あり）
3. テキスト貼り付け（CSV / TSV）
4. テーブル入力
5. **Google フォーム連携CSV**（`utils/gform_importer.py`・テンプレ `docs/gform_staff_onboarding_template.md`）

### 名寄せ（2026-06 追加機能 / コミット `1dff1aa`）
取込時の **同一人物判定**：

```
照合優先度： NO. > メール（NFKC正規化） > 源氏名（NFKC正規化）
正規化      ： 全角半角・空白・大小文字をすべて吸収
              （"Eve Kat" / "ＥＶＥ　ＫＡＴ" / "evekat" → 同一キー）
```

- `db.bulk_import_staff()` は1バッチ内でも重複を吸収（同一バッチ内二重取込防止）
- 自動マージは行わず、**表記揺れ統合・同名衝突**は `result["warnings"]` に列挙
- 取込画面（スタッフ管理）で「🔎 名寄せの確認事項 N件」として表示
- `db.find_or_create_staff()` も NO.優先＋正規化照合に統一

### 経理連携（源泉徴収の前提）
源泉徴収「税額」計算は経理担当が実施するが、人別の年間支払額が正確であることが前提。
→ 名寄せが分裂を防ぐことで、**年間 ¥50万超 判定（法定調書）** や経理側の人単位合算が壊れない。

---

## 9. 領収書・契約書（電子発行・署名）

### 領収書（receipts/*.pdf）
- `pages/91_領収書発行.py` で承認済み支払いを一括 PDF 化
- 原本／控え 2部、税額内訳 ON/OFF 切替
- **トークンURL**（**7日**有効・`utils/receipt_token.py:expiry_iso(valid_days=7)`）でスタッフへ DL リンク配信
- スタッフ画面 `pages/9_receipt_download.py` は受信トークンを `utils/receipt_token.py` で検証し、**サーバー側で `receipt_storage.download_pdf()` を呼んで取得した PDF bytes を `st.download_button` で直接配信**（Signed URL は介さない）

### 契約書（contracts/*.pdf）
- `pages/93_契約書テンプレ.py` で業務委託契約／NDA テンプレ編集（docx / pdf / プレーンテキスト取込対応）
- `pages/94_契約書発行.py` で一括発行＋スタッフへ署名URL配信
- スタッフ画面 `pages/99_contract_sign.py` はトークン検証後、`streamlit-drawable-canvas` で電子署名→ PNG → 契約PDFに合成保存
- 契約No `C-YYYYMMDD-T<template_id>-S<staff_id>-<hash>` で一意管理（T は **テンプレID**・event_id ではない／`utils/contract_pdf.py:53` `build_contract_no(template_id, staff_id, issue_date_ymd)`）、本文スナップショットも保存（後の改変防止）
- 仮版PDFには透かしを入れ、正規版で外す

### セキュリティ
- 契約書PDFのスタッフ自己申告データは `html.escape()` でエスケープ済（XSS 防止）
- Storage バケットは public OFF。**契約署名済PDFは Signed URL、領収書はサーバー側ダウンロード経由で bytes 配信**（どちらも非公開・トークン経由）
- 二重署名対策は `utils/contract_issuer.apply_signature` の **アプリ層 status 事前チェック**で行う（DB側 UPDATE は id 条件のみ・原子的ガードではない）

---

## 10. 業務フロー（4ステップ）

```
① 作る   →  ② 入れる    →  ③ 計算       →  ④ 渡す
イベント設定  スタッフ管理   ピット端末       個別手当
              シフト取込    支払い計算       領収書発行
                            封筒リスト       契約書発行
```

運用体制（KIMURA_REVIEW_1PERSON_SCOPE 2026-04-23 確定）：

| 役割 | 担当 | 操作範囲 |
|---|---|---|
| メイン運用者（フル権限・admin） | **伊藤さん 1人** | ①〜④ 全工程（シフト・出退勤・契約・領収書・支払いを完全1人で実施） |
| 最終確認・承認（閲覧 / viewer） | **中野さん** | ダッシュボード閲覧、最終承認 |

> 旧 MANUAL.md v3.3 の「経理／TD／給与窓口」分業は 2026-04-23 の KIMURA_REVIEW でスコープ外（過剰）と判定され、1人運用に統合された。役職ロール（Dealer / Floor / TD / Chip / DC）はスタッフの**職務区分**として残り、運用者の役割分担とは別概念。

ホーム画面の「今日のTo-Do」（8項目）は、この4ステップを **大会の準備→当日→締めの順** に並べた進捗チェックリスト（`progress_checklist`）で、状態は実DBから自動判定（done/warn/pending/todo）。

---

## 11. テストとCI

### テストスイート（`test_e2e/`）
| 番号 | 内容 | 件数 |
|---|---|---|
| 4 | 領収書PDF生成 | 5 |
| 8 | 契約書PDF生成 | 5 |
| 14 | 領収書原本／控え＋税額内訳 | 7 |
| 15 | 契約書テンプレ取込（docx/pdf/plain） | 10 |
| 16 | Google フォーム CSV取込 | 12 |
| 17 | event_template JSON 投入 | 27 |
| 18 | ページ起動スモーク（AppTest） | 10 |
| 19 | admin_guard（PWゲート） | 10 |
| 20 | core logic（計算・紙幣・地域・シフト） | 60+ |
| 21 | UI 要素検出（AppTest 全20ページ（ホーム + pages/ 配下19ファイル）） | 50+ |
| 22 | セキュリティ動作（HTMLエスケープ・要件） | 30+（assert ベース実装） |
| **23** | **スタッフ名寄せ（2026-06 追加）** | **8** |
| **24** | **弁当配布チェック（2026-06-18 追加）** | **8** |

README 表記の合計 **215+ 件**（4/22 はテスト数の数え方の都合で多少誤差あり）。`make test-fast`（DB非依存）/ `make test-ui`（AppTest）/ `make test`（全部）。

### CI（GitHub Actions）
- `.github/workflows/test.yml` で push のたびに全テスト実行
- バッジ：README 先頭に表示
- 失敗時は Streamlit Cloud に直接デプロイされる前に検知できる

### Lint
- `make lint` で `app.py / db.py / utils/*.py / scripts/*.py / pages/*.py` を `py_compile`

---

## 12. デプロイと運用

### デプロイ
- main ブランチへの push → Streamlit Cloud が GitHub から自動 pull → 再ビルド → デプロイ
- リポジトリ可視性：**public** が前提（private にする場合は Streamlit Cloud の GitHub アプリに private リポ権限を付与必須）

### Reboot 手順（「Oh no」状態からの復旧）
1. https://share.streamlit.io にログイン
2. アプリ一覧から **p1-staff-manager** の右端「⋮」→ **Reboot**
3. 確認ダイアログで Reboot
4. 1〜2分で再ビルド→起動

### Secrets（Streamlit Cloud）
```toml
SUPABASE_URL = "https://fmqalkwkxckbxxijiprp.supabase.co"
SUPABASE_SERVICE_KEY = "..."   # service_role キー（推奨）
ADMIN_PASSWORD = "..."         # 多ユーザー無効時の後方互換
[auth.users.nakano]
password_hash = "pbkdf2$200000$<salt>$<hash>"
role = "admin"
[auth.users.window1]
password_hash = "pbkdf2$200000$<salt>$<hash>"
role = "viewer"
```

### 月次・四半期チェックリスト
詳細は `docs/SECURITY_OPS.md` §7。

| 周期 | 作業 |
|---|---|
| 月次 | 監査ログ異常検知・`pip list --outdated`・バックアップ・招待リスト確認 |
| 四半期 | ADMIN_PASSWORD更新（90日）・Storage 全件バックアップ・RLS抜き打ちテスト |
| 年次 | 7年経過分のスタッフ匿名化・プラン見直し・契約テンプレ法務レビュー |

---

## 13. 既知の制限と将来課題

### 制限
- マイナンバー・銀行口座情報は **持たない**（オフライン管理）
- 源泉徴収「税額」の計算は **しない**（経理担当に委譲）
- Supabase Free プラン想定（自動バックアップなし — Pro 昇格推奨）

### 残課題（2026-06-15時点）
1. **anon キー旧値が GitHub 履歴に残存**：`db.py:19-25` のフォールバック値が漏洩済み。**SUPABASE_SERVICE_KEY を Secrets に設定 → `docs/db_migrations/20260609_revoke_anon_lockdown.sql` を実行** で anon ロールを完全無権限化することで本質解決する。SQL は実行順序を厳守（Secrets 設定→アプリ動作確認→SQL実行）。
2. **Streamlit 1.50 で `use_container_width` が廃止予告**：実害なし（warning のみ）。次のメンテで `width='stretch'` に置換予定。

### 将来課題（任意）
- データ保持期限（7年）超過スタッフの自動匿名化（`scripts/purge_expired.py` 想定・未着手）

---

## 14. バージョン履歴（git log 実コミットメッセージから整理）

| バージョン | コミット | 主な変更（コミットメッセージから） |
|---|---|---|
| v3.6 | `0d8c2f3` | イベント設定ウィザード＋JSONテンプレ一括投入（型完成） |
| v3.7 | `53ef024` | デザインシステム導入とUI/UX全面リファイン |
| v3.8 | `ad90d76` | 現場フィードバック対応 Phase 2（個別時給・小口経費・ピット端末） |
| v3.9 | `b99ef55` | 現場フィードバック対応 Phase 3（承認フロー再設計・交通費二段階・個別手当） |
| v3.9.1〜v3.9.5 | `22cee01`〜`87e1a8b` | Codex レビュー指摘の連続修正 |
| v3.10 | `bd9cb97` | UX 即効果セット A+B+D（ホームTo-Do化・ピット端末強化・iPad印刷対応） |
| v3.10.1〜v3.10.3 | `f6f3a9d`〜`0af4d13` | Codex レビュー指摘の連続修正（印刷モード再設計） |
| v3.11 | `e940249` | 領収書PDFの構造を逆転（payer=宛名・receiver=発行者欄） |
| v3.12 | `1818f1c` | 経理監査T1 内部統制・安全強化（A-2/3/4/7/9/10/11・C-1） |
| v3.13 | `3711bc3` | 経理監査T2 金額の一元化（A-5 臨時調整／A-6 確定額payable） |
| v3.14 | `20667e1` | UX磨き込み 高ROI3点（ナビ優先度化・タブレット圧縮・主要アクション上げ） |
| **（v番号未付与）** | `9af1b03`〜`1dff1aa` | **2026-05〜06 機能追加群：多ユーザー認証 / ディーラー応募GSS連動 / 応募管理UI / 領収書・契約書日本語フォント埋込 / SUPABASE_SERVICE_KEY 対応 / PII画面の認可ゲート強化 / スタッフ名寄せ強化** |
| **（v番号未付与）** | 2026-07-02 | **応募管理・応募フォーム設定を機能ごと削除**（中野さん判断：シート自作→CSVアップロード運用に一本化。ページ2枚・db.py応募セクション・GSS連携・マイグレSQLを除去。本番DB未適用だったため残骸なし） |

> 注：v3.14 以降は明示的なバージョン番号付与なしでコミットベースに進化している。`app.py:488` のフッター表記は **`v3.10`** で固定されており、実装の進化に追従していない（次回 UI 改修時に更新候補）。

---

## 関連ドキュメント
- `GUIDE.md` — 活用ガイド（伊藤さん向け業務操作手順）
- `README.md` — 概要・テスト・セキュリティ早見表
- `MANUAL.md` — v3.3時点の旧取扱説明書（歴史記録）
- `docs/SECURITY_OPS.md` — セキュリティ運用ガイド（月次・年次チェック）
- `docs/KIMURA_REVIEW_1PERSON_SCOPE.md` — 1人運用方針（運用設計の根拠）
- `docs/gform_staff_onboarding_template.md` — Google フォーム設計テンプレ
