/**
 * P1 ディーラー応募 GSS → Supabase 連動（スタンドアロンGAS・読み取り専用）
 * 設計: パシフィック/P1/5_システム開発部/設計_ディーラー応募GSS連動_v2
 *
 * 【大原則】本番GSSには一切書き込まない・トリガーを仕掛けない・コピーしない。
 *   - このプロジェクトは本番GSSにバインドしない「スタンドアロン」GAS。
 *   - openById で読み取りのみ。実行アカウントは本番GSSの「閲覧者(Viewer)」固定。
 *   - service_role キーは持たない。Edge Function 宛の INGEST_SECRET(HMAC) のみ保持。
 *
 * 【セットアップ（Script Properties に設定）】
 *   SOURCE_SPREADSHEET_ID … 本番GSSのID
 *   SOURCE_SHEET_NAME     … 回答シート名（例: フォームの回答 1）
 *   EDGE_FN_URL           … Supabase Edge Function (ingest-dealer-applications) のURL
 *   INGEST_SECRET         … Edge Function と共有する署名シークレット（長いランダム文字列）
 *   OVERLAP_HOURS         … 差分の重複走査ウィンドウ(時間)。既定 6
 *   CURSOR_ISO            … （自動管理）最後に処理した applied_at の安全マージン後ISO
 *
 * 【トリガー】時間主導トリガー（例: 10分毎）で pollAndSync を実行。onEdit等は使わない。
 */

function pollAndSync() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) {
    Logger.log('skip: another run holds the lock');  // 多重起動防止（cursorを触らない）
    return;
  }
  try {
    var props = PropertiesService.getScriptProperties();
    var sourceId = props.getProperty('SOURCE_SPREADSHEET_ID');
    var sheetName = props.getProperty('SOURCE_SHEET_NAME');
    var edgeUrl = props.getProperty('EDGE_FN_URL');
    var secret = props.getProperty('INGEST_SECRET');
    if (!sourceId || !sheetName || !edgeUrl || !secret) {
      throw new Error('Script Properties が不足しています');
    }
    var overlapHours = parseFloat(props.getProperty('OVERLAP_HOURS') || '6');
    var cursorIso = props.getProperty('CURSOR_ISO') || '1970-01-01T00:00:00Z';
    var cursorMs = new Date(cursorIso).getTime();
    var windowStart = cursorMs - overlapHours * 3600 * 1000; // 重複走査ウィンドウ

    // ---- 読み取り専用（openById） ----
    var sheet = SpreadsheetApp.openById(sourceId).getSheetByName(sheetName);
    if (!sheet) throw new Error('シートが見つかりません: ' + sheetName);
    var values = sheet.getDataRange().getValues();
    if (values.length < 2) { Logger.log('no data rows'); return; }

    var header = values[0];
    var idx = buildHeaderIndex_(header);
    // 必須ヘッダ欠落（列名変更等）を黙って"0件"にせず、失敗させて気づけるようにする（Codex P2）。
    if (idx.timestamp < 0 || idx.email < 0) {
      throw new Error('必須ヘッダが見つかりません（タイムスタンプ/メールアドレス）。ヘッダ名変更の可能性。');
    }

    var rows = [];
    var maxAppliedMs = cursorMs;
    for (var r = 1; r < values.length; r++) {
      var row = values[r];
      var appliedAt = parseTs_(row[idx.timestamp]);
      if (!appliedAt) continue;
      var appliedMs = appliedAt.getTime();
      if (appliedMs < windowStart) continue;          // ウィンドウ外は無視
      var norm = normalizeRow_(row, idx, sourceId, sheet, appliedAt, header, r + 1);
      rows.push(norm);
      if (appliedMs > maxAppliedMs) maxAppliedMs = appliedMs;
    }

    if (rows.length === 0) { Logger.log('no new/changed rows'); return; }

    // ---- Edge Function へ HMAC 署名付きで送信（service_role は持たない） ----
    var payload = JSON.stringify({ rows: rows });
    var sig = hmacHex_(payload, secret);
    var resp = UrlFetchApp.fetch(edgeUrl, {
      method: 'post',
      contentType: 'application/json',
      headers: { 'x-ingest-signature': sig },
      payload: payload,
      muteHttpExceptions: true
    });
    var code = resp.getResponseCode();
    var failed = -1;
    try { failed = JSON.parse(resp.getContentText()).failed; } catch (e) {}
    // 全件成功(2xx かつ failed===0)のときだけ cursor を進める。
    // 207/部分失敗/解析不可なら cursor を進めず、次回に dead-letter 行ごと再送する
    // （失敗行を静かに取りこぼさない・Codex P1）。PIIはログに出さない（件数のみ）。
    if (code < 200 || code >= 300 || failed !== 0) {
      Logger.log('ingest not fully ok: HTTP ' + code + ' failed=' + failed + ' rows=' + rows.length);
      return;
    }

    // ---- 全件成功時のみ cursor を進める（安全マージン1分） ----
    var safeIso = new Date(maxAppliedMs - 60 * 1000).toISOString();
    props.setProperty('CURSOR_ISO', safeIso);
    Logger.log('ingested rows=' + rows.length + ' cursor=' + safeIso);
  } finally {
    lock.releaseLock();
  }
}

