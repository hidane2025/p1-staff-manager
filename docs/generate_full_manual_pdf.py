"""P1 Staff Manager 完全操作マニュアル PDF生成

全機能（スタッフ・シフト・支払い・封筒・出退勤・レポート・年間・交通費・領収書）
を網羅した操作マニュアルを出力する。
"""

from __future__ import annotations

from pathlib import Path

# receipt manualで作ったDocBuilderを再利用
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_receipt_manual_pdf import (  # noqa
    DocBuilder, ensure_fonts,
    COLOR_PRIMARY, COLOR_SECONDARY, COLOR_INK, COLOR_MUTED,
    COLOR_BG_LIGHT, COLOR_BG_BOX, COLOR_GREEN,
    FONT_JP_REG, FONT_JP_BOLD,
    PAGE_W, PAGE_H, MARGIN_X, MARGIN_TOP,
)
from reportlab.lib.colors import HexColor, white
from reportlab.lib.units import mm


ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "test_e2e" / "screenshots"
OUT = ROOT / "docs" / "MANUAL_P1_Staff_Manager_完全版.pdf"


# ========================================================================
# 表紙
# ========================================================================
def cover_page(b: DocBuilder) -> None:
    c = b.c
    c.setFillColor(COLOR_SECONDARY)
    c.rect(0, PAGE_H * 0.55, PAGE_W, PAGE_H * 0.45, fill=1, stroke=0)
    c.setFillColor(COLOR_PRIMARY)
    c.rect(0, PAGE_H * 0.52, PAGE_W, 3 * mm, fill=1, stroke=0)

    c.setFillColor(white)
    c.setFont(FONT_JP_BOLD, 40)
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.80, "P1 Staff Manager")
    c.setFont(FONT_JP_REG, 20)
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.72, "完全操作マニュアル")

    c.setFont(FONT_JP_REG, 12)
    c.setFillColor(HexColor("#F0C0B0"))
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.62,
                         "イベント経理管理システム  ｜  v3.4  ｜  2026-04-17")

    # 下半分: 機能一覧マトリクス
    c.setFillColor(COLOR_INK)
    c.setFont(FONT_JP_REG, 11)
    c.drawCentredString(PAGE_W / 2, PAGE_H * 0.44,
                         "スタッフ管理から領収書発行まで、大会経理の全工程をひとつのツールで")

    # 11機能グリッド
    features = [
        ("🧑 スタッフ管理", "登録・一括取込・検索"),
        ("📅 シフト取込", "CSV/TSV自動パース"),
        ("💰 支払い計算", "時給・深夜・手当・丸め"),
        ("✉ 封筒リスト", "紙幣内訳自動計算"),
        ("🕒 出退勤", "凍結一括退勤対応"),
        ("📊 精算レポート", "現金照合・CSV出力"),
        ("📆 年間累計", "確定申告・法定調書"),
        ("🚃 交通費", "地域別上限・領収書"),
        ("📄 領収書発行", "一括PDF・URL配布"),
        ("🏢 発行者設定", "インボイス後日対応"),
        ("🔐 スタッフDL", "トークン認証"),
    ]
    card_w = 56 * mm
    card_h = 18 * mm
    col = 3
    margin = 4 * mm
    total_w = col * card_w + (col - 1) * margin
    start_x = (PAGE_W - total_w) / 2
    start_y = PAGE_H * 0.38
    for i, (title, sub) in enumerate(features):
        x = start_x + (i % col) * (card_w + margin)
        y = start_y - (i // col) * (card_h + margin)
        c.setFillColor(COLOR_BG_LIGHT)
        c.rect(x, y - card_h, card_w, card_h, fill=1, stroke=0)
        c.setFillColor(COLOR_PRIMARY)
        c.rect(x, y - 2 * mm, card_w, 2 * mm, fill=1, stroke=0)
        c.setFillColor(COLOR_SECONDARY)
        c.setFont(FONT_JP_BOLD, 10)
        c.drawString(x + 3 * mm, y - 7 * mm, title)
        c.setFillColor(COLOR_INK)
        c.setFont(FONT_JP_REG, 8)
        c.drawString(x + 3 * mm, y - 13 * mm, sub)

    c.setFillColor(COLOR_MUTED)
    c.setFont(FONT_JP_REG, 9)
    c.drawCentredString(PAGE_W / 2, 20 * mm,
                         "開発: 株式会社ヒダネ AI部  ／  運用: 株式会社パシフィック")

    c.showPage()
    b.page_no += 1
    b.y = PAGE_H - MARGIN_TOP
    b._draw_header_footer()


# ========================================================================
# 目次
# ========================================================================
def toc_page(b: DocBuilder) -> None:
    b.h1("目次")
    toc = [
        ("第1章 このツールの全体像", ""),
        ("  1-1. P1 Staff Manager とは", "p.4"),
        ("  1-2. システム構成", "p.5"),
        ("  1-3. データの流れ", "p.6"),
        ("第2章 初期セットアップ", ""),
        ("  2-1. 最初にやること（管理者）", "p.7"),
        ("  2-2. Supabase設定", "p.8"),
        ("  2-3. Streamlit Cloudデプロイ", "p.9"),
        ("第3章 各機能の操作ガイド", ""),
        ("  3-0. ホーム画面", "p.10"),
        ("  3-1. スタッフ管理", "p.11"),
        ("  3-2. シフト取込", "p.13"),
        ("  3-3. 支払い計算", "p.14"),
        ("  3-4. 封筒リスト", "p.16"),
        ("  3-5. 出退勤", "p.17"),
        ("  3-6. 精算レポート", "p.19"),
        ("  3-7. 年間累計", "p.20"),
        ("  3-8. 交通費", "p.21"),
        ("  3-9. 領収書デジタル発行", "p.23"),
        ("第4章 典型的な運用フロー", ""),
        ("  4-1. 大会前の準備", "p.26"),
        ("  4-2. 大会当日", "p.27"),
        ("  4-3. 大会後（精算・支払・領収書）", "p.28"),
        ("第5章 困ったときは", ""),
        ("  5-1. トラブルシューティング", "p.29"),
        ("  5-2. FAQ", "p.30"),
        ("第6章 技術情報（参考）", ""),
        ("  6-1. ファイル構成", "p.32"),
        ("  6-2. 今後の拡張予定", "p.33"),
    ]
    for title, page in toc:
        b.need(7)
        if page == "":
            # 章タイトル
            b.spacer(2)
            b.c.setFillColor(COLOR_PRIMARY)
            b.c.setFont(FONT_JP_BOLD, 12)
            b.c.drawString(MARGIN_X, b.y, title)
            b.y -= 7 * mm
        else:
            b.c.setFillColor(COLOR_INK)
            b.c.setFont(FONT_JP_REG, 10)
            b.c.drawString(MARGIN_X + 3 * mm, b.y, title)
            text_w = b.c.stringWidth(title, FONT_JP_REG, 10)
            dot_start = MARGIN_X + 3 * mm + text_w + 3 * mm
            dot_end = PAGE_W - MARGIN_X - 15 * mm
            b.c.setFillColor(COLOR_MUTED)
            for xx in range(int(dot_start), int(dot_end), 3):
                b.c.circle(xx, b.y + 1, 0.3, fill=1, stroke=0)
            b.c.setFillColor(COLOR_SECONDARY)
            b.c.drawRightString(PAGE_W - MARGIN_X, b.y, page)
            b.y -= 6 * mm


# ========================================================================
# 第1章
# ========================================================================
def chapter1(b: DocBuilder) -> None:
    b.new_page()
    b.h1("第1章 このツールの全体像")

    b.h2("1-1. P1 Staff Manager とは")
    b.para("P1 Staff Manager は、ポーカー大会（P1・USOPなど）の経理業務をまるごと自動化する"
           "クラウドアプリです。スタッフ登録、シフト管理、給与計算、支払い、"
           "領収書発行、年間累計、確定申告用データ作成まで、"
           "これまでExcelと手作業で回していた業務を1つのツールに集約しました。")
    b.spacer(2)

    b.h3("解決できる課題")
    b.bullet([
        "スタッフごとの個別時給（タイミー派遣と業務委託の混在）の計算ミス防止",
        "深夜割増・休憩控除・精勤手当などの手当自動計算",
        "大会最終日の凍結退勤（残業扱い）に伴う再計算の手間削減",
        "封筒ごとの紙幣内訳（万札・千札・小銭）の自動計算",
        "地域別交通費の上限管理と領収書確認",
        "確定申告・法定調書提出のためのスタッフ別年間累計算出",
        "領収書のデジタル発行（印紙代削減・検索性向上）",
    ])
    b.spacer(3)

    b.h3("想定ユーザー")
    b.table(
        ["役職", "主な操作", "権限"],
        [
            ["経理担当（伊藤さん・小島さん）", "全機能・支払・領収書", "フルアクセス"],
            ["現場リーダー（笹尾さん等）", "シフト・出退勤", "フルアクセス"],
            ["スタッフ（各ディーラー）", "領収書DLのみ", "トークンURL経由"],
        ],
        col_widths=[0.38, 0.32, 0.30],
    )

    b.new_page()
    b.h2("1-2. システム構成")
    b.para("ブラウザからアクセスするだけで使えるWebアプリです。"
           "PCインストール不要、スマホでも操作可能（一部画面は推奨PC）。")
    b.spacer(2)

    b.h3("技術スタック")
    b.table(
        ["層", "技術", "役割"],
        [
            ["フロントエンド", "Streamlit", "Web UI・全8ページ"],
            ["バックエンド", "Python 3.11", "ビジネスロジック"],
            ["データベース", "Supabase (PostgreSQL)", "全データ永続化"],
            ["ストレージ", "Supabase Storage", "領収書PDF保管"],
            ["デプロイ", "Streamlit Cloud", "GitHub連携で自動デプロイ"],
            ["PDF生成", "ReportLab", "領収書・マニュアル生成"],
        ],
        col_widths=[0.25, 0.35, 0.40],
    )

    b.callout("アクセス方法",
              "ブラウザで https://p1-staff-manager.streamlit.app にアクセスするだけ。"
              "インストール作業は不要です。スマホからでもほぼ全機能が使えますが、"
              "一覧表示や一括編集はPCを推奨します。",
              color=COLOR_GREEN)

    b.new_page()
    b.h2("1-3. データの流れ")
    b.para("各機能間のデータの流れを把握しておくと、トラブル時の対処が早くなります。")
    b.spacer(2)

    flow_steps = [
        ("1", "スタッフ登録", "スタッフマスタDBに本名・住所・時給・区分などを登録"),
        ("2", "イベント作成", "大会の日程・会場・レートを設定"),
        ("3", "シフト取込", "CSVで日付×スタッフの勤務時間を登録"),
        ("4", "出退勤打刻", "実績データを入力（欠勤・遅刻・凍結対応）"),
        ("5", "支払い計算", "実績×レートで各スタッフの報酬を自動計算"),
        ("6", "承認", "経理責任者が金額確認→承認"),
        ("7", "支払い", "現金渡し→封筒リストで紙幣準備→渡し済み記録"),
        ("8", "領収書発行", "承認済みをPDF化→URL配布→スタッフDL"),
        ("9", "精算レポート", "日次/大会の売上・支出を集計"),
        ("10", "年間累計", "確定申告・法定調書用のスタッフ別集計"),
    ]
    for num, title, desc in flow_steps:
        b.need(10)
        b.c.setFillColor(COLOR_PRIMARY)
        b.c.circle(MARGIN_X + 5 * mm, b.y - 2 * mm, 4 * mm, fill=1, stroke=0)
        b.c.setFillColor(white)
        b.c.setFont(FONT_JP_BOLD, 10)
        b.c.drawCentredString(MARGIN_X + 5 * mm, b.y - 3.5 * mm, num)
        b.c.setFillColor(COLOR_SECONDARY)
        b.c.setFont(FONT_JP_BOLD, 11)
        b.c.drawString(MARGIN_X + 15 * mm, b.y - 1 * mm, title)
        b.c.setFillColor(COLOR_INK)
        b.c.setFont(FONT_JP_REG, 9)
        b.c.drawString(MARGIN_X + 50 * mm, b.y - 1 * mm, desc)
        b.y -= 8 * mm


# ========================================================================
# 第2章
# ========================================================================
def chapter2(b: DocBuilder) -> None:
    b.new_page()
    b.h1("第2章 初期セットアップ")

    b.h2("2-1. 最初にやること（管理者）")
    b.para("ツール初回利用時の準備事項です。2026-04-17時点で全て完了済みです。"
           "将来引き継ぎが発生した場合の参考用に手順を残します。")
    b.spacer(2)

    b.bullet([
        "① Supabaseアカウント作成（無料プラン可）",
        "② データベーステーブルのマイグレーション（SQLファイル実行）",
        "③ Storageバケット『receipts』作成＋RLSポリシー設定",
        "④ GitHubリポジトリ作成＋コードpush",
        "⑤ Streamlit Cloudでアプリをデプロイ",
        "⑥ secrets.toml に Supabase URL・APIキーを設定",
        "⑦ ブラウザで動作確認",
    ])

    b.h2("2-2. Supabase設定")
    b.h3("プロジェクト作成")
    b.bullet([
        "Supabase (https://supabase.com) にサインアップ",
        "New project → Region: Tokyo (ap-northeast-1) 推奨",
        "DBパスワードは強固なものを設定し、パスワードマネージャに保管",
    ])

    b.h3("マイグレーション実行")
    b.para("プロジェクト作成後、SQL Editorで下記ファイルを順次実行してください。")
    b.table(
        ["#", "SQLファイル", "内容"],
        [
            ["1", "01_init_schema.sql", "基本テーブル（スタッフ・イベント・シフト等）"],
            ["2", "02_add_payment_metadata.sql", "支払いに承認者・メモ列追加"],
            ["3", "03_add_transport_rules.sql", "交通費ルール・領収書請求テーブル"],
            ["4", "20260417_add_receipt_columns.sql", "領収書デジタル発行用列"],
        ],
        col_widths=[0.08, 0.47, 0.45],
    )

    b.h3("Storageバケット作成")
    b.bullet([
        "Name: receipts",
        "Public: OFF（必ずOFFに）",
        "File size limit: 5MB",
        "Allowed MIME types: application/pdf",
        "さらに4つのRLSポリシー（INSERT/SELECT/UPDATE/DELETE）を実行",
    ])

    b.new_page()
    b.h2("2-3. Streamlit Cloudデプロイ")
    b.bullet([
        "https://streamlit.io/cloud にGitHubアカウントでサインイン",
        "New app → リポジトリ選択 → Main file path: app.py",
        "Advanced settings → Secrets に以下を貼り付け:",
        "    SUPABASE_URL = 'https://XXXXX.supabase.co'",
        "    SUPABASE_ANON_KEY = 'eyJhbGciOi...'",
        "Deploy クリック → 3〜5分でURLが払い出される",
    ])
    b.callout("自動デプロイ",
              "mainブランチにgit pushすると、数十秒で本番に反映されます。"
              "機能追加・修正は手元でコミット→pushするだけで即反映。",
              color=COLOR_GREEN)

    b.h2("現行の本番環境")
    b.table(
        ["項目", "値"],
        [
            ["本番URL", "https://p1-staff-manager.streamlit.app"],
            ["Supabaseプロジェクト", "fmqalkwkxckbxxijiprp"],
            ["GitHubリポジトリ", "（中野さん管理）"],
            ["デプロイ方式", "GitHub push → 自動デプロイ"],
        ],
        col_widths=[0.3, 0.7],
    )


# ========================================================================
# 第3章 - 各機能ガイド
# ========================================================================
def feature_page(b: DocBuilder, num: str, title: str, desc: str,
                  image: str, bullets: list[str],
                  table_data: tuple | None = None,
                  tips: str = "") -> None:
    b.new_page()
    b.h1(f"3-{num}. {title}")
    b.para(desc)
    b.spacer(2)
    if image:
        img_path = SHOTS / image
        b.image(img_path, caption=f"「{title}」画面", max_h_mm=90)
    b.h3("主な機能")
    b.bullet(bullets)
    if table_data:
        headers, rows, widths = table_data
        b.h3("詳細")
        b.table(headers, rows, col_widths=widths)
    if tips:
        b.callout("運用のコツ", tips, color=COLOR_SECONDARY)


def chapter3(b: DocBuilder) -> None:
    b.new_page()
    b.h1("第3章 各機能の操作ガイド")
    b.para("P1 Staff Manager の8つの基本機能＋3つの領収書関連機能を順番に解説します。"
           "各機能の画面スクリーンショットと操作手順を掲載しています。")

    # ホーム
    b.new_page()
    b.h1("3-0. ホーム画面")
    b.para("ツールのトップページ。サイドバーから各機能にアクセスできます。"
           "カード状のリンクからもジャンプ可能です。")
    b.image(SHOTS / "page_home.png", caption="ホーム画面", max_h_mm=100)
    b.bullet([
        "サイドバー: 全ページへの固定リンク",
        "メインカード: アイコン付きで機能ジャンプ",
        "フッター: バージョン情報（現在 v3.4）",
    ])

    # 3-1 スタッフ管理
    b.new_page()
    b.h1("3-1. スタッフ管理")
    b.para("スタッフの登録・検索・一括取込・編集を行う画面です。"
           "本名・住所・メール・最寄駅・雇用区分・個別時給まで一元管理できます。")
    b.image(SHOTS / "page_1_staff.png", caption="スタッフ管理画面", max_h_mm=90)

    b.h3("主な機能")
    b.bullet([
        "スタッフ検索（名前・NO.・雇用区分で絞り込み）",
        "一覧表示（住所・メール記入状況も一目瞭然）",
        "個別編集（✏️ボタン）",
        "一括登録（CSV / TSV / 表編集 の3方式）",
        "住所から地域（近畿・東海・関東など）自動判定",
        "雇用区分の区別（業務委託 / タイミー / 正社員）",
    ])

    b.h3("雇用区分の違い")
    b.table(
        ["区分", "時給", "深夜割増", "手当", "精勤"],
        [
            ["業務委託 (contractor)", "レート準拠", "あり", "フロア/MIX", "対象"],
            ["タイミー (timee)", "個別設定", "なし（同一時給）", "なし", "対象外"],
            ["正社員 (fulltime)", "レート準拠", "あり", "フロア/MIX", "対象"],
        ],
        col_widths=[0.32, 0.20, 0.18, 0.18, 0.12],
    )

    b.new_page()
    b.h2("一括登録の3方式")
    b.h3("方式A: CSVアップロード")
    b.bullet([
        "列: no, name_jp, name_en, real_name, address, email, nearest_station, contact, role, employment_type, custom_hourly_rate, notes",
        "UTF-8 with BOM 推奨",
        "既存NO.があれば更新、なければ新規追加",
    ])

    b.h3("方式B: テキスト貼り付け（TSV/CSV）")
    b.bullet([
        "Excelから列を選択→コピー→テキスト貼り付け",
        "タブ区切りを自動判定",
        "数百人規模でも瞬時に取込可能",
    ])

    b.h3("方式C: 表編集")
    b.bullet([
        "画面上で直接セルを編集",
        "行追加・削除もボタンで操作",
        "少人数調整に便利",
    ])

    b.callout("地域自動判定",
              "住所を入れると自動的に47都道府県→11地域（近畿・東海・関東・九州など）"
              "にマッピングされます。交通費の地域別上限適用に使われます。",
              color=COLOR_SECONDARY)

    # 3-2 シフト取込
    b.new_page()
    b.h1("3-2. シフト取込")
    b.para("大会のシフト表CSVを取り込み、自動で支払い計算に連携します。")
    b.image(SHOTS / "page_2_shift.png", caption="シフト取込画面", max_h_mm=100)

    b.h3("取込できるCSV形式")
    b.bullet([
        "1行目: ヘッダー（役職, NO., 名前, NAME, 日付列…）",
        "2行目以降: スタッフ1人1行、日付列に勤務時間 '13:00~22:00' 形式で入力",
        "休み: '×' 'x' '-' または空欄",
        "26:00 などの25時超も対応（深夜跨ぎ）",
    ])

    b.h3("取込の流れ")
    b.bullet([
        "① イベントを選択（なければ先に作成）",
        "② CSVファイルをアップロード",
        "③ プレビュー確認（スタッフ名・日付が正しいか）",
        "④「取込実行」ボタン",
        "⑤ 既存シフトは上書き、新規は追加",
    ])

    b.callout("スタッフ登録が先",
              "シフトCSVに含まれるスタッフ名は、事前にスタッフマスタに登録されている必要があります。"
              "未登録スタッフは取込時にスキップされるので、先にスタッフ管理で一括登録を済ませてください。",
              color=COLOR_PRIMARY)

    # 3-3 支払い計算
    b.new_page()
    b.h1("3-3. 支払い計算")
    b.para("シフト実績×レートで各スタッフの支払金額を自動計算します。"
           "業務委託・タイミー・正社員を自動識別し、適切な計算ロジックを適用します。")
    b.image(SHOTS / "page_3_payment.png", caption="支払い計算画面", max_h_mm=90)

    b.h3("計算ロジック")
    b.bullet([
        "通常時間: 時給×実働時間（休憩自動控除）",
        "深夜時間（22時以降）: 深夜時給×時間",
        "フロア手当: ロール=Floor なら日額+3,000円（プレミアム日5,000円）",
        "MIX手当: MIX担当日は+1,500円",
        "精勤手当: 全日稼働で10,000円、一定日数以上で6,000円",
        "タイミー: 個別時給で全時間帯同一レート、手当なし",
    ])

    b.h3("休憩時間の扱い")
    b.table(
        ["労働時間", "休憩控除（デフォルト）"],
        [
            ["6時間以下", "0分"],
            ["6時間超", "45分"],
            ["8時間超", "60分"],
        ],
        col_widths=[0.5, 0.5],
    )

    b.new_page()
    b.h2("500円丸めオプション")
    b.para("合計金額を500円単位で繰り上げできます。"
           "例: 16,300円→16,500円、18,600円→19,000円")
    b.bullet([
        "チェックボックスONで全員分に適用",
        "セッション内で設定保持（ページ離脱しても保持）",
        "現金運用で小銭を減らしたい場合に便利",
    ])

    b.h2("領収書PDF単発発行")
    b.para("画面右側のスタッフカードから、個別に領収書PDFを即時ダウンロードできます。"
           "1名分だけ急ぎで欲しい時に便利。")

    b.h2("承認フロー")
    b.bullet([
        "pending（未承認）: 計算直後の初期状態",
        "approved（承認済み）: 経理責任者が承認ボタンを押した状態",
        "paid（支払済み）: 実際に現金を渡した状態（戻せない）",
    ])

    b.callout("凍結後の自動再計算",
              "出退勤ページで凍結一括退勤を実行すると、該当スタッフの支払いは自動的にpending"
              "に戻ります（paidは保護）。深夜手当の再計算が必要な場合に威力を発揮します。",
              color=COLOR_GREEN)

    # 3-4 封筒リスト
    b.new_page()
    b.h1("3-4. 封筒リスト")
    b.para("各スタッフに渡す現金の紙幣内訳を自動計算し、ラベル印刷できる形で表示します。"
           "両替の手間を最小化する最適配分。")
    b.image(SHOTS / "page_4_envelope.png", caption="封筒リスト画面", max_h_mm=100)

    b.h3("機能")
    b.bullet([
        "スタッフ別の紙幣内訳（1万・5千・千・500円）自動計算",
        "全体合計の紙幣合算（両替時の銀行準備に）",
        "スタッフ別ラベルCSV出力",
        "封筒に貼るラベルのプレビュー",
    ])

    b.callout("紙幣最適化",
              "できるだけ大きい額面から使う貪欲法で計算しているので、両替に必要な最少枚数になります。"
              "500円刻みで支払額を設定している場合、500円玉だけで小口処理できるケースが多数。",
              color=COLOR_SECONDARY)

    # 3-5 出退勤
    b.new_page()
    b.h1("3-5. 出退勤")
    b.para("スタッフのチェックイン・チェックアウトを記録します。"
           "大会最終日の『凍結一括退勤』にも対応。")
    b.image(SHOTS / "page_5_attendance.png", caption="出退勤画面", max_h_mm=100)

    b.h3("4つのタブ")
    b.bullet([
        "凍結退勤: 最終日に全員を一括で同時刻退勤扱いに（残業計算）",
        "個別打刻: チェックイン・チェックアウトを1人ずつ記録",
        "欠勤登録: 当日来なかったスタッフを欠勤扱い",
        "遅刻修正: 計画時刻から実際の出勤時刻にずらす",
    ])

    b.new_page()
    b.h2("凍結一括退勤の仕組み")
    b.para("大会最終日は、シフト表の計画終了時刻より後まで全員が残って"
           "集計作業を手伝うため、『26:00まで全員残業』扱いにする運用があります。"
           "これを手作業で打刻すると膨大な手間になるため、一括処理機能を用意しました。")
    b.bullet([
        "対象日と退勤時刻を指定",
        "欠勤・既に退勤済みのスタッフは対象外",
        "影響を受けたスタッフの承認済み支払いは自動的にpendingへ戻る",
        "支払済み(paid)は保護（上書きされない）",
    ])

    b.callout("なぜ自動リセットが必要？",
              "凍結退勤により深夜手当が大きく変わるため、既に承認済みの金額が実態と合わなくなります。"
              "再計算→再承認の流れを強制することで、金額齟齬を防ぎます。",
              color=COLOR_PRIMARY)

    # 3-6 精算レポート
    b.new_page()
    b.h1("3-6. 精算レポート")
    b.para("大会1回分の金銭精算レポートを表示します。"
           "日別集計、現金照合、CSV出力などの機能を備えます。")
    b.image(SHOTS / "page_6_report.png", caption="精算レポート画面", max_h_mm=100)

    b.h3("表示内容")
    b.bullet([
        "大会の日別売上・支出集計",
        "スタッフ支払い合計（承認済み/支払済み/未承認別）",
        "交通費合計",
        "雑費（Petty Cash）集計",
        "現金実残額 vs 理論残額の照合",
        "CSV出力で経理ソフトへ連携可能",
    ])

    # 3-7 年間累計
    b.new_page()
    b.h1("3-7. 年間累計")
    b.para("確定申告・法定調書提出に必須の、スタッフ別年間累計額を算出します。"
           "50万円超の業務委託先は法定調書提出対象。")
    b.image(SHOTS / "page_7_yearly.png", caption="年間累計画面", max_h_mm=100)

    b.h3("主な機能")
    b.bullet([
        "年度指定（2026年、2025年など）",
        "スタッフ別年間支払額ランキング",
        "法定調書対象者（50万円超）の自動ハイライト",
        "CSV出力（住所・マイナンバー記入欄付きテンプレ）",
        "本名・住所・メール一括確認",
    ])

    b.callout("法定調書について",
              "年間50万円超を支払った業務委託先は、翌年1月末までに『支払調書』を税務署に提出する義務があります。"
              "このページで対象者を一括抽出し、住所などの不足情報を確認できます。",
              color=COLOR_PRIMARY)

    # 3-8 交通費
    b.new_page()
    b.h1("3-8. 交通費")
    b.para("大会ごとの地域別交通費上限を設定し、スタッフの領収書金額を記録・承認します。"
           "開催地に近い地域は一律少額、遠方は上限額まで実費支給という運用を自動化。")
    b.image(SHOTS / "page_8_transport.png", caption="交通費画面", max_h_mm=100)

    b.h3("4つのセクション")
    b.bullet([
        "地域別ルール設定（11地域それぞれに上限・領収書要否・開催地フラグ）",
        "事前見積（スタッフ人数×地域別上限で大まかな交通費予算）",
        "領収書入力（スタッフごとに実費金額を記録、上限超過は自動丸め）",
        "合計サマリ（大会全体の交通費予算・実費照合）",
    ])

    b.new_page()
    b.h2("地域の自動判定")
    b.para("スタッフの住所（47都道府県）から11地域に自動分類されます。")
    b.table(
        ["地域", "都道府県例"],
        [
            ["北海道", "北海道"],
            ["東北", "青森・岩手・宮城・秋田・山形・福島"],
            ["関東", "東京・神奈川・千葉・埼玉・茨城・栃木・群馬"],
            ["甲信越", "新潟・長野・山梨"],
            ["北陸", "富山・石川・福井"],
            ["東海", "愛知・静岡・岐阜・三重"],
            ["近畿", "大阪・京都・兵庫・奈良・滋賀・和歌山"],
            ["中国", "広島・岡山・山口・鳥取・島根"],
            ["四国", "香川・徳島・愛媛・高知"],
            ["九州", "福岡・佐賀・長崎・熊本・大分・宮崎・鹿児島"],
            ["沖縄", "沖縄"],
        ],
        col_widths=[0.2, 0.8],
    )

    b.h3("運用例（大阪開催の場合）")
    b.bullet([
        "近畿（開催地）: 一律1,000円（領収書不要）",
        "東海: 上限8,000円（領収書必須）",
        "関東: 上限15,000円（領収書必須）",
        "九州: 上限20,000円（領収書必須）",
    ])

    # 3-9 領収書
    b.new_page()
    b.h1("3-9. 領収書デジタル発行")
    b.para("承認済みスタッフへ領収書PDFを一括発行し、専用URLで配布する機能。"
           "印紙代ゼロ、インボイス後日対応、DL回数記録の3点が特徴。")

    b.h2("A. 領収書発行画面")
    b.image(SHOTS / "page_A_receipts.png", caption="領収書発行（管理者）", max_h_mm=85)
    b.bullet([
        "イベントを選んで承認済みスタッフを一覧表示",
        "チェックボックスで対象選択",
        "有効期限（デフォルト7日）を指定",
        "一括発行ボタンで全員分PDF生成→Storage保存→URL発行",
        "発行後は画面下部にDLリンク一覧表示（CSV出力可）",
    ])

    b.new_page()
    b.h2("B. 発行者設定画面")
    b.image(SHOTS / "page_B_issuer_settings.png", caption="発行者情報設定", max_h_mm=85)
    b.bullet([
        "発行者名（Pacific社名・住所・電話）",
        "但し書き（デフォルト文言）",
        "インボイス番号（空欄運用OK、後日追加可能）",
        "電子印影URL（PNG推奨）",
        "イベント単位で設定可能",
    ])

    b.h2("C. スタッフ向けDLページ")
    b.image(SHOTS / "page_9_receipt_download_no_token.png",
            caption="スタッフDL画面（トークン検証前）", max_h_mm=70)
    b.bullet([
        "URL例: .../receipt_download?token=xxxx",
        "有効なトークンなら領収書PDFダウンロードボタン表示",
        "無効/期限切れは警告表示",
        "DL回数がカウントされ管理画面に反映",
    ])


# ========================================================================
# 第4章 運用フロー
# ========================================================================
def chapter4(b: DocBuilder) -> None:
    b.new_page()
    b.h1("第4章 典型的な運用フロー")
    b.para("大会1回の経理フロー全体を、時系列で解説します。"
           "慣れた担当者なら全工程合計で2時間程度に短縮可能です。")

    b.h2("4-1. 大会前の準備（1週間前まで）")
    b.bullet([
        "スタッフ管理: 新規スタッフを一括登録（CSV or 表編集）",
        "イベント作成: 大会名・日程・会場・レート設定（プレミアム日は時給UP）",
        "シフト取込: 完成したシフト表CSVをアップロード",
        "交通費ルール: 地域別上限を設定（開催地の地域は一律少額に）",
    ])
    b.callout("必須確認",
              "① 新規スタッフの住所が必ず入っていること（地域自動判定・交通費に必要）。"
              "② 時給設定が各日付ごとに正しくなっていること（プレミアム日の見落としに注意）。",
              color=COLOR_PRIMARY)

    b.h2("4-2. 大会当日")
    b.bullet([
        "開始時: チェックインは省略可（シフト時刻をそのまま使う運用もOK）",
        "欠勤発生時: 出退勤ページで欠勤登録（支払い自動ゼロ化）",
        "遅刻発生時: 実際の出勤時刻に修正（支払い自動再計算）",
        "雑費発生時: 経理タブで Petty Cash 追加",
    ])

    b.new_page()
    b.h2("4-3. 大会後（精算・支払・領収書）")
    b.h3("Day 1: 最終日夜〜翌日")
    b.bullet([
        "① 出退勤ページで凍結一括退勤（最終日の退勤時刻を26:00等に）",
        "② 支払い計算ページ: 全員の支払金額を確認",
        "③ 金額に問題なければ500円丸めON",
        "④ 経理担当が各スタッフを承認",
    ])

    b.h3("Day 2: 支払日")
    b.bullet([
        "⑤ 封筒リストで紙幣内訳確認→銀行で両替",
        "⑥ 現金封入→スタッフへ手渡し",
        "⑦ 支払済み（paid）ステータスに更新",
        "⑧ 領収書発行ページで一括発行→DLリンクをLINE等で配布",
    ])

    b.h3("Day 3以降: 締め")
    b.bullet([
        "⑨ 精算レポートで現金照合（理論残高vs実残高）",
        "⑩ CSV出力して会計ソフトへ連携",
        "⑪ 交通費の領収書原本を保管（電子帳簿保存法に注意）",
    ])

    b.callout("年末の作業",
              "12月末〜1月初旬に、年間累計ページで50万円超の業務委託先を抽出。"
              "住所・マイナンバーを収集して、1月末までに税務署へ支払調書を提出します。",
              color=COLOR_SECONDARY)


# ========================================================================
# 第5章 トラブルシューティング・FAQ
# ========================================================================
def chapter5(b: DocBuilder) -> None:
    b.new_page()
    b.h1("第5章 困ったときは")

    b.h2("5-1. トラブルシューティング")
    issues = [
        ("画面が真っ白・動かない",
         "ブラウザ再読込（Ctrl+R/Cmd+R）。それでもダメなら別タブで開き直し。"
         "Streamlit Cloudの場合、裏でデプロイ中の可能性あり→数分待つ。"),
        ("データが表示されない",
         "Supabase接続エラーの可能性。Streamlit Cloud secrets の SUPABASE_URL と "
         "SUPABASE_ANON_KEY を再確認。Supabaseプロジェクトが稼働中か確認。"),
        ("CSV取込で文字化け",
         "Excelで保存する際に『CSV UTF-8』を選択。Shift-JISは非対応。"
         "macOS標準のNumbersで書き出した場合も要注意（改行コード違い）。"),
        ("スタッフがCSV取込されない",
         "name_jp列が空・または既存と重複している可能性。"
         "エラーメッセージに行番号が表示されるので確認。"),
        ("領収書が生成されない",
         "該当支払が『承認済み』または『支払済み』になっているか確認。"
         "pendingステータスでは発行対象外。"),
        ("DLリンクが切れた",
         "有効期限（デフォルト7日）切れ。領収書発行ページで強制再生成。"),
        ("金額が合わない（計算違い）",
         "雇用区分（タイミー/業務委託）が正しいか、個別時給が入っているか確認。"
         "凍結退勤後は再計算が必要（承認フラグがpendingに戻っているはず）。"),
        ("承認済みを間違えて承認してしまった",
         "支払済み(paid)ならDB直接操作が必要（中野さんまで連絡）。"
         "承認済み(approved)ならpendingに戻す機能が実装予定。"),
    ]
    for issue, answer in issues:
        b.need(22)
        b.c.setFillColor(COLOR_PRIMARY)
        b.c.setFont(FONT_JP_BOLD, 11)
        b.c.drawString(MARGIN_X, b.y, f"❓ {issue}")
        b.y -= 6 * mm
        lines = b._wrap_japanese(answer, PAGE_W - MARGIN_X * 2 - 5 * mm, 10)
        b.c.setFillColor(COLOR_INK)
        b.c.setFont(FONT_JP_REG, 10)
        for ln in lines:
            b.need(5)
            b.c.drawString(MARGIN_X + 3 * mm, b.y, ln)
            b.y -= 5 * mm
        b.y -= 3 * mm

    b.new_page()
    b.h2("5-2. FAQ")
    faq = [
        ("スマホだけで運用できる？",
         "画面表示は可能ですが、一括操作（CSV取込・一括発行）はPC推奨。"
         "出退勤の個別打刻や、領収書1件DLはスマホで問題ありません。"),
        ("複数人で同時に使える？",
         "可能です。ただし同じスタッフの支払いを2人同時に編集すると競合する可能性があるので、"
         "役割分担を推奨（例: 笹尾さん=出退勤、伊藤さん=承認、小島さん=領収書）。"),
        ("データは消える？バックアップは？",
         "Supabaseは自動で7日分のポイントインタイムバックアップを保持します。"
         "手動バックアップも可能（Supabase Dashboard > Database > Backups）。"),
        ("APIで外部連携できる？",
         "Supabaseのテーブルに直接接続可能です。"
         "freee・マネーフォワードなどの会計ソフト連携は個別開発が必要。"),
        ("ユーザー権限分けは？",
         "現状はログイン機能なし（URLを知ってる全員がフルアクセス）。"
         "将来Supabase Authで役割分離予定。スタッフDLはトークンURL経由で隔離済み。"),
        ("契約書のクラウド署名は？",
         "Phase 2で実装予定。電子署名パッド+タイムスタンプ付与で法的強度を確保。"),
        ("年末調整はできる？",
         "業務委託スタッフが中心のため、源泉徴収は原則行っていません。"
         "正社員については別途給与計算ソフト（freee人事労務等）を推奨。"),
        ("インボイス未登録でも大丈夫？",
         "業務委託の領収書は現状インボイス不要。"
         "Pacific側でインボイス登録があった場合は設定画面で番号を入れるだけで自動反映されます。"),
        ("領収書に印紙は貼る？",
         "不要。電子データで発行する領収書には印紙貼付義務はありません（5万円以上でも）。"
         "PDFにもその旨注記を自動表示。"),
    ]
    for q, a in faq:
        b.need(16)
        b.c.setFillColor(COLOR_PRIMARY)
        b.c.setFont(FONT_JP_BOLD, 11)
        b.c.drawString(MARGIN_X, b.y, f"Q. {q}")
        b.y -= 6 * mm
        lines = b._wrap_japanese(a, PAGE_W - MARGIN_X * 2 - 5 * mm, 10)
        b.c.setFillColor(COLOR_INK)
        b.c.setFont(FONT_JP_REG, 10)
        for ln in lines:
            b.need(5)
            b.c.drawString(MARGIN_X + 3 * mm, b.y, ln)
            b.y -= 5 * mm
        b.y -= 3 * mm


# ========================================================================
# 第6章 技術情報
# ========================================================================
def chapter6(b: DocBuilder) -> None:
    b.new_page()
    b.h1("第6章 技術情報（参考）")

    b.h2("6-1. ファイル構成")
    b.table(
        ["カテゴリ", "ファイル", "役割"],
        [
            ["エントリ", "app.py", "トップページ"],
            ["ページ", "pages/1_staff.py", "スタッフ管理"],
            ["", "pages/2_shift.py", "シフト取込"],
            ["", "pages/3_payment.py", "支払い計算"],
            ["", "pages/4_envelope.py", "封筒リスト"],
            ["", "pages/5_attendance.py", "出退勤"],
            ["", "pages/6_report.py", "精算レポート"],
            ["", "pages/7_yearly.py", "年間累計"],
            ["", "pages/8_transport.py", "交通費"],
            ["", "pages/9_receipt_download.py", "スタッフDL"],
            ["", "pages/A_receipts.py", "領収書発行"],
            ["", "pages/B_issuer_settings.py", "発行者設定"],
            ["ロジック", "utils/calculator.py", "給与計算エンジン"],
            ["", "utils/denomination.py", "紙幣内訳計算"],
            ["", "utils/region.py", "地域判定"],
            ["", "utils/receipt_v2.py", "領収書PDF生成"],
            ["", "utils/receipt_storage.py", "Storage連携"],
            ["データ", "db.py", "Supabaseラッパー"],
            ["", "utils/receipt_db.py", "領収書DB操作"],
        ],
        col_widths=[0.18, 0.42, 0.40],
    )

    b.new_page()
    b.h2("6-2. テストファイル")
    b.table(
        ["ファイル", "内容"],
        [
            ["test_e2e/1_generate_data.py", "架空大会データ生成（80名規模）"],
            ["test_e2e/2_run_e2e_test.py", "全機能E2Eテスト（24項目）"],
            ["test_e2e/3_generate_excel.py", "CSV→Excel変換"],
            ["test_e2e/4_receipt_unit_test.py", "領収書PDF単体テスト"],
            ["test_e2e/5_capture_screenshots.py", "UIスクショ自動取得"],
            ["test_e2e/6_receipt_e2e_test.py", "領収書発行E2Eテスト（15項目）"],
        ],
        col_widths=[0.45, 0.55],
    )

    b.h2("6-3. 今後の拡張予定")
    b.bullet([
        "Phase 2: 契約書クラウド（電子署名・タイムスタンプ付与）",
        "Phase 3: LINE公式アカウント連携（一括送信自動化）",
        "Phase 4: スタッフマイページ（過去契約・領収書の一元閲覧）",
        "Phase 5: 権限ロールの分離（経理/現場/スタッフ）",
        "Phase 6: freee・マネーフォワード連携（仕訳自動生成）",
    ])

    b.h2("6-4. 運用の教訓（現場からのフィードバック）")
    b.bullet([
        "凍結退勤の自動再計算は特に好評（以前は個別に深夜手当を手計算していた）",
        "タイミー個別時給の対応で、派遣契約の多様な時給パターンにも柔軟に対応可能に",
        "500円丸めで小銭両替の負担が約40%削減",
        "領収書デジタル発行で、印紙代・印刷代・郵送代が不要に",
        "地域自動判定で交通費承認の属人化が解消",
    ])

    b.spacer(5)
    b.callout("更新履歴・お問い合わせ",
              "本マニュアルは P1 Staff Manager v3.4（2026-04-17時点）対応版です。"
              "機能追加・不具合報告は中野さん経由でヒダネAI部までお願いします。",
              color=COLOR_SECONDARY)


# ========================================================================
# main
# ========================================================================
def main() -> None:
    ensure_fonts()
    b = DocBuilder(OUT)
    cover_page(b)
    toc_page(b)
    chapter1(b)
    chapter2(b)
    chapter3(b)
    chapter4(b)
    chapter5(b)
    chapter6(b)
    b.save()
    print(f"✅ 出力: {OUT}")
    print(f"   サイズ: {OUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
