"""契約書PDF生成単体テスト（DB接続不要）"""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw

from utils.contract_pdf import (
    ContractVariables,
    build_contract_no,
    compute_content_hash,
    generate_contract_pdf,
    render_template,
    today_jst_ymd,
)


OUT = Path(__file__).resolve().parent


SAMPLE_BODY = """# 業務委託契約書

{{issuer_name}}（以下「甲」という）と、{{staff_name}}（以下「乙」という）は、以下の通り業務委託契約を締結する。

## 第1条（業務内容）

甲は乙に、下記業務を委託する。
- {{event_name}} における {{role}} 業務
- 大会運営全般の補助業務

## 第2条（業務委託料）

乙への報酬は大会終了後に精算するものとする。

## 第3条（守秘義務）

乙は業務上知り得た秘密を第三者に漏洩してはならない。契約終了後も継続する。

---

{{issue_date}}

**甲**: {{issuer_name}}
{{issuer_address}}

**乙**: {{staff_name}}
{{staff_address}}

_上記契約の証として、乙が電子署名を行う。_
"""


def make_fake_signature() -> bytes:
    """手書き風署名画像を生成"""
    img = Image.new("RGBA", (400, 150), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    # 曲線風の線
    draw.line([(20, 80), (80, 40), (140, 90), (180, 50),
                 (240, 85), (300, 45), (370, 80)],
                fill=(0, 0, 0, 255), width=4)
    draw.line([(50, 110), (70, 120), (120, 115), (200, 118)],
                fill=(0, 0, 0, 255), width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_render_template() -> None:
    vars = ContractVariables(
        staff_name="山田 太郎",
        staff_address="東京都新宿区1-2-3",
        role="Dealer",
        event_name="P1 Kyoto 2026",
    )
    rendered = render_template(SAMPLE_BODY, vars)
    assert "山田 太郎" in rendered
    assert "Dealer" in rendered
    assert "{{staff_name}}" not in rendered
    print("  ✅ テンプレートレンダリングOK")


def test_contract_no() -> None:
    n = build_contract_no(1, 123, "2026-04-17")
    assert n == "C-20260417-T1-S123"
    print(f"  ✅ 契約書No生成: {n}")


def test_unsigned_pdf() -> None:
    vars = ContractVariables(
        staff_name="佐藤 花子",
        staff_address="大阪府大阪市北区梅田1-1",
        role="Floor",
        event_name="P1 Kyoto 2026 夏大会",
        issuer_name="株式会社パシフィック",
        issuer_address="東京都港区XX 1-2-3",
    )
    rendered = render_template(SAMPLE_BODY, vars)
    pdf = generate_contract_pdf(
        rendered_body=rendered,
        contract_no=build_contract_no(1, 1, today_jst_ymd()),
        issuer_name=vars.issuer_name,
    )
    out = OUT / "test_contract_unsigned.pdf"
    out.write_bytes(pdf)
    assert len(pdf) > 3000
    print(f"  ✅ 未署名PDF生成 {out.name} ({len(pdf):,} bytes)")


def test_signed_pdf() -> None:
    vars = ContractVariables(
        staff_name="鈴木 一郎",
        staff_address="愛知県名古屋市中区XX",
        role="TD",
        event_name="P1 Kyoto 2026 夏大会",
    )
    rendered = render_template(SAMPLE_BODY, vars)
    sig = make_fake_signature()
    from datetime import datetime, timezone, timedelta
    signed_at = datetime.now(timezone(timedelta(hours=9))).isoformat()
    pdf = generate_contract_pdf(
        rendered_body=rendered,
        contract_no=build_contract_no(1, 2, today_jst_ymd()),
        issuer_name=vars.issuer_name,
        signature_image_bytes=sig,
        signed_at_iso=signed_at,
    )
    out = OUT / "test_contract_signed.pdf"
    out.write_bytes(pdf)
    assert len(pdf) > 4000
    print(f"  ✅ 署名済PDF生成 {out.name} ({len(pdf):,} bytes)")


def test_hash() -> None:
    h1 = compute_content_hash("内容A", "2026-04-17T10:00:00+09:00", "C-001")
    h2 = compute_content_hash("内容A", "2026-04-17T10:00:00+09:00", "C-001")
    h3 = compute_content_hash("内容B", "2026-04-17T10:00:00+09:00", "C-001")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # SHA-256 hex
    print(f"  ✅ ハッシュ算出 OK (length={len(h1)})")


if __name__ == "__main__":
    print("=== 契約書PDF単体テスト ===")
    test_contract_no()
    test_render_template()
    test_hash()
    test_unsigned_pdf()
    test_signed_pdf()
    print("\n✅ 全テストPASS")
