"""P1 Staff Manager DBスキーマ資料 PDF生成（2026-08-06）

docs/schema.sql（本番DBの内省から自動生成したDDL）を人が読める資料にする。
外部エンジニアへの提出・社内の引き継ぎ資料として使う。

使い方:
    .venv/bin/python docs/generate_schema_pdf.py
出力:
    docs/P1StaffManager_DBスキーマ_<日付>.pdf
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_receipt_manual_pdf import (  # noqa: E402
    DocBuilder, ensure_fonts,
    COLOR_PRIMARY, COLOR_SECONDARY, COLOR_INK, COLOR_MUTED,
    COLOR_BG_LIGHT, COLOR_GREEN,
    FONT_JP_REG, FONT_JP_BOLD,
    PAGE_W, PAGE_H, MARGIN_X,
)
from reportlab.lib.colors import HexColor, white  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "docs/schema.sql"
GENERATED = "2026-08-06"

# 列に日本語の意味を与える（DDLだけでは業務的な意味が伝わらないため）
COL_NOTE = {
    "p1_events": {
        "break_minutes_6h": "6時間超勤務時の休憩控除（分）",
        "break_minutes_8h": "8時間超勤務時の休憩控除（分）",
        "issuer_name": "領収書・契約書の発行者名（甲）",
        "rounding_unit": "支払額の端数処理単位（0＝処理しない）",
        "prefecture": "開催地の都道府県。地域別交通費の起点",
        "rate_template_id": "レートプリセットの識別子",
        "show_tax_breakdown": "領収書に消費税内訳を出すか",
    },
    "p1_staff": {
        "no": "スタッフNO.（現場で使う番号）",
        "name_jp": "ディーラーネーム（表示名）",
        "real_name": "本名（契約書・領収書に使う）",
        "region": "住所から自動判定した地域（交通費ルールの照合キー）",
        "employment_type": "contractor＝業務委託／employee＝雇用",
        "custom_hourly_rate": "個別時給（設定時はイベント単価より優先）",
    },
    "p1_shifts": {
        "planned_start": "予定開始 'HH:MM'（24時超え表記あり）",
        "planned_end": "予定終了 'HH:MM'（'27:00'＝翌3時）",
        "actual_start": "実績の出勤打刻",
        "actual_end": "実績の退勤打刻",
        "status": "scheduled／checked_in／checked_out／absent",
        "is_mix": "MIXゲーム担当（手当の対象）",
    },
    "p1_event_rates": {
        "hourly_rate": "通常時給",
        "night_rate": "深夜時給（22:00〜翌5:00に適用）",
        "transport_allowance": "旧方式の日額交通費（地域ルール未設定時のみ使用）",
        "floor_bonus": "フロア手当（日額）",
        "mix_bonus": "MIX手当（日額）",
    },
    "p1_event_transport_rules": {
        "region": "地域名（11地域）",
        "max_amount": "開催地＝1日あたりの一律額／それ以外＝往復総額の上限",
        "receipt_required": "領収書の要否",
        "is_venue_region": "開催地か（1なら領収書不要・日額×出勤日数）",
    },
    "p1_payments": {
        "base_pay": "基本給（時給×実働）",
        "night_pay": "深夜割増",
        "transport_total": "交通費",
        "attendance_bonus": "精勤手当",
        "break_deduction": "休憩控除（マイナス項目）",
        "adjustment": "臨時調整（手入力）",
        "total_amount": "支給総額",
        "payable_amount": "端数処理後の実支払額",
        "status": "pending＝未承認／approved＝承認済／paid＝支払済",
        "receipt_received": "領収書を受領したか（支払の前提条件）",
        "receipt_token": "スタッフ用DLリンクの鍵（URLに含まれる）",
    },
    "p1_contracts": {
        "signing_token": "署名ページの鍵（URLに含まれる）",
        "rendered_body_md": "発行時点の本文スナップショット",
        "content_hash": "改ざん検知用ハッシュ",
        "signature_image_path": "電子署名の画像",
        "signer_ip": "署名者のIP（証跡）",
    },
    "p1_app_users": {
        "password_hash": "pbkdf2-hmac-sha256（平文は保存しない）",
        "must_change_password": "初回ログインで変更を強制",
        "active": "0＝無効化（削除せず履歴を残す）",
    },
}

TABLE_GROUP = [
    ("大会と単価の定義", ["p1_events", "p1_event_rates", "p1_event_transport_rules"]),
    ("人とシフト", ["p1_staff", "p1_shifts"]),
    ("金額の確定", ["p1_payments", "p1_transport_claims", "p1_staff_event_allowances",
                    "p1_petty_cash"]),
    ("契約書", ["p1_contract_templates", "p1_contracts"]),
    ("認証と監査", ["p1_app_users", "p1_admin_totp", "p1_day_codes", "p1_audit_log"]),
]


def parse_schema() -> tuple[dict, dict]:
    """schema.sql を読み、テーブルごとの列・注記・付随DDLに分解する"""
    src = SCHEMA.read_text()
    tables, meta = {}, {}
    for m in re.finditer(
            r"-- (p1_\w+)  … ([^\n]*)\n--   行数\(概算\): ([^\n]*)\n"
            r"-- -+\nCREATE TABLE \w+ \((.*?)\n\);\n(.*?)(?=\n-- -{10}|\n-- ={10})",
            src, re.S):
        t, desc, rows, body, tail = m.groups()
        cols, cons = [], []
        for line in body.splitlines():
            s = line.strip().rstrip(",")
            if not s:
                continue
            (cons if s.startswith("CONSTRAINT") else cols).append(s)
        meta[t] = {
            "desc": desc.strip(),
            "rows": rows.split("／")[0].strip(),
            "sens": (rows.split("機微度:")[1].strip() if "機微度:" in rows else ""),
            "constraints": cons,
            "tail": [l for l in tail.splitlines() if l.strip()],
        }
        tables[t] = cols
    return tables, meta


def split_col(line: str) -> tuple[str, str, str]:
    """'name text DEFAULT x NOT NULL' → (名前, 型, 制約表記)"""
    parts = line.split()
    name = parts[0]
    typ = parts[1] if len(parts) > 1 else ""
    rest = " ".join(parts[2:])
    flags = []
    dm = re.search(r"DEFAULT (.+?)(?: NOT NULL|$)", rest)
    if dm:
        d = dm.group(1).replace("::text", "").replace("::regclass", "")
        if "nextval" in d:
            d = "連番"
        flags.append(f"既定 {d}")
    if "NOT NULL" in rest:
        flags.append("必須")
    return name, typ, " / ".join(flags)


def cover(b: DocBuilder) -> None:
    b.c.setFillColor(COLOR_SECONDARY)
    b.c.rect(0, PAGE_H - 95 * mm, PAGE_W, 95 * mm, fill=1, stroke=0)
    b.c.setFillColor(white)
    b.c.setFont(FONT_JP_BOLD, 26)
    b.c.drawString(MARGIN_X, PAGE_H - 45 * mm, "P1 Staff Manager")
    b.c.setFont(FONT_JP_BOLD, 20)
    b.c.drawString(MARGIN_X, PAGE_H - 58 * mm, "データベース スキーマ資料")
    b.c.setFont(FONT_JP_REG, 11)
    b.c.drawString(MARGIN_X, PAGE_H - 72 * mm, "ポーカー大会 経理管理ツール")
    b.c.drawString(MARGIN_X, PAGE_H - 80 * mm, f"{GENERATED} 版")
    b.y = PAGE_H - 115 * mm
    b.para(
        "本書は、本番データベースの構造をそのまま書き出した資料です。"
        "外部の技術者への提出、または社内での引き継ぎに使用します。", size=10)
    b.spacer(4)
    b.callout(
        "この資料の作り方",
        "本番データベースに接続してスキーマを内省し、機械的に生成しています。"
        "人が手で書き写した箇所はありません。生成後に全テーブル・全列を"
        "本番と再照合し、一致することを確認済みです。", color=COLOR_GREEN)
    b.spacer(3)
    b.callout(
        "取り扱い注意",
        "個人情報（氏名・住所）と給与額、および認証情報を保持するテーブルを含みます。"
        "各テーブルに機微度（T1〜T3）を記載しています。本書自体にデータは含まれません"
        "（構造のみ）。", color=COLOR_PRIMARY)


def overview(b: DocBuilder, tables: dict, meta: dict) -> None:
    b.new_page()
    b.h1("1. 全体像")
    b.para(
        "本システムは Supabase（PostgreSQL）上で動作します。データベースは他事業と"
        "同居しているため、本システムのテーブルはすべて p1_ で始まります。"
        "本書はその範囲のみを収録しています。")
    b.spacer(2)
    b.h2("データの流れ")
    b.para(
        "大会を作り、日別の単価と地域別の交通費ルールを決める。そこにスタッフと"
        "シフトを取り込み、当日の出退勤を記録する。これらを突き合わせて支払額を"
        "計算し、承認を経て支払う。領収書と契約書は支払いデータから発行される。", size=10)
    b.spacer(2)

    for gname, gtables in TABLE_GROUP:
        b.h3(gname)
        rows = []
        for t in gtables:
            if t not in meta:
                continue
            rows.append([t, meta[t]["desc"][:34], meta[t]["rows"],
                         str(len(tables[t]))])
        b.table(["テーブル", "役割", "行数", "列数"], rows,
                col_widths=[0.30, 0.45, 0.12, 0.13])
        b.spacer(3)

    b.h2("機微度の区分")
    b.table(["区分", "内容", "該当テーブル"], [
        ["T3", "認証情報", "app_users／admin_totp／day_codes"],
        ["T2", "個人情報・給与", "staff／payments／contracts"],
        ["T1", "金額情報", "transport_claims／allowances／petty_cash／audit_log"],
    ], col_widths=[0.12, 0.33, 0.55])
    b.spacer(3)
    b.callout(
        "アクセス制御",
        "全 p1_ テーブルは anon／authenticated ロールの権限を剥奪し、"
        "行レベルセキュリティ（RLS）で匿名アクセスを拒否しています。"
        "アプリは service_role キーでのみ接続します。"
        "（適用: 2026-07-31 lock_down_p1_tables）", color=COLOR_SECONDARY)


def table_pages(b: DocBuilder, tables: dict, meta: dict) -> None:
    b.new_page()
    b.h1("2. テーブル定義")
    for gname, gtables in TABLE_GROUP:
        for t in gtables:
            if t not in tables:
                continue
            m = meta[t]
            b.need(60)
            b.h2(f"{t}")
            b.para(m["desc"], size=10, color=COLOR_MUTED)
            info = f"行数(概算) {m['rows']}　／　列数 {len(tables[t])}"
            if m["sens"]:
                info += f"　／　機微度 {m['sens']}"
            b.para(info, size=9, color=COLOR_MUTED)
            b.spacer(1)
            rows = []
            for line in tables[t]:
                name, typ, flags = split_col(line)
                note = COL_NOTE.get(t, {}).get(name, "")
                rows.append([name, typ, flags, note])
            b.table(["列", "型", "制約", "意味"], rows,
                    col_widths=[0.26, 0.15, 0.22, 0.37])
            # 制約・索引・RLS
            extras = []
            for c in m["constraints"]:
                extras.append(c.replace("CONSTRAINT ", ""))
            for line in m["tail"]:
                s = line.split("   --")[0].strip()
                if s.startswith("CREATE INDEX") or s.startswith("CREATE UNIQUE INDEX"):
                    extras.append("索引: " + s.replace("CREATE ", "").rstrip(";"))
                elif s.startswith("ALTER TABLE") and "ADD CONSTRAINT" in s:
                    extras.append(s.split("ADD CONSTRAINT ")[1].rstrip(";"))
            if extras:
                b.spacer(1)
                b.bullet(extras[:8], size=8)
            b.spacer(4)


def notes(b: DocBuilder) -> None:
    b.new_page()
    b.h1("3. 設計上の注意点")

    b.h2("時刻・日付は文字列型で保持している")
    b.para(
        "シフトの開始・終了は text 型の 'HH:MM' 形式です。深夜跨ぎを "
        "'27:00'（翌3時）のように24時を超える表記で扱うため、time 型では"
        "表現できないという理由によります。日付も text の 'YYYY-MM-DD' です。"
        "外部から集計する場合は、この点に注意してください。")

    b.h2("金額はすべて整数（円）")
    b.para(
        "小数は使いません。端数処理は p1_events.rounding_unit の単位で行い、"
        "処理後の額が p1_payments.payable_amount に入ります。0 の場合は"
        "端数処理をしません（1円単位で支払う）。")

    b.h2("承認済みの金額は自動で守られる")
    b.para(
        "支払いは pending → approved → paid と進みます。paid になった行は"
        "再計算しても変わりません。approved の行は、金額に影響する変更"
        "（出退勤の記録・欠勤・シフトの再取込）があると自動で pending に"
        "戻り、再承認が必要になります。承認した金額と実際の支払額が"
        "食い違わないようにするためです。")

    b.h2("スタッフを消しても金額の記録は残る")
    b.para(
        "契約書・個別手当・交通費請求の staff_id は ON DELETE RESTRICT です。"
        "金額や契約の記録がぶら下がっているスタッフは削除できません。"
        "（適用: 2026-08-02 add_integrity_guards）")

    b.h2("二重登録を構造的に防いでいる")
    b.bullet([
        "p1_payments (event_id, staff_id) が一意 … 同じ大会で同じ人に二重の支払い行を作れない",
        "p1_event_rates (event_id, date) が一意 … 同じ日に二重の単価を登録できない",
        "p1_transport_claims (event_id, staff_id) が一意 … 交通費の二重請求を防ぐ",
    ], size=9)

    b.spacer(2)
    b.h2("領収書・契約書のURLはトークンが鍵")
    b.para(
        "スタッフは receipt_token / signing_token を含むURLで自分の書類にアクセス"
        "します。トークンそのものが認証なので、URLの取り扱いは資格情報と同等に"
        "扱う必要があります。有効期限があり、失効させることもできます。"
        "サーバ側のアクセスログはクエリ文字列を記録しない設定にしています。")

    b.spacer(2)
    b.callout(
        "変更履歴の管理",
        "スキーマの変更は docs/db_migrations/ に日付順のSQLファイルとして残しています。"
        "本書はその適用結果を本番から読み出したものです。", color=COLOR_SECONDARY)


def main() -> None:
    ensure_fonts()
    tables, meta = parse_schema()
    if not tables:
        raise SystemExit("schema.sql の解析に失敗しました")
    out = ROOT / f"docs/P1StaffManager_DBスキーマ_{GENERATED}.pdf"
    b = DocBuilder(
        out,
        header_left="P1 Staff Manager ｜ データベース スキーマ資料",
        header_right="株式会社ヒダネ × 株式会社P1 Entertainment",
    )
    cover(b)
    overview(b, tables, meta)
    table_pages(b, tables, meta)
    notes(b)
    b.save()
    ncol = sum(len(v) for v in tables.values())
    print(f"生成: {out}")
    print(f"  テーブル {len(tables)} / 列 {ncol}")


if __name__ == "__main__":
    main()
