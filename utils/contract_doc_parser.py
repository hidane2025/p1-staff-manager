"""P1 Staff Manager — 契約書テンプレ取込ユーティリティ

経理/法務レビュー済みの正規版テンプレ（Word / PDF / Markdown / プレーン）を
Markdown として正規化して DB に取り込むための変換層。

呼び出し側は `parse_upload(filename, file_bytes)` を使えば
拡張子を見て適切なパーサを自動選択する。失敗時は例外を送出するので、
UI 側で expander に技術詳細を表示しつつ「手動で貼り付けてください」
フォールバックに誘導できる。

immutable / 純粋関数方針:
    いずれのパーサも入力 bytes を変更せず、戻り値の str を生成して返す。
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable


SUPPORTED_EXTENSIONS: tuple[str, ...] = ("docx", "pdf", "md", "markdown", "txt")


class DocParseError(Exception):
    """テンプレ取込の失敗を表す基底例外"""


class UnsupportedFormatError(DocParseError):
    """サポート外のフォーマット"""


class MissingDependencyError(DocParseError):
    """必須ライブラリが存在しない & 自動導入にも失敗"""


# ==========================================================================
# 依存ライブラリの遅延 import（失敗時は pip3 install を試行）
# ==========================================================================
def _pip_install(package: str) -> bool:
    """python3 -m pip install --user <package> を走らせ、成功したら True"""
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--user", package],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _import_docx():
    try:
        import docx  # type: ignore
        return docx
    except ImportError:
        if _pip_install("python-docx"):
            try:
                import docx  # type: ignore
                return docx
            except ImportError:
                pass
        raise MissingDependencyError(
            "python-docx が利用できません。`pip3 install python-docx` を手動で実行してください。"
        )


def _import_pypdf2():
    try:
        import PyPDF2  # type: ignore
        return PyPDF2
    except ImportError:
        if _pip_install("PyPDF2"):
            try:
                import PyPDF2  # type: ignore
                return PyPDF2
            except ImportError:
                pass
        raise MissingDependencyError(
            "PyPDF2 が利用できません。`pip3 install PyPDF2` を手動で実行してください。"
        )


# ==========================================================================
# 正規化ユーティリティ（immutable: 戻り値で新しい str を返す）
# ==========================================================================
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_TRAILING_WS_RE = re.compile(r"[ \t]+\n")


def _normalize_markdown(text: str) -> str:
    """取り込んだテキストを Markdown として整える。

    - Windows 改行 → LF
    - 全角空白のみの行はトリム
    - 行末空白削除
    - 連続空行は 2 行までに圧縮
    - 前後空行トリム
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln if ln.strip(" \u3000") else "" for ln in text.split("\n")]
    text = "\n".join(lines)
    text = _TRAILING_WS_RE.sub("\n", text)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip() + "\n"


# ==========================================================================
# パーサ本体
# ==========================================================================
def parse_docx(file_bytes: bytes) -> str:
    """Word (.docx) → Markdown。

    - 各段落の `style.name` を見て Heading1/2/3 に `#` を付与
    - リスト系スタイルは `- ` プレフィックス
    - テーブルは `|` 区切りで簡易 Markdown 表に変換
    - 太字/斜体は **text** / _text_ で復元（run 単位）
    """
    docx = _import_docx()
    try:
        document = docx.Document(io.BytesIO(file_bytes))
    except Exception as e:  # noqa: BLE001
        raise DocParseError(f"Word ファイルを開けませんでした: {e}") from e

    lines: list[str] = []
    for block in _iter_block_items(document):
        if block["kind"] == "paragraph":
            rendered = _render_paragraph(block["paragraph"])
            if rendered is not None:
                lines.append(rendered)
        elif block["kind"] == "table":
            table_md = _render_table(block["table"])
            if table_md:
                lines.append(table_md)

    text = "\n\n".join(lines)
    return _normalize_markdown(text)


def parse_pdf(file_bytes: bytes) -> str:
    """PDF → Markdown（ベストエフォート）

    PyPDF2 の extract_text がフォント/埋込み方式によって空文字を返すケースがあるため、
    抽出結果がほぼ空なら DocParseError を投げる。呼び出し側は
    「手動で本文を貼り付けてください」テキストエリアにフォールバックする。
    """
    pypdf2 = _import_pypdf2()
    try:
        reader = pypdf2.PdfReader(io.BytesIO(file_bytes))
    except Exception as e:  # noqa: BLE001
        raise DocParseError(f"PDF を開けませんでした: {e}") from e

    pages_text: list[str] = []
    for idx, page in enumerate(reader.pages):
        try:
            pages_text.append(page.extract_text() or "")
        except Exception as e:  # noqa: BLE001
            raise DocParseError(
                f"{idx + 1} ページ目の抽出に失敗しました: {e}"
            ) from e

    body = "\n\n".join(p.strip() for p in pages_text if p.strip())
    if len(body.strip()) < 20:
        raise DocParseError(
            "PDF からテキストをほぼ抽出できませんでした（画像PDF/暗号化の可能性）。"
            "手動で本文を貼り付けてください。"
        )
    return _normalize_markdown(body)


