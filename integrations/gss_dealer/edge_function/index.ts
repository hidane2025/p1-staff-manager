// Supabase Edge Function: ingest-dealer-applications
// 設計: パシフィック/P1/5_システム開発部/設計_ディーラー応募GSS連動_v2（§1, §5.3, Codex P1-3）
//
// 役割: GAS から HMAC 署名付きで届いた応募行を検証し、p1_dealer_applications に
//       冪等 upsert する。service_role キーはこの関数内にのみ置く（GASには出さない）。
//
// 環境変数（supabase secrets set ...）:
//   SUPABASE_URL                  … プロジェクトURL
//   SUPABASE_SERVICE_ROLE_KEY     … service_role（この関数内に隔離）
//   INGEST_SECRET                 … GAS と共有する HMAC シークレット
//
// デプロイ: supabase functions deploy ingest-dealer-applications --no-verify-jwt
//   （JWTではなく独自のHMACで認証するため --no-verify-jwt）

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const INGEST_SECRET = Deno.env.get("INGEST_SECRET")!;

function hexFromBuffer(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function hmacHex(body: string, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body));
  return hexFromBuffer(sig);
}

// 定数時間比較
function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let out = 0;
  for (let i = 0; i < a.length; i++) out |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return out === 0;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return new Response("method not allowed", { status: 405 });

  // 設定欠落時は必ず拒否する。INGEST_SECRET が空のまま起動すると空鍵HMACになり、
  // --no-verify-jwt 下では誰でも偽造POSTできてしまう（Codex P1）。
  if (!INGEST_SECRET || !SERVICE_KEY || !SUPABASE_URL) {
    return new Response("server not configured", { status: 500 });
  }

  const raw = await req.text();
  const provided = req.headers.get("x-ingest-signature") || "";
  const expected = await hmacHex(raw, INGEST_SECRET);
  if (!timingSafeEqual(provided, expected)) {
    return new Response("invalid signature", { status: 401 });
  }

  let payload: { rows?: any[] };
  try {
    payload = JSON.parse(raw);
  } catch {
    return new Response("bad json", { status: 400 });
  }
  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  if (rows.length === 0) return new Response(JSON.stringify({ upserted: 0 }), { status: 200 });

  const db = createClient(SUPABASE_URL, SERVICE_KEY, { auth: { persistSession: false } });

  // 取込実行ログ開始
  const { data: runRow } = await db
    .from("p1_import_runs")
    .insert({ rows_seen: rows.length, note: "edge ingest" })
    .select("id")
    .single();
  const runId = runRow?.id ?? null;

  // 既存の hash/status を取得（変更検知・冪等のため）。
  // ⚠️ lookup をチャンク分割し、エラー時はバッチ全体を失敗させる。
  //   ここを空マップで握りつぶすと全行が「新規」と誤判定され、
  //   reviewed/accepted/rejected の人手判定を status='new' で巻き戻してしまう（Codex P2）。
  const keys = rows.map((r) => r.source_row_key).filter(Boolean);
  const seen = new Map<string, { hash: string; status: string }>();
  for (let i = 0; i < keys.length; i += 100) {
    const chunk = keys.slice(i, i + 100);
    const { data: ex, error: exErr } = await db
      .from("p1_dealer_applications")
      .select("source_row_key, source_row_hash, status")
      .in("source_row_key", chunk);
    if (exErr) {
      await db.from("p1_import_runs")
        .update({ finished_at: new Date().toISOString(), rows_failed: rows.length,
                  note: "existing-lookup failed: " + String(exErr) })
        .eq("id", runId);
      return new Response("existing-lookup failed", { status: 500 });
    }
    (ex || []).forEach((e: any) =>
      seen.set(e.source_row_key, { hash: e.source_row_hash, status: e.status })
    );
  }

  let upserted = 0, failed = 0, changed = 0;
  for (const r of rows) {
    try {
      const prev = seen.get(r.source_row_key);
      if (prev && prev.hash === r.source_row_hash) continue; // 変化なし=no-op（冪等）

      // status を含まないデータ部分（status は新規/既存で別経路に分ける）
      const fields: Record<string, unknown> = {
        source_row_hash: r.source_row_hash,
        applied_at: r.applied_at,
        email: r.email,
        name_jp: r.name_jp,
        real_name: r.real_name,
        gender: r.gender,
        birthday: r.birthday,
        address: r.address,
        nearest_station: r.nearest_station,
        role_hint: r.role_hint,
        can_mix: !!r.can_mix,
        mix_games: r.mix_games,
        available_dates: r.available_dates ?? [],
        affiliation: r.affiliation,
        experience: r.experience,
        sns_x: r.sns_x,
        sns_other: r.sns_other,
        cash_on_day: r.cash_on_day,
        phone: r.phone,
        consent: r.consent,
        self_pr: r.self_pr,
        questions: r.questions,
        raw_payload: r._raw ?? r, // 未マップ列も含む全列（GAS _raw）を保全
        import_run_id: runId,
        updated_at: new Date().toISOString(),
      };

      if (!prev) {
        // 新規挿入（status=new）。並行で既に入っていれば一意制約で失敗→dead-letter→
        // 次回は existing 扱いになり自己修復する。
        const { error } = await db.from("p1_dealer_applications")
          .insert({ ...fields, source_row_key: r.source_row_key, status: "new" });
        if (error) throw error;
      } else {
        // 既存・内容変化: まずデータを更新（status は触らない）。
        const { error: e1 } = await db.from("p1_dealer_applications")
          .update(fields).eq("source_row_key", r.source_row_key);
        if (e1) throw e1;
        // status は「書込時点で」new/reviewed のときだけ source_changed に上げる。
        // lookup〜書込の間に accepted/rejected されても人手判定を上書きしない（TOCTOU防御・Codex P2）。
        const { error: e2 } = await db.from("p1_dealer_applications")
          .update({ status: "source_changed" })
          .eq("source_row_key", r.source_row_key)
          .in("status", ["new", "reviewed"]);
        if (e2) throw e2;
        changed++;
      }
      upserted++;
    } catch (e) {
      failed++;
      await db.from("p1_import_errors").insert({
        import_run_id: runId,
        source_row_key: r?.source_row_key ?? null,
        reason: String(e),
        payload: r, // dead-letter（再処理用）
      });
    }
  }

  await db.from("p1_import_runs")
    .update({ finished_at: new Date().toISOString(), rows_upserted: upserted, rows_failed: failed })
    .eq("id", runId);

  return new Response(JSON.stringify({ upserted, failed, changed }), {
    status: failed > 0 ? 207 : 200,
    headers: { "content-type": "application/json" },
  });
});
