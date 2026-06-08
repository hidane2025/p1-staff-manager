// Supabase Edge Function: ingest-dealer-applications（案A: 各大会対応）
// 設計: パシフィック/P1/5_システム開発部/設計_ディーラー応募GSS連動_v3
//
// 2つのアクションを HMAC 認証で提供（service_role はこの関数内に隔離）:
//   { action: "sources" }                 → active な 大会↔GSS 一覧を返す（GASが巡回に使う）
//   { action: "ingest", event_id, rows }   → 応募行を p1_dealer_applications に冪等 upsert
//
// 環境変数: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / INGEST_SECRET
// デプロイ: supabase functions deploy ingest-dealer-applications --no-verify-jwt

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const INGEST_SECRET = Deno.env.get("INGEST_SECRET")!;

function hexFromBuffer(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
}
async function hmacHex(body: string, secret: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body));
  return hexFromBuffer(sig);
}
function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let out = 0;
  for (let i = 0; i < a.length; i++) out |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return out === 0;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return new Response("method not allowed", { status: 405 });
  // 設定欠落時は必ず拒否（空鍵HMACでの偽造POSTを防ぐ）。
  if (!INGEST_SECRET || !SERVICE_KEY || !SUPABASE_URL) {
    return new Response("server not configured", { status: 500 });
  }

  const raw = await req.text();
  const provided = req.headers.get("x-ingest-signature") || "";
  const expected = await hmacHex(raw, INGEST_SECRET);
  if (!timingSafeEqual(provided, expected)) {
    return new Response("invalid signature", { status: 401 });
  }

  let payload: { action?: string; event_id?: number; rows?: any[] };
  try { payload = JSON.parse(raw); } catch { return new Response("bad json", { status: 400 }); }

  const db = createClient(SUPABASE_URL, SERVICE_KEY, { auth: { persistSession: false } });

  // ---- action: sources（大会↔GSS 一覧） ----
  if (payload.action === "sources") {
    const { data, error } = await db
      .from("p1_application_sources")
      .select("id, event_id, spreadsheet_id, sheet_name")
      .eq("is_active", true);
    if (error) return new Response("sources query failed", { status: 500 });
    return new Response(JSON.stringify({ sources: data ?? [] }), {
      status: 200, headers: { "content-type": "application/json" },
    });
  }

  // ---- action: ingest（応募取込） ----
  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  if (rows.length === 0) return new Response(JSON.stringify({ upserted: 0, failed: 0 }), { status: 200 });

  const { data: runRow } = await db
    .from("p1_import_runs")
    .insert({ rows_seen: rows.length, event_id: payload.event_id ?? null, note: "edge ingest" })
    .select("id").single();
  const runId = runRow?.id ?? null;

  // 既存 hash/status をチャンク取得（lookup失敗時はバッチ全体を失敗させ status巻き戻しを防ぐ）
  const keys = rows.map((r) => r.source_row_key).filter(Boolean);
  const seen = new Map<string, { hash: string; status: string; event_id: number | null }>();
  for (let i = 0; i < keys.length; i += 100) {
    const { data: ex, error: exErr } = await db
      .from("p1_dealer_applications")
      .select("source_row_key, source_row_hash, status, event_id")
      .in("source_row_key", keys.slice(i, i + 100));
    if (exErr) {
      await db.from("p1_import_runs")
        .update({ finished_at: new Date().toISOString(), rows_failed: rows.length,
                  note: "existing-lookup failed: " + String(exErr) }).eq("id", runId);
      return new Response("existing-lookup failed", { status: 500 });
    }
    (ex || []).forEach((e: any) =>
      seen.set(e.source_row_key, { hash: e.source_row_hash, status: e.status, event_id: e.event_id ?? null }));
  }

  let upserted = 0, failed = 0, changed = 0;
  for (const r of rows) {
    try {
      const prev = seen.get(r.source_row_key);
      if (prev && prev.hash === r.source_row_hash) {
        // 内容は不変。ただし event_id が違えば付け替える（未設定の旧データ＋対応付け修正の両方）。
        // status は変えない（人手判定を壊さない）。
        const ev = r.event_id ?? payload.event_id ?? null;
        if (ev != null && prev.event_id !== ev) {
          await db.from("p1_dealer_applications")
            .update({ event_id: ev }).eq("source_row_key", r.source_row_key);
        }
        continue;
      }

      const fields: Record<string, unknown> = {
        source_row_hash: r.source_row_hash,
        event_id: r.event_id ?? payload.event_id ?? null,
        applied_at: r.applied_at,
        email: r.email, name_jp: r.name_jp, real_name: r.real_name,
        gender: r.gender, birthday: r.birthday, address: r.address,
        nearest_station: r.nearest_station, role_hint: r.role_hint,
        can_mix: !!r.can_mix, mix_games: r.mix_games,
        available_dates: r.available_dates ?? [],
        affiliation: r.affiliation, experience: r.experience,
        sns_x: r.sns_x, sns_other: r.sns_other, cash_on_day: r.cash_on_day,
        phone: r.phone, consent: r.consent, self_pr: r.self_pr, questions: r.questions,
        raw_payload: r._raw ?? r,
        import_run_id: runId,
        updated_at: new Date().toISOString(),
      };

      if (!prev) {
        const { error } = await db.from("p1_dealer_applications")
          .insert({ ...fields, source_row_key: r.source_row_key, status: "new" });
        if (error) throw error;
      } else {
        const { error: e1 } = await db.from("p1_dealer_applications")
          .update(fields).eq("source_row_key", r.source_row_key);
        if (e1) throw e1;
        // status は書込時点で new/reviewed のときだけ source_changed に（人手判定を上書きしない）
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
        import_run_id: runId, source_row_key: r?.source_row_key ?? null,
        reason: String(e), payload: r,
      });
    }
  }

  await db.from("p1_import_runs")
    .update({ finished_at: new Date().toISOString(), rows_upserted: upserted, rows_failed: failed })
    .eq("id", runId);

  return new Response(JSON.stringify({ upserted, failed, changed }), {
    status: failed > 0 ? 207 : 200, headers: { "content-type": "application/json" },
  });
});