def parse_plain(file_bytes: bytes) -> str:
    """.md / .txt をそのまま UTF-8 デコード → 正規化"""
    for encoding in ("utf-8", "utf-8-sig", "cp932", "shift_jis", "latin-1"):
        try:
            text = file_bytes.decode(encoding)
            return _normalize_markdown(text)
        except UnicodeDecodeError:
            continue
    raise DocParseError("テキストファイルの文字コードを判定できませんでした。")


# ==========================================================================
# ディスパッチャ
# ==========================================================================
@dataclass(frozen=True)
class ParseResult:
    markdown: str
    parser: str
    original_filename: str


def parse_upload(filename: str, file_bytes: bytes) -> ParseResult:
    """アップロードされたファイルを拡張子で分類してパースする"""
    ext = _extract_extension(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"対応していない拡張子です: {ext}（対応: {', '.join(SUPPORTED_EXTENSIONS)}）"
        )

    parser_map: dict[str, Callable[[bytes], str]] = {
        "docx": parse_docx,
        "pdf": parse_pdf,
        "md": parse_plain,
        "markdown": parse_plain,
        "txt": parse_plain,
    }
    parser_fn = parser_map[ext]
    markdown = parser_fn(file_bytes)
    return ParseResult(markdown=markdown, parser=ext, original_filename=filename)


def _extract_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower().strip()


# ==========================================================================
# docx 内部処理
# ==========================================================================
def _iter_block_items(document) -> list[dict]:
    """python-docx の Document から paragraph / table を順番に取り出す。

    Document.element.body の子要素順を尊重することで、
    見出し → 表 → 本文のような構造を正しく再現できる。
    """
    from docx.oxml.ns import qn  # type: ignore
    from docx.table import Table  # type: ignore
    from docx.text.paragraph import Paragraph  # type: ignore

    body = document.element.body
    items: list[dict] = []
    for child in body.iterchildren():
        tag = child.tag
        if tag == qn("w:p"):
            items.append({"kind": "paragraph",
                          "paragraph": Paragraph(child, document)})
        elif tag == qn("w:tbl"):
            items.append({"kind": "table",
                          "table": Table(child, document)})
    return items


def _render_paragraph(paragraph) -> str | None:
    """Paragraph → Markdown 1 行。空段落は None"""
    text = _render_runs(paragraph)
    style_name = (paragraph.style.name or "").strip() if paragraph.style else ""

    if not text.strip():
        return None

    # 見出し判定
    heading_level = _heading_level(style_name)
    if heading_level:
        return f"{'#' * heading_level} {text.strip()}"

    # 箇条書き判定
    if _is_list_paragraph(paragraph, style_name):
        return f"- {text.strip()}"

    return text


def _heading_level(style_name: str) -> int:
    """Heading 1 → 1, Heading 2 → 2 ...。それ以外は 0"""
    m = re.match(r"Heading\s*(\d+)", style_name, re.IGNORECASE)
    if m:
        return max(1, min(6, int(m.group(1))))
    if style_name.lower() == "title":
        return 1
    return 0


def _is_list_paragraph(paragraph, style_name: str) -> bool:
    """番号付き/箇条書きリスト段落かどうか"""
    if "list" in style_name.lower() or "bullet" in style_name.lower():
        return True
    # numId を見る（番号付きリスト）
    try:
        from docx.oxml.ns import qn  # type: ignore
        num_pr = paragraph._p.find(qn("w:pPr") + "/" + qn("w:numPr"))
        if num_pr is not None:
            return True
    except Exception:
        pass
    return False


def _render_runs(paragraph) -> str:
    """runs を巡回して bold / italic を Markdown で復元"""
    pieces: list[str] = []
    for run in paragraph.runs:
        raw = run.text or ""
        if not raw:
            continue
        t = raw
        if run.bold:
            t = f"**{t}**"
        if run.italic:
            t = f"_{t}_"
        pieces.append(t)
    return "".join(pieces)


def _render_table(table) -> str:
    """シンプルな Markdown table 化。セル内改行はスペースに置換"""
    rows: list[list[str]] = []
    for row in table.rows:
        rows.append([_cell_text(cell) for cell in row.cells])
    if not rows:
        return ""

    max_cols = max(len(r) for r in rows)
    norm_rows = [r + [""] * (max_cols - len(r)) for r in rows]

    header = norm_rows[0]
    body = norm_rows[1:] if len(norm_rows) > 1 else []

    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    for r in body:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _cell_text(cell) -> str:
    parts = []
    for p in cell.paragraphs:
        txt = _render_runs(p).strip()
        if txt:
            parts.append(txt)
    return " ".join(parts).replace("|", "\\|")
