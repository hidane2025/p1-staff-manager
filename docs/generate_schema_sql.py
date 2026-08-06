"""本番DBのOpenAPI内省から p1_* のDDLを生成する（2026-08-06）

Management APIトークンが失効（403）しているため、PostgRESTの内省で
表・列・型・既定値・NOT NULL・主キー・外部キーを取得する。
索引とRLSはマイグレーションファイルから収集し、出典を明記する。
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import urllib.request

ROOT = pathlib.Path.home() / "Documents/GitHub/p1-staff-manager"
KEY = (pathlib.Path.home() / ".config/hidane-ops/p1_service_role").read_text().strip()
URL = "https://fmqalkwkxckbxxijiprp.supabase.co"

TABLE_DESC = {
    "p1_events": "大会（イベント）マスター。すべての金額計算の起点",
    "p1_staff": "スタッフ台帳。氏名・住所・地域・雇用区分",
    "p1_shifts": "シフトと出退勤実績（予定/実績/欠勤・食事配布状況）",
    "p1_event_rates": "日別の単価（時給・深夜・手当）",
    "p1_event_transport_rules": "地域別の交通費ルール（11地域）",
    "p1_transport_claims": "交通費の領収書と精算額",
    "p1_staff_event_allowances": "個別手当（スタッフ×大会ごとの臨時支給）",
    "p1_payments": "支払い（確定額・承認状態・領収書トークン）",
    "p1_contract_templates": "契約書テンプレート（本文Markdown）",
    "p1_contracts": "発行済み契約書と電子署名の記録",
    "p1_petty_cash": "小口現金の出納",
    "p1_app_users": "ログインアカウント（個人アカウント方式）",
    "p1_admin_totp": "管理者の2要素認証設定",
    "p1_day_codes": "当日運用コード（現場端末の入場コード）",
    "p1_audit_log": "監査ログ（誰が・いつ・何をしたか）",
}

SENSITIVITY = {
    "p1_staff": "T2（本名・住所・メール・電話＝個人情報）",
    "p1_payments": "T2（報酬額＝給与情報。領収書トークンを含む）",
    "p1_contracts": "T2（署名画像・IP・UA＝個人情報）",
    "p1_app_users": "T3（パスワードハッシュ＝認証情報）",
    "p1_admin_totp": "T3（TOTPシークレット＝認証情報）",
    "p1_day_codes": "T3（当日運用コード＝認証情報）",
    "p1_transport_claims": "T1（金額）",
    "p1_staff_event_allowances": "T1（金額）",
    "p1_petty_cash": "T1（金額）",
    "p1_audit_log": "T1（操作者名を含む）",
}

FORMAT_TO_PG = {
    "integer": "integer",
    "bigint": "bigint",
    "text": "text",
    "character varying": "text",
    "timestamp with time zone": "timestamptz",
    "timestamp without time zone": "timestamp",
    "date": "date",
    "boolean": "boolean",
    "numeric": "numeric",
    "jsonb": "jsonb",
    "json": "json",
    "uuid": "uuid",
    "double precision": "double precision",
    "smallint": "smallint",
    "real": "real",
}


def fetch_spec() -> dict:
    req = urllib.request.Request(
        f"{URL}/rest/v1/", headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
    return json.loads(urllib.request.urlopen(req).read())


def row_counts(tables) -> dict:
    out = {}
    for t in tables:
        req = urllib.request.Request(
            f"{URL}/rest/v1/{t}?select=id&limit=1",
            headers={"apikey": KEY, "Authorization": f"Bearer {KEY}",
                     "Prefer": "count=exact", "Range": "0-0"})
        try:
            r = urllib.request.urlopen(req)
            cr = r.headers.get("content-range", "")
            out[t] = cr.split("/")[-1] if "/" in cr else "?"
        except Exception:
            out[t] = "?"
    return out


def collect_migrations() -> tuple[dict, dict, list]:
    """マイグレーション群から索引・RLSポリシー・その他制約を集める"""
    idx, rls, extra = {}, {}, []
    mig_dir = ROOT / "docs/db_migrations"
    for f in sorted(mig_dir.glob("*.sql")):
        src = f.read_text()
        for m in re.finditer(
                r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?:IF NOT EXISTS\s+)?(\w+)\s+ON\s+(?:public\.)?(\w+)\s*\(([^)]+)\)",
                src, re.I):
            uniq, name, tbl, cols = m.groups()
            idx.setdefault(tbl, []).append(
                (name, cols.strip(), bool(uniq), f.name))
        for m in re.finditer(
                r'CREATE\s+POLICY\s+"([^"]+)"\s+ON\s+(?:public\.)?(\w+)\s+FOR\s+(\w+)\s+TO\s+([\w,\s]+?)\s+((?:USING|WITH)[^;]*);',
                src, re.I):
            name, tbl, cmd, roles, body = m.groups()
            body = " ".join(body.split())
            # 同名ポリシーは後の版が DROP→CREATE で置き換えるため、最後の定義が現行
            rls.setdefault(tbl, {})[name] = (cmd.upper(), roles.strip(), body, f.name)
        for m in re.finditer(
                r"ALTER TABLE\s+(?:public\.)?(\w+)\s*\n?\s*ADD CONSTRAINT\s+(\w+)\s+([^;]+);", src, re.I | re.S):
            extra.append((m.group(1), m.group(2), " ".join(m.group(3).split()), f.name))
    return idx, rls, extra


def main():
    spec = fetch_spec()
    defs = {k: v for k, v in spec.get("definitions", {}).items() if k.startswith("p1_")}
    counts = row_counts(defs)
    idx, rls, extra = collect_migrations()
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    ncol = sum(len(v.get("properties", {})) for v in defs.values())
    nfk = sum(1 for v in defs.values() for p in v.get("properties", {}).values()
              if "Foreign Key" in (p.get("description") or ""))

    out = []
    A = out.append
    A("-- " + "=" * 70)
    A("-- P1 Staff Manager — データベース スキーマ定義（DDL）")
    A("-- " + "=" * 70)
    A("-- 生成日時   : 2026-08-06 (JST)")
    A(f"-- 対象コード : {ROOT.name} @ {head}")
    A("-- データベース : PostgreSQL（Supabase・他事業と同居のため p1_ 接頭辞のみ収録）")
    A("--")
    A("-- 生成方法   : 本番データベースの PostgREST スキーマ内省から自動生成")
    A("--              （列・型・既定値・NOT NULL・主キー・外部キーは live の実測値）")
    A("--              索引とRLSポリシーは docs/db_migrations/*.sql の適用済み定義を収録")
    A("--              ※前版(2026-07-31)は列3件とテーブル1件が欠落していたため再生成")
    A("--")
    A(f"-- 収録       : テーブル {len(defs)} / 列 {ncol} / 外部キー {nfk}")
    A("-- " + "=" * 70)
    A("")
    A("SET search_path = public;")
    A("")

    for t in sorted(defs, key=lambda x: (x not in TABLE_DESC, x)):
        d = defs[t]
        props = d.get("properties", {})
        required = set(d.get("required", []))
        A("-- " + "-" * 69)
        A(f"-- {t}  … {TABLE_DESC.get(t, '')}")
        A(f"--   行数(概算): {counts.get(t, '?')}"
          + (f" ／ 機微度: {SENSITIVITY[t]}" if t in SENSITIVITY else ""))
        A("-- " + "-" * 69)
        A(f"CREATE TABLE {t} (")
        lines, pk, fks = [], [], []
        for c, p in props.items():
            desc = p.get("description") or ""
            typ = FORMAT_TO_PG.get(p.get("format"), p.get("format") or "text")
            seg = f"    {c} {typ}"
            if "Primary Key" in desc and typ in ("integer", "bigint"):
                # 連番の既定値は内省に出ないため、PGの慣行どおり補って明示する
                seg += f" DEFAULT nextval('{t}_id_seq'::regclass)"
            elif "default" in p:
                dv = p["default"]
                if isinstance(dv, str):
                    if re.match(r"^[a-z_]+\(", dv) or "::" in dv:
                        seg += f" DEFAULT {dv}"
                    else:
                        seg += f" DEFAULT '{dv}'::text"
                elif isinstance(dv, bool):
                    seg += f" DEFAULT {str(dv).lower()}"
                else:
                    seg += f" DEFAULT {dv}"
            if c in required:
                seg += " NOT NULL"
            if "Primary Key" in desc:
                pk.append(c)
            m = re.search(r"<fk table='(\w+)' column='(\w+)'/>", desc)
            if m:
                fks.append((c, m.group(1), m.group(2)))
            lines.append(seg)
        if pk:
            lines.append(f"    CONSTRAINT {t}_pkey PRIMARY KEY ({', '.join(pk)})")
        for c, ft, fc in fks:
            act = ""
            for et, en, ebody, _f in extra:
                if et == t and c in ebody and "FOREIGN KEY" in ebody.upper():
                    mm = re.search(r"ON DELETE (\w+)", ebody, re.I)
                    if mm:
                        act = f" ON DELETE {mm.group(1).upper()}"
            lines.append(
                f"    CONSTRAINT {t}_{c}_fkey FOREIGN KEY ({c}) REFERENCES {ft}({fc}){act}")
        A(",\n".join(lines))
        A(");")
        for name, cols, uniq, src in idx.get(t, []):
            A(f"CREATE {'UNIQUE ' if uniq else ''}INDEX {name} ON {t} ({cols});"
              f"   -- {src}")
        for et, en, ebody, src in extra:
            if et == t and "FOREIGN KEY" not in ebody.upper():
                A(f"ALTER TABLE {t} ADD CONSTRAINT {en} {ebody};   -- {src}")
        pol = rls.get(t, {})
        if pol:
            A(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;")
            for name, (cmd, roles, body, src) in pol.items():
                A(f'CREATE POLICY "{name}" ON {t} FOR {cmd} TO {roles} {body};   -- {src}')
        A("")

    A("-- " + "=" * 70)
    A("-- 補足")
    A("-- " + "=" * 70)
    A("-- ・全 p1_ テーブルは anon / authenticated ロールの権限を剥奪済み")
    A("--   （docs/db_migrations/20260731_lock_down_p1_tables.sql）。")
    A("--   アプリは service_role キーでのみ接続する。")
    A("-- ・時刻列は文字列型（text）で 'HH:MM' 形式。深夜跨ぎは 24 時超え表記")
    A("--   （例 '27:00' = 翌3時）を用いるため、time型ではなく text で保持している。")
    A("-- ・日付列も text（'YYYY-MM-DD'）。既存データとの互換のため型変更していない。")

    dest = ROOT / "docs/schema.sql"
    dest.write_text("\n".join(out) + "\n")
    print(f"生成: {dest}  ({len(out)}行 / テーブル{len(defs)} / 列{ncol})")


if __name__ == "__main__":
    main()
