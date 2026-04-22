"""Google フォーム CSV インポーター 単体テスト（DB接続不要）

P1 Staff Manager の新機能「🔗 Googleフォーム連携」タブで使う
`utils.gform_importer` のパース・バリデーション・bulk_import_staff 連携を検証する。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Callable
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.gform_importer import (  # noqa: E402
    parse_gform_csv,
    validate_gform_row,
    validate_gform_rows,
)


# ---------------------------------------------------------------------------
# CSV fixture builders
# ---------------------------------------------------------------------------


def _csv_bytes(rows: list[list[str]]) -> bytes:
    """CSV を UTF-8 BOM 付きで生成（Google フォームの既定 CSV と同じ書式）"""
    buf = io.StringIO()
    for row in rows:
        escaped = []
        for cell in row:
            if "," in cell or '"' in cell or "\n" in cell:
                escaped.append('"' + cell.replace('"', '""') + '"')
            else:
                escaped.append(cell)
        buf.write(",".join(escaped) + "\n")
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def _sample_gform_csv() -> bytes:
    header = [
        "タイムスタンプ",
        "メールアドレス",
        "お名前（本名・漢字）",
        "お名前（カタカナ）",
        "ディーラーネーム（現場での呼び名）",
        "生年月日",
        "性別",
        "電話番号",
        "LINE ID または LINE QR リンク",
        "緊急連絡先（氏名・電話番号）",
        "郵便番号",
        "ご住所",
        "最寄駅",
        "役職",
        "雇用区分",
        "タイミーの場合の希望時給",
        "MIX対応可否",
        "稼働可能曜日",
        "開始希望日",
        "過去の大会運営経験",
        "その他（質問・希望等）",
    ]
    row1 = [
        "2026/04/20 10:30:00",
        "yamada@example.com",
        "山田 太郎",
        "ヤマダ タロウ",
        "EveKat",
        "1990-01-02",
        "男性",
        "090-1234-5678",
        "line_taro",
        "山田 次郎 / 090-0000-0000",
        "100-0001",
        "愛知県名古屋市中区栄1-1-1",
        "名古屋駅",
        "ディーラー, フロア",
        "業務委託",
        "",
        "可",
        "土, 日",
        "2026-05-01",
        "P1 Nagoya 2025 参加",
        "よろしくお願いします",
    ]
    row2 = [
        "2026/04/21 11:00:00",
        "hana@example.com",
        "佐藤 花子",
        "サトウ ハナコ",
        "",  # ディーラーネーム空 → real_name フォールバック
        "1988-08-15",
        "女性",
        "08011112222",
        "",
        "",
        "",
        "大阪府大阪市北区梅田1-1-1",
        "大阪駅",
        "TD",
        "タイミー",
        "1800",
        "不可",
        "月, 火, 水",
        "2026-05-10",
        "",
        "",
    ]
    return _csv_bytes([header, row1, row2])


# ---------------------------------------------------------------------------
# parse_gform_csv
# ---------------------------------------------------------------------------


def test_parse_basic_row_mapping() -> None:
    rows = parse_gform_csv(_sample_gform_csv())
    assert len(rows) == 2, f"行数が合わない: {len(rows)}"

    first = rows[0]
    assert first["real_name"] == "山田 太郎"
    assert first["name_jp"] == "EveKat"
    assert first["email"] == "yamada@example.com"
    assert first["contact"] == "090-1234-5678"
    assert first["nearest_station"] == "名古屋駅"
    assert first["role"] == "Dealer", f"role={first['role']}"
    assert first["employment_type"] == "contractor"
    assert first["custom_hourly_rate"] == ""  # 業務委託なので時給欄は空
    # 郵便番号が住所に結合されている
    assert first["address"].startswith("〒100-0001"), first["address"]
    assert "愛知県名古屋市中区栄1-1-1" in first["address"]
    # 複数選択役職の2つ目は notes へ
    assert "Floor" in first["notes"]
    # フリガナ・生年月日・性別など notes 統合
    assert "フリガナ: ヤマダ タロウ" in first["notes"]
    assert "生年月日: 1990-01-02" in first["notes"]
    assert "性別: 男性" in first["notes"]
    assert "MIX対応" in first["notes"]
    assert "稼働可能曜日: 土, 日" in first["notes"]
    # タイムスタンプも notes に
    assert "フォーム回答日時" in first["notes"]
    print("  ✅ 基本マッピング（山田太郎）OK")


def test_parse_fallback_name_jp_to_real_name() -> None:
    rows = parse_gform_csv(_sample_gform_csv())
    second = rows[1]
    # ディーラーネーム空 → 本名が name_jp にフォールバック
    assert second["name_jp"] == "佐藤 花子"
    assert second["real_name"] == "佐藤 花子"
    assert second["employment_type"] == "timee"
    assert second["custom_hourly_rate"] == "1800"
    assert second["role"] == "TD"
    # 郵便番号空の場合は住所だけ
    assert second["address"] == "大阪府大阪市北区梅田1-1-1"
    print("  ✅ ディーラーネーム空→本名フォールバック OK")


def test_parse_empty_input_returns_empty_list() -> None:
    assert parse_gform_csv(b"") == []
    assert parse_gform_csv(b"\ufeff") == []
    print("  ✅ 空入力は空リストを返す")


def test_parse_handles_missing_optional_columns() -> None:
    header = [
        "タイムスタンプ",
        "お名前（本名・漢字）",
        "メールアドレス",
        "電話番号",
        "ご住所",
        "役職",
        "雇用区分",
    ]
    row = [
        "2026/04/21 12:00:00",
        "鈴木 一郎",
        "ichiro@example.com",
        "08099998888",
        "東京都千代田区1-1",
        "TD",
        "正社員",
    ]
    rows = parse_gform_csv(_csv_bytes([header, row]))
    assert len(rows) == 1
    r = rows[0]
    assert r["real_name"] == "鈴木 一郎"
    assert r["name_jp"] == "鈴木 一郎"  # フォールバック
    assert r["employment_type"] == "fulltime"
    assert r["role"] == "TD"
    assert r["custom_hourly_rate"] == ""
    print("  ✅ 任意列が無い CSV でも落ちない")


def test_parse_unknown_columns_preserved_in_notes() -> None:
    header = [
        "タイムスタンプ",
        "お名前（本名・漢字）",
        "メールアドレス",
        "電話番号",
        "ご住所",
        "珍しい新しい質問",
    ]
    row = [
        "2026/04/21 12:00:00",
        "田中 次郎",
        "jiro@example.com",
        "07012345678",
        "福岡県福岡市中央区",
        "妙な回答です",
    ]
    rows = parse_gform_csv(_csv_bytes([header, row]))
    assert len(rows) == 1
    assert "妙な回答です" in rows[0]["notes"], rows[0]["notes"]
    print("  ✅ 未知列は notes に吸収される")


# ---------------------------------------------------------------------------
# validate_gform_row / validate_gform_rows
# ---------------------------------------------------------------------------


def test_validate_passes_with_full_data() -> None:
    row = {
        "real_name": "山田 太郎",
        "email": "yamada@example.com",
        "contact": "090-1234-5678",
    }
    assert validate_gform_row(row) == []
    print("  ✅ 完全データは合格")


def test_validate_fails_on_missing_real_name() -> None:
    row = {"real_name": "", "email": "x@y.com", "contact": "09012345678"}
    errors = validate_gform_row(row)
    assert any("本名" in e for e in errors), errors
    print("  ✅ 本名欠落でエラー")


def test_validate_fails_on_bad_email() -> None:
    row = {"real_name": "A", "email": "not-an-email", "contact": "09012345678"}
    errors = validate_gform_row(row)
    assert any("メール" in e for e in errors), errors
    print("  ✅ 不正メール形式でエラー")


def test_validate_fails_on_missing_contact() -> None:
    row = {"real_name": "A", "email": "a@b.com", "contact": ""}
    errors = validate_gform_row(row)
    assert any("電話番号" in e for e in errors)
    print("  ✅ 電話番号欠落でエラー")


def test_validate_fails_on_too_short_phone() -> None:
    row = {"real_name": "A", "email": "a@b.com", "contact": "12"}
    errors = validate_gform_row(row)
    assert any("電話番号" in e for e in errors)
    print("  ✅ 桁不足電話番号でエラー")


def test_validate_gform_rows_returns_only_failing_rows() -> None:
    rows = [
        {"real_name": "A", "email": "a@b.com", "contact": "09012345678"},
        {"real_name": "", "email": "ng", "contact": ""},
        {"real_name": "C", "email": "c@d.com", "contact": "08099998888"},
    ]
    results = validate_gform_rows(rows)
    assert len(results) == 1
    row_no, errors = results[0]
    assert row_no == 2
    assert len(errors) >= 3
    print("  ✅ エラー行のみ返却")


# ---------------------------------------------------------------------------
# bulk_import_staff 連携（mock でDBアクセス回避）
# ---------------------------------------------------------------------------


def test_bulk_import_integration_with_mock_db() -> None:
    """parse_gform_csv → db.bulk_import_staff への受け渡しを mock で検証。

    db 層は Supabase に依存するため、ネットワークアクセスをブロックした上で
    bulk_import_staff の入力をキャプチャして期待形式を確認する。
    """
    rows = parse_gform_csv(_sample_gform_csv())
    assert rows, "前提: パース結果が空"

    captured: dict[str, list[dict]] = {"rows": []}

    def _fake_bulk_import(input_rows):
        captured["rows"] = list(input_rows)
        return {
            "created": len(input_rows),
            "updated": 0,
            "errors": [],
        }

    with patch("db.bulk_import_staff", side_effect=_fake_bulk_import):
        import db  # import 後に patch を効かせる
        result = db.bulk_import_staff(rows)

    assert result["created"] == 2
    assert result["errors"] == []
    assert len(captured["rows"]) == 2
    # bulk_import_staff が期待するキーが揃っているか
    required_keys = {
        "name_jp", "real_name", "email", "contact", "address",
        "role", "employment_type", "nearest_station", "notes",
    }
    for r in captured["rows"]:
        missing = required_keys - set(r.keys())
        assert not missing, f"必須キー不足: {missing}"
    print("  ✅ bulk_import_staff 連携 (mock) OK")


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


def _run(test: Callable[[], None]) -> bool:
    try:
        test()
        return True
    except AssertionError as exc:
        print(f"  ❌ {test.__name__}: {exc}")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"  💥 {test.__name__}: {type(exc).__name__}: {exc}")
        return False


if __name__ == "__main__":
    print("=== Google フォーム インポーター 単体テスト ===")
    tests: list[Callable[[], None]] = [
        test_parse_basic_row_mapping,
        test_parse_fallback_name_jp_to_real_name,
        test_parse_empty_input_returns_empty_list,
        test_parse_handles_missing_optional_columns,
        test_parse_unknown_columns_preserved_in_notes,
        test_validate_passes_with_full_data,
        test_validate_fails_on_missing_real_name,
        test_validate_fails_on_bad_email,
        test_validate_fails_on_missing_contact,
        test_validate_fails_on_too_short_phone,
        test_validate_gform_rows_returns_only_failing_rows,
        test_bulk_import_integration_with_mock_db,
    ]
    passed = 0
    failed = 0
    for t in tests:
        if _run(t):
            passed += 1
        else:
            failed += 1
    print(f"\n合計 {passed}/{passed + failed} PASS, {failed} FAIL")
    if failed:
        sys.exit(1)
    print("✅ 全テストPASS")
