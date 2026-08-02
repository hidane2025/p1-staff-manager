"""P1 Staff Manager — スタッフ配布URL 回帰テスト（2026-08-02 追加）

背景:
    2026-07-29 にスタッフ向けページを staff_site/ へ分離した。
    実体は staff_site/pages/receipt_download.py / staff_site/pages/contract_sign.py であり、
    公開URLは **/staff/ 配下**（例: https://<host>/staff/receipt_download?token=...）になった。

    utils/url_helper.py は追随済み（receipt_download_url / contract_sign_url が /staff/ を含む）。
    しかし管理画面の各ページは f-string で直接URLを組み立てており、/staff/ が抜けている。

    抜けたURL（例: https://<host>/receipt_download?token=...）は管理側アプリを指すため、
    スタッフが開くと Basic 認証が出て到達できない＝配布物（QR・メール・封筒印刷）が機能しない。

検証内容:
    (A) pages/*.py・utils/*.py を走査し、"receipt_download?token" / "contract_sign?token" を
        含むURL組み立てがすべて直前に "/staff/" を伴っているか（違反行を1件ずつ列挙して落とす）
    (B) utils.url_helper の receipt_download_url / contract_sign_url が
        /staff/ を含み、トークンがURLエンコードされるか
    (C) 検査対象を glob で取っているか（ファイル名をハードコードしていない＝将来ページを
        追加しても自動で検査対象に入る）＋ 検出器自体が空振りしていないこと

DBには一切接続しない（ソース走査と純粋関数の検証のみ）。

実行:
    cd p1-staff-manager
    .venv/bin/python test_e2e/32_distribution_url_regression_test.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


PASS = "✅"
FAIL = "❌"
failures: list = []


def _check(name: str, cond: bool, detail: str = ""):
    mark = PASS if cond else FAIL
    print(f"  {mark} {name}")
    if not cond:
        failures.append(f"{name}: {detail}")


# ============================================================
# 共通: 検出器
# ============================================================
# スタッフ配布URLのルート名。staff_site/pages/ 配下のファイル名がそのまま
# Streamlit のページパスになるため、この2つが「/staff/ 配下にあるべきルート」。
STAFF_ROUTES = ("receipt_download", "contract_sign")

# 「ルート名 + ?token」の出現を探す。f-string でも素の文字列でも引っかかる。
_ROUTE_RE = re.compile(r"(?:" + "|".join(STAFF_ROUTES) + r")\?token")

# 正しい形は、ルート名の直前が必ず "/staff/" であること。
#   OK : f"{get_base_host()}/staff/receipt_download?token=..."
#   NG : f"{base_host}/receipt_download?token=..."
REQUIRED_PREFIX = "/staff/"


def find_unprefixed_staff_urls(source: str) -> list[tuple[int, str]]:
    """/staff/ を伴わないスタッフ配布URLの組み立て箇所を返す。

    戻り値: [(行番号(1始まり), 行の中身), ...]
    """
    bad: list[tuple[int, str]] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        for m in _ROUTE_RE.finditer(line):
            # ルート名の直前の文字列が "/staff/" で終わっていれば正しい
            if not line[: m.start()].endswith(REQUIRED_PREFIX):
                bad.append((lineno, line.strip()))
    return bad


def scan_dirs() -> list[Path]:
    """検査対象ファイルを glob で収集する（ファイル名の列挙をしない）。

    ここで固定リストを書くと、将来ページを1枚足したときに検査から漏れる。
    __pycache__ は .py を含まないが、念のため除外する。
    """
    targets: list[Path] = []
    for d in ("pages", "utils"):
        for p in sorted((ROOT / d).glob("*.py")):
            if "__pycache__" in p.parts:
                continue
            targets.append(p)
    return targets


# ============================================================
# 0. 検出器の自己テスト（検査が空振りしていないことの担保）
# ============================================================
print("\n[0] 検出器の自己テスト")

_bad_sample = 'url = f"{base_host}/receipt_download?token={token}"'
_good_sample = 'url = f"{get_base_host()}/staff/receipt_download?token={token}"'
_good_sample2 = 'url = f"{get_base_host()}/staff/contract_sign?token={token}"'

# 「/staff/ 抜き」を1件として検出できること（できなければ以降の検査は全部無意味）
_check("欠陥パターンを1件検出する",
       len(find_unprefixed_staff_urls(_bad_sample)) == 1,
       f"got {find_unprefixed_staff_urls(_bad_sample)}")
_check("正しいパターン（領収書）は検出しない",
       find_unprefixed_staff_urls(_good_sample) == [])
_check("正しいパターン（契約署名）は検出しない",
       find_unprefixed_staff_urls(_good_sample2) == [])
# 部分一致で誤検出しないこと: "/xstaff/" は "/staff/" ではない
_check("紛らわしい prefix（/xstaff/）は違反として検出する",
       len(find_unprefixed_staff_urls(
           'f"{h}/xstaff/receipt_download?token={t}"')) == 1)


# ============================================================
# 1. (C) 検査対象を glob で集めているか
# ============================================================
print("\n[1] 検査対象の収集（glob・将来ページ追加にも追随する）")

targets = scan_dirs()
pages_scanned = [p for p in targets if p.parent.name == "pages"]
utils_scanned = [p for p in targets if p.parent.name == "utils"]

# glob の実測値と一致すること＝固定リストで絞り込んでいない証拠
_pages_all = [p for p in (ROOT / "pages").glob("*.py")]
_utils_all = [p for p in (ROOT / "utils").glob("*.py")]

_check("pages/*.py を全数走査している",
       len(pages_scanned) == len(_pages_all),
       f"scanned={len(pages_scanned)} / glob={len(_pages_all)}")
_check("utils/*.py を全数走査している",
       len(utils_scanned) == len(_utils_all),
       f"scanned={len(utils_scanned)} / glob={len(_utils_all)}")
# 0件なら「走査した結果ゼロ違反」が偽の合格になるため、下限を明示する
_check("pages/ に .py が1枚以上ある（走査が空振りしていない）",
       len(pages_scanned) >= 1, f"got {len(pages_scanned)}")
_check("utils/ に .py が1枚以上ある（走査が空振りしていない）",
       len(utils_scanned) >= 1, f"got {len(utils_scanned)}")

# 配布URLを組み立てている箇所がそもそも存在すること
# （リファクタでURL組み立てが消えた場合、以下の検査は自動的に全部PASSしてしまう。
#   その"静かな合格"を防ぐため、対象コードの存在自体を確認する）
_files_with_route = [
    p for p in targets if _ROUTE_RE.search(p.read_text(encoding="utf-8"))
]
_check("配布URLを組み立てているファイルが1枚以上ある",
       len(_files_with_route) >= 1,
       f"got {[p.name for p in _files_with_route]}")

# ルート名の裏取り: /staff/<route> が実在する根拠は staff_site/pages/<route>.py。
# Streamlit は pages/ 配下のファイル名をそのままURLパスにするため、
# ここにファイルが在ることが「/staff/receipt_download が正しいURL」の唯一の根拠になる。
_staff_pages = {p.stem for p in (ROOT / "staff_site" / "pages").glob("*.py")
                if "__pycache__" not in p.parts}
for _route in STAFF_ROUTES:
    _check(f"staff_site/pages/{_route}.py が実在する（/staff/{_route} の根拠）",
           _route in _staff_pages,
           f"staff_site/pages に在るのは {sorted(_staff_pages)}")


# ============================================================
# 2. (A) /staff/ 抜けURLの検出 — ここが今回の欠陥
# ============================================================
print("\n[2] pages/ ・ utils/ に /staff/ 抜けのURL組み立てが無いこと")

violations: list[tuple[Path, int, str]] = []
for p in targets:
    src = p.read_text(encoding="utf-8")
    for lineno, line in find_unprefixed_staff_urls(src):
        violations.append((p, lineno, line))

# 違反行を1件ずつ個別のチェックとして出す（どのファイルの何行目かを失敗一覧に残すため）
for p, lineno, line in violations:
    rel = p.relative_to(ROOT)
    _check(f"{rel}:{lineno} は /staff/ を含む",
           False,
           f"{line[:110]}")

# 総括。期待値は 0 件（1件でも残っていればスタッフがURLに到達できない）
_check("違反ゼロ件",
       len(violations) == 0,
       f"{len(violations)}件の /staff/ 抜けURL: "
       + ", ".join(f"{p.relative_to(ROOT)}:{n}" for p, n, _ in violations))


# ============================================================
# 3. (B) url_helper の生成URL
# ============================================================
print("\n[3] utils.url_helper: 生成URLの形")

# APP_BASE_URL 未設定だと get_base_host() が RuntimeError になる仕様なので、
# 先に環境変数を与えてから import・呼び出しする。
_BASE = "https://p1-staff.example.test"
os.environ["APP_BASE_URL"] = _BASE

from utils.url_helper import (  # noqa: E402
    get_base_host, receipt_download_url, contract_sign_url,
)

_check("APP_BASE_URL がベースホストになる",
       get_base_host() == _BASE, f"got {get_base_host()!r}")

# 期待値の根拠:
#   ベース https://p1-staff.example.test
#   ＋ /staff/（staff_site 分離後の公開プレフィックス）
#   ＋ receipt_download（staff_site/pages/receipt_download.py のファイル名＝ルート名）
#   ＋ ?token=abc123（トークンは英数のみなのでエンコード後も不変）
_r = receipt_download_url("abc123")
_check("receipt_download_url は /staff/ を含む",
       _r == f"{_BASE}/staff/receipt_download?token=abc123", f"got {_r!r}")

_c = contract_sign_url("abc123")
_check("contract_sign_url は /staff/ を含む",
       _c == f"{_BASE}/staff/contract_sign?token=abc123", f"got {_c!r}")

# トークンのURLエンコード:
#   "a b/c+d&e" → 空白=%20 / "/"=%2F / "+"=%2B / "&"=%26
#   quote(safe='') なので "/" も必ずエスケープされる（パス境界を割らせないため）
_enc = receipt_download_url("a b/c+d&e")
_check("トークンはURLエンコードされる（空白・スラッシュ・+・&）",
       _enc == f"{_BASE}/staff/receipt_download?token=a%20b%2Fc%2Bd%26e",
       f"got {_enc!r}")

_enc2 = contract_sign_url("x/y?z=1")
_check("契約署名URLもトークンをエンコードする（?・= も含む）",
       _enc2 == f"{_BASE}/staff/contract_sign?token=x%2Fy%3Fz%3D1",
       f"got {_enc2!r}")

# 末尾スラッシュ付きのベースでもスラッシュが重複しないこと
os.environ["APP_BASE_URL"] = _BASE + "/"
_r2 = receipt_download_url("t1")
_check("ベースURL末尾の / は正規化される（// にならない）",
       _r2 == f"{_BASE}/staff/receipt_download?token=t1", f"got {_r2!r}")
os.environ["APP_BASE_URL"] = _BASE

# 未設定時は誤ったドメインのリンクを配らないよう明示的に失敗する仕様
_saved = {k: os.environ.pop(k) for k in ("APP_BASE_URL", "PUBLIC_URL")
          if k in os.environ}
try:
    get_base_host()
    _raised = False
except RuntimeError:
    _raised = True
except Exception:
    _raised = False
finally:
    os.environ.update(_saved)
_check("ベースURL未設定なら RuntimeError（誤リンク配布より失敗を選ぶ）", _raised)


# ============================================================
# 結果集計
# ============================================================
print()
print("=" * 60)
if failures:
    print(f"{FAIL} 失敗 {len(failures)}件:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
else:
    print(f"{PASS} 全テスト成功")
    sys.exit(0)
