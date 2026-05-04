# イベントテンプレート（JSON）

新しい大会を P1 Staff Manager に登録するための JSON テンプレート集です。

## 含まれるファイル

| ファイル | 用途 |
|---|---|
| `_TEMPLATE_BLANK.json` | 編集用の空テンプレート（コメント付き） |
| `p1_nagoya_2026_winter.json` | P1 Nagoya 2026 年末大会（実績ベース） |
| `p1_kyoto_2026_summer.json` | P1 Kyoto 2026 夏大会（参考） |

## 使い方（中野さん向け）

### A. アプリのウィザードでアップロード（推奨）

1. P1 Staff Manager の **「📋 イベント設定」** ページを開く
2. 「JSON テンプレートから一括投入」セクションでファイルをアップロード
3. プレビューを確認 → 「実行」

### B. CLI で一括投入

```bash
cd p1-staff-manager
.venv/bin/python scripts/seed_event.py docs/event_templates/p1_nagoya_2026_winter.json
```

## テンプレート構造

```json
{
  "name": "イベント名",
  "venue": "会場名",
  "venue_prefecture": "愛知県",
  "start_date": "2026-MM-DD",
  "end_date": "2026-MM-DD",
  "break_minutes_6h": 45,
  "break_minutes_8h": 60,
  "rate_template_id": "p1_standard",
  "dates": ["2026-MM-DD", ...],
  "rates": {
    "2026-MM-DD": {
      "hourly": 1500, "night": 1875, "transport": 1000,
      "floor_bonus": 3000, "mix_bonus": 1500,
      "date_label": "regular"
    }
  },
  "transport_rules": [
    {"region": "東海", "max_amount": 0, "receipt_required": 0,
     "is_venue_region": 1, "note": "開催地"}
  ]
}
```

### 各フィールドの説明

| フィールド | 必須 | 説明 |
|---|---|---|
| `name` | ✅ | イベント名（例: "P1 Nagoya 2026 年末"） |
| `venue` | ✅ | 会場名（例: "中日ホール"） |
| `venue_prefecture` | ⚪️ | 開催地都道府県。地域別交通費の起点になる |
| `start_date` / `end_date` | ✅ | YYYY-MM-DD 形式 |
| `break_minutes_6h` | ⚪️ | 6時間超勤務時の休憩控除（分）。デフォルト45 |
| `break_minutes_8h` | ⚪️ | 8時間超勤務時の休憩控除（分）。デフォルト60 |
| `rate_template_id` | ⚪️ | プリセット識別ラベル（記録用、計算には影響しない） |
| `dates` | ⚪️ | 対象日リスト。省略時は start〜end から自動生成 |
| `rates.[日付]` | ⚪️ | 日別レート（指定しない日はデフォルト ¥1,500/¥1,875 で計算される） |
| `rates.[日付].date_label` | ⚪️ | "regular" / "premium"。表示・集計用 |
| `transport_rules` | ⚪️ | 地域別交通費上限（is_venue_region=1 は開催地） |

## レートプリセット

`rates` を毎回手書きするのが面倒なときは以下のプリセットを使う。

| プリセットID | 通常時給 | 深夜時給 | フロア手当 | MIX手当 |
|---|---|---|---|---|
| `p1_standard` | ¥1,500 | ¥1,875 | ¥3,000 | ¥1,500 |
| `usop_standard` | ¥1,400 | ¥1,700 | ¥3,000 | ¥3,000 |
| `minimum_aichi` | ¥1,055 | ¥1,319 | ¥3,000 | ¥1,500 |

`premium` 日は P1標準で時給+¥100、フロア手当 ¥3,000→¥5,000。

## 既存イベントをテンプレ化したい時

```bash
.venv/bin/python -c "
import json
from utils.event_template import export_event_to_template, dump_template
tmpl = export_event_to_template(event_id=123)  # 任意の event_id
print(dump_template(tmpl))
" > docs/event_templates/my_event.json
```

または **「📋 イベント設定」ページ → 「現在のイベントを JSON でダウンロード」**。

## 後方互換について

`venue_prefecture` / `rate_template_id` は新カラム。
DBマイグレーション（`docs/db_migrations/20260504_add_event_prefecture.sql`）未実行でも
アプリは従来どおり動作する。マイグレ実行後にこれらの値が保存されるようになる。
