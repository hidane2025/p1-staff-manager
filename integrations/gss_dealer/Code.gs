/**
 * P1 ディーラー応募 GSS → Supabase 連動（案A: 各大会対応・DB駆動・読み取り専用）
 * 設計: パシフィック/P1/5_システム開発部/設計_ディーラー応募GSS連動_v3
 *
 * 【案A】大会(p1_events)ごとに応募フォーム(GSS)が分かれる。
 *   - 「大会↔GSS」の一覧は Supabase 側 (p1_application_sources) が持ち、アプリ画面で登録。
 *   - このGASは Edge Function 経由でその一覧を取得し、全 active 大会を巡回して取り込む。
 *   - 新しい大会は「アプリでURL登録」するだけ＝GAS/コードは一切編集不要。
 *
 * 【大原則】本番GSSには書き込まない・バインドしない・コピーしない。openById 読取のみ。
 *   service_role は持たない。Edge Function 宛の INGEST_SECRET(HMAC) のみ保持。
 *
 * 【Script Properties】
 *   EDGE_FN_URL    … Supabase Edge Function (ingest-dealer-applications) のURL
 *   INGEST_SECRET  … Edge Function と共有する署名シークレット
 *   OVERLAP_HOURS  … 差分の重複走査ウィンドウ(時間)。既定 6
 *   CURSOR_<event_id> … （自動管理）大会ごとの最終処理位置ISO
 *
 * 【トリガー】時間主導トリガー（例: 10分毎）で pollAndSync を実行。onEdit等は使わない。
 */

function pollAndSync() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) { Logger.log('skip: locked'); return; }
  try {
    var props = PropertiesService.getScriptProperties();
    var edgeUrl = props.getProperty('EDGE_FN_URL');
    var secret = props.getProperty('INGEST_SECRET');
    if (!edgeUrl || !secret) throw new Error('EDGE_FN_URL / INGEST_SECRET が未設定');
    var overlapHours = parseFloat(props.getProperty('OVERLAP_HOURS') || '6');

    // ---- 大会↔GSS 一覧を Edge 経由で取得（service_role はGASに置かない） ----
    var sources = fetchSources_(edgeUrl, secret);
    if (!sources || sources.length === 0) { Logger.log('no active sources'); return; }

    var totalIngested = 0;
    for (var s = 0; s < sources.length; s++) {
      try {
        totalIngested += syncOneSource_(sources[s], edgeUrl, secret, props, overlapHours);
      } catch (e) {
        // 1大会で失敗しても他大会は続行（その大会のcursorは進めない）。PIIはログに出さない。
        Logger.log('source failed event_id=' + (sources[s] && sources[s].event_id) + ': ' + e);
      }
    }
    Logger.log('done. ingested total=' + totalIngested + ' sources=' + sources.length);
  } finally {
    lock.releaseLock();
  }
}

/** Edge Function から active な大会↔GSS一覧を取得（HMAC署名付き）。 */
function fetchSources_(edgeUrl, secret) {
  var body = JSON.stringify({ action: 'sources' });
  var resp = UrlFetchApp.fetch(edgeUrl, {
    method: 'post', contentType: 'application/json',
    headers: { 'x-ingest-signature': hmacHex_(body, secret) },
    payload: body, muteHttpExceptions: true
  });
  if (resp.getResponseCode() !== 200) throw new Error('sources fetch HTTP ' + resp.getResponseCode());
  var data = JSON.parse(resp.getContentText());
  return data.sources || [];
}

/** 1大会分を同期。取り込んだ件数を返す。 */
function syncOneSource_(source, edgeUrl, secret, props, overlapHours) {
  var eventId = source.event_id;
  // cursor は「ソースID＋GSS／シート識別子＋大会」をハッシュした単位。
  // event_id・spreadsheet_id・sheet_name のいずれを後から修正しても新キーになり、
  // 全行を再走査して取り込み直す（差し替え時の取りこぼし防止）。
  var cursorKey = 'CURSOR_' + sha256Hex_(
    [source.id, source.spreadsheet_id, source.sheet_name, eventId].join('|')).substring(0, 32);
  var cursorIso = props.getProperty(cursorKey) || '1970-01-01T00:00:00Z';
  var cursorMs = new Date(cursorIso).getTime();
  var windowStart = cursorMs - overlapHours * 3600 * 1000;

  var sheet = SpreadsheetApp.openById(source.spreadsheet_id)
                .getSheetByName(source.sheet_name);
  if (!sheet) throw new Error('シート無し: ' + source.sheet_name);
  var values = sheet.getDataRange().getValues();
  if (values.length < 2) return 0;

  var header = values[0];
  var idx = buildHeaderIndex_(header);
  if (idx.timestamp < 0 || idx.email < 0) {
    throw new Error('必須ヘッダ無し（タイムスタンプ/メール）event_id=' + eventId);
  }

  var rows = [];
  var maxAppliedMs = cursorMs;
  for (var r = 1; r < values.length; r++) {
    var appliedAt = parseTs_(values[r][idx.timestamp]);
    if (!appliedAt) continue;
    var appliedMs = appliedAt.getTime();
    if (appliedMs < windowStart) continue;
    rows.push(normalizeRow_(values[r], idx, source.spreadsheet_id, sheet, appliedAt, header, r + 1, eventId));
    if (appliedMs > maxAppliedMs) maxAppliedMs = appliedMs;
  }
  if (rows.length === 0) return 0;

  var body = JSON.stringify({ action: 'ingest', event_id: eventId, rows: rows });
  var resp = UrlFetchApp.fetch(edgeUrl, {
    method: 'post', contentType: 'application/json',
    headers: { 'x-ingest-signature': hmacHex_(body, secret) },
    payload: body, muteHttpExceptions: true
  });
  var code = resp.getResponseCode();
  var failed = -1;
  try { failed = JSON.parse(resp.getContentText()).failed; } catch (e) {}
  // 全件成功(2xx かつ failed===0)のときだけ cursor を進める（失敗を取りこぼさない）。
  if (code < 200 || code >= 300 || failed !== 0) {
    Logger.log('ingest not fully ok event_id=' + eventId + ' HTTP ' + code + ' failed=' + failed);
    return 0;
  }
  props.setProperty(cursorKey, new Date(maxAppliedMs - 60 * 1000).toISOString());
  return rows.length;
}

