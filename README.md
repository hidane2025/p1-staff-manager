# P1 Staff Manager

[![テスト](https://github.com/hidane2025/p1-staff-manager/actions/workflows/test.yml/badge.svg)](https://github.com/hidane2025/p1-staff-manager/actions/workflows/test.yml)

ポーカー大会のスタッフ管理・経理処理システム。  
本番URL: https://hidane2025-p1-staff-manager-app-fw8ggg.streamlit.app/

## 機能の概要

| 流れ | 主な画面 | 役割 |
|---|---|---|
| ① 作る | 📋 イベント設定 | JSONテンプレートから一括投入。プリセット手動入力にも対応。 |
| ② 入れる | 👥 スタッフ管理 / 📅 シフト取込 | スタッフ登録（CSV/フォーム）と日別シフトの取込 |
| ③ 計算 | 💰 支払い計算 / ✉️ 封筒リスト | 時給×時間＋深夜＋手当＋精勤の自動計算と封筒準備 |
| ④ 渡す | 📄 領収書発行 / ✍️ 契約書発行 | PDF生成＋スタッフ向けDL/署名URLの個別配信 |

詳細は [docs/SECURITY_OPS.md](docs/SECURITY_OPS.md) と [docs/event_templates/_README.md](docs/event_templates/_README.md) を参照。

## ローカル開発

```bash
# セットアップ（初回のみ）
make install

# 起動 → http://localhost:8511
make run

# テスト実行
make test          # 全部
make test-fast     # 軽量だけ（30秒以内）
make test-ui       # UI要素テストだけ
make lint          # 構文チェック
```

## CI / 自動テスト

GitHub Actions で push のたびに 11スイート・215+件のテストを自動実行。  
失敗時は Streamlit Cloud へ直接デプロイされる前に検知できる。

| スイート | 件数 | 内容 |
|---|---|---|
| 4 / 8 | — | receipt / contract PDF生成 |
| 14 / 15 | — | receipt 原本/控え・contract template import |
| 16 | 12 | Google フォーム CSV取込 |
| 17 | 27 | event_template (JSON投入) |
| 18 | 8 | ページ起動スモーク（AppTest） |
| 19 | 10 | admin_guard（PWゲート） |
| 20 | 60+ | core logic（計算/紙幣/地域/シフトパース） |
| 21 | 50+ | UI要素検出（AppTest 全ページ） |
| 22 | 30 | セキュリティ動作（HTMLエスケープ・要件） |

## セキュリティ

| 層 | 仕組み |
|---|---|
| Viewer 認証 | Streamlit Cloud Sharing で招待制 |
| 管理者ゲート | PII を扱う7ページに `require_admin()`（`ADMIN_PASSWORD` Secret） |
| 監査ログ | PII閲覧・ログイン成功/失敗を `p1_audit_log` に記録 |
| Storage RLS | receipts/contracts バケットを Signed URL のみで配信 |
| HTMLエスケープ | スタッフ自己申告データを契約書PDFで `html.escape()` |
| 依存ピン留め | requirements.txt は全行 `==` で固定 |

詳細・運用手順は [docs/SECURITY_OPS.md](docs/SECURITY_OPS.md)。

## ライセンス

Internal — 株式会社ヒダネ