/** ヘッダ名（部分一致）から列indexを引く。列順変更に強くする（設計v2 §3 / Codex P2-7）。 */
function buildHeaderIndex_(header) {
  function find(keys) {
    for (var i = 0; i < header.length; i++) {
      var h = String(header[i]);
      for (var k = 0; k < keys.length; k++) {
        if (h.indexOf(keys[k]) !== -1) return i;
      }
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
    experience: find(['活動歴', '活動歴']),
    snsX: find(['活動用X', 'X（', 'Twitter']),
    snsOther: find(['その他SNS', 'その他']),
    cash: find(['現金支給', '現金']),
    questions: find(['質問']),
    phone: find(['電話']),
    consent: find(['確認事項', '確認']),
    days: findAll_(header, ['8/12', '8/13', '8/14', '8/15', '8/16', '勤務可能'])
  };
}

/** 勤務可能日の複数列を集める（ヘッダに日付/「勤務可能」を含む列）。 */
function findAll_(header, keys) {
  var out = [];
  for (var i = 0; i < header.length; i++) {
    var h = String(header[i]);
    for (var k = 0; k < keys.length; k++) {
      if (h.indexOf(keys[k]) !== -1) { out.push({ idx: i, label: h }); break; }
    }
  }
  return out;
}

function normalizeRow_(row, idx, sourceId, sheet, appliedAt, header, rowNumber) {
  function val(i) { return i >= 0 ? String(row[i] == null ? '' : row[i]).trim() : ''; }

  var email = val(idx.email).toLowerCase();
  var phone = val(idx.phone).replace(/[^0-9]/g, '');
  var mix = val(idx.mix);
  // MIX対応可否: 否定回答（不可/なし等）は can_mix=false にする（length>0 では誤判定・Codex P2）。
  var mixNegative = /不可|出来ない|できない|なし|無し|^no$/i.test(mix);
  var canMix = mix.length > 0 && !mixNegative;

  // 勤務可能日: 値が入っている(=可)列のラベルを配列化
  var days = [];
  (idx.days || []).forEach(function (d) {
    var v = String(row[d.idx] == null ? '' : row[d.idx]).trim();
    if (v && v !== '×' && v !== '不可' && v.toLowerCase() !== 'no') days.push(d.label);
  });

  var appliedMs = appliedAt.getTime();
  // 冪等キーは「行ごとに一意で内容編集に不変な値」で作る。
  //  - 行番号(rowNumber): append-only運用なら行ごとに安定・一意。email/phone修正でも不変。
  //  - email/phone は可変なので含めない（含めると連絡先修正で別レコード化・Codex P2）。
  //  - timestamp単独だと同一秒で衝突し後勝ちで応募が消える（Codex P2）→ 行番号で一意化。
  // ※ append-only が崩れ行が削除されると以降の行番号がずれる点は設計の運用前提で担保。
  var rowKeySeed = [sourceId, sheet.getSheetId(), rowNumber].join('|');
  var sourceRowKey = sha256Hex_(rowKeySeed);

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
  // 未マップ列も含む全列を保全（後からの再マッピング用・Codex P2）。
  // Edge Function 側で raw_payload として保存する。
  var raw = {};
  for (var i = 0; i < header.length; i++) {
    raw[String(header[i])] = String(row[i] == null ? '' : row[i]);
  }
  obj._raw = raw;

  // 行内容ハッシュ（変更検知）。_raw も含むので全列の変更を検知できる。
  obj.source_row_hash = sha256Hex_(JSON.stringify(obj));
  return obj;
}

function parseTs_(v) {
  if (v instanceof Date) return v;
  if (!v) return null;
  var d = new Date(v);
  return isNaN(d.getTime()) ? null : d;
}

function sha256Hex_(s) {
  var bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, s, Utilities.Charset.UTF_8);
  return bytesToHex_(bytes);
}
function hmacHex_(s, key) {
  var bytes = Utilities.computeHmacSha256Signature(s, key);
  return bytesToHex_(bytes);
}
function bytesToHex_(bytes) {
  var hex = '';
  for (var i = 0; i < bytes.length; i++) {
    var b = (bytes[i] + 256) % 256;
    hex += ('0' + b.toString(16)).slice(-2);
  }
  return hex;
}