/** ヘッダ名（部分一致）から列indexを引く。大会非依存（日付決め打ちしない）。 */
function buildHeaderIndex_(header) {
  function find(keys) {
    for (var i = 0; i < header.length; i++) {
      var h = String(header[i]);
      for (var k = 0; k < keys.length; k++) if (h.indexOf(keys[k]) !== -1) return i;
    }
    return -1;
  }
  return {
    timestamp: find(['タイムスタンプ']),
    email: find(['メールアドレス']),
    roleHint: find(['業務種別']),
    mix: find(['MIX']),
    nameJp: find(['活動名義']),
    realName: find(['本名']),
    gender: find(['性別']),
    birthday: find(['生年月日']),
    address: find(['住所']),
    stations: find(['最寄り駅', '出発']),
    affiliation: find(['所属']),
    selfPr: find(['自己PR', 'PR']),
    experience: find(['活動歴']),
    snsX: find(['活動用X', 'Twitter']),
    snsOther: find(['その他SNS', 'その他']),
    cash: find(['現金支給', '現金']),
    questions: find(['質問']),
    phone: find(['電話']),
    consent: find(['確認事項', '確認']),
    days: findDayColumns_(header)
  };
}

/**
 * 勤務可能日の列を大会非依存で検出する。
 * 「勤務可能」を含む列、または日付らしいヘッダ（M/D・M月D日）を拾う。
 * → 大会ごとに会期(日付)が違っても壊れない。
 */
function findDayColumns_(header) {
  var out = [];
  for (var i = 0; i < header.length; i++) {
    var h = String(header[i]);
    var isDateLike = /勤務可能|出勤可能|\d{1,2}\s*[\/／]\s*\d{1,2}|\d{1,2}\s*月\s*\d{1,2}\s*日/.test(h);
    if (isDateLike) out.push({ idx: i, label: h });
  }
  return out;
}

function normalizeRow_(row, idx, spreadsheetId, sheet, appliedAt, header, rowNumber, eventId) {
  function val(i) { return i >= 0 ? String(row[i] == null ? '' : row[i]).trim() : ''; }

  var email = val(idx.email).toLowerCase();
  var phone = val(idx.phone).replace(/[^0-9]/g, '');
  var mix = val(idx.mix);
  var mixNegative = /不可|出来ない|できない|なし|無し|^no$/i.test(mix);
  var canMix = mix.length > 0 && !mixNegative;

  var days = [];
  (idx.days || []).forEach(function (d) {
    var v = String(row[d.idx] == null ? '' : row[d.idx]).trim();
    if (v && v !== '×' && v !== '不可' && v.toLowerCase() !== 'no') days.push(d.label);
  });

  // 冪等キーは「行ごとに一意・内容編集に不変」な値で作る（append-only前提で行番号が安定）。
  // email/phone は可変なので含めない。spreadsheet_id を含むので大会間でも衝突しない。
  var sourceRowKey = sha256Hex_([spreadsheetId, sheet.getSheetId(), rowNumber].join('|'));

  var obj = {
    source_row_key: sourceRowKey,
    applied_at: appliedAt.toISOString(),
    email: email,
    name_jp: val(idx.nameJp),
    real_name: val(idx.realName),
    gender: val(idx.gender),
    birthday: val(idx.birthday),
    address: val(idx.address),
    nearest_station: val(idx.stations),
    role_hint: val(idx.roleHint),
    can_mix: canMix,
    mix_games: mix,
    available_dates: days,
    affiliation: val(idx.affiliation),
    experience: val(idx.experience),
    sns_x: val(idx.snsX),
    sns_other: val(idx.snsOther),
    cash_on_day: val(idx.cash),
    phone: phone,
    consent: val(idx.consent),
    self_pr: val(idx.selfPr),
    questions: val(idx.questions)
  };
  // 未マップ列も含む全列を保全（後からの再マッピング用）。
  var raw = {};
  for (var i = 0; i < header.length; i++) raw[String(header[i])] = String(row[i] == null ? '' : row[i]);
  obj._raw = raw;
  // 行内容ハッシュ（変更検知）。GSS行の中身だけで作る＝event_id等の設定変更は含めない。
  // （event_id を含めると対応付け修正だけで pending 応募が source_changed に誤遷移する）
  obj.source_row_hash = sha256Hex_(JSON.stringify(obj));
  // hash 確定後に設定値(event_id)を付与する。
  obj.event_id = eventId;
  return obj;
}

function parseTs_(v) {
  if (v instanceof Date) return v;
  if (!v) return null;
  var d = new Date(v);
  return isNaN(d.getTime()) ? null : d;
}
function sha256Hex_(s) {
  return bytesToHex_(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, s, Utilities.Charset.UTF_8));
}
function hmacHex_(s, key) {
  return bytesToHex_(Utilities.computeHmacSha256Signature(s, key));
}
function bytesToHex_(bytes) {
  var hex = '';
  for (var i = 0; i < bytes.length; i++) hex += ('0' + ((bytes[i] + 256) % 256).toString(16)).slice(-2);
  return hex;
}
