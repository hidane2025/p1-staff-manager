#!/usr/bin/env bash
# P1 Staff Manager 起動スクリプト
#   nginx(Basic認証) ─┬─ /staff/ → スタッフ用Streamlit（認証免除・管理機能なし）
#                     └─ /      → 管理用Streamlit（認証必須。WebSocketも内側）
set -euo pipefail

: "${PORT:=8080}"          # ホスティングが割り当てる公開ポート
: "${ADMIN_PORT:=8501}"    # 管理アプリ（内部のみ）
: "${STAFF_PORT:=8502}"    # スタッフ用アプリ（内部のみ）
: "${MAX_UPLOAD_MB:=16}"   # nginx の client_max_body_size と揃えること

# ------------------------------------------------------------
# 必須設定の検査（1つでも欠けたら起動しない = fail closed）
#   ここを緩めると「認証なしで公開」「DBキー未設定で既定キーへ暗黙フォールバック」
#   といった事故が“成功したデプロイ”として通ってしまう。
# ------------------------------------------------------------
_missing=()
for _v in BASIC_AUTH_USER BASIC_AUTH_PASSWORD SUPABASE_URL SUPABASE_SERVICE_KEY; do
  [[ -z "${!_v:-}" ]] && _missing+=("$_v")
done
# アプリのログインは「個人アカウント(AUTH_USERS)」か「共有パスワード(ADMIN_PASSWORD)」の
# どちらかが必須。個人アカウントの方が監査ログに実名が残るため推奨。
if [[ -z "${AUTH_USERS:-}" && -z "${ADMIN_PASSWORD:-}" ]]; then
  _missing+=("AUTH_USERS または ADMIN_PASSWORD")
fi
if (( ${#_missing[@]} > 0 )); then
  echo "FATAL: 必須の環境変数が未設定です: ${_missing[*]}" >&2
  echo "       未設定のまま起動すると認証なしでの公開や誤ったDB接続が起きるため中止します。" >&2
  exit 1
fi

# Basic認証ファイルを生成。パスワードは標準入力で渡し、コマンドライン
# （/proc/<pid>/cmdline から読める）には載せない。
htpasswd -inB "$BASIC_AUTH_USER" <<<"$BASIC_AUTH_PASSWORD" > /etc/nginx/.htpasswd
# nginxのワーカーはroot以外（Debianでは www-data）で動くため、600（root専用）だと
# 認証ファイルを読めず全リクエストが500になる。ワーカーのユーザー名を設定から読み取り、
# そのグループにだけ読み取りを許す（他ユーザーには非公開のまま）。
_nginx_user="$(awk '$1=="user"{print $2}' /etc/nginx/nginx.conf | tr -d ';' | head -1)"
: "${_nginx_user:=www-data}"
chown "root:${_nginx_user}" /etc/nginx/.htpasswd 2>/dev/null || true
chmod 640 /etc/nginx/.htpasswd

cp /app/deploy/proxy_params.conf /etc/nginx/p1_proxy_params.conf
export PORT ADMIN_PORT STAFF_PORT
envsubst '${PORT} ${ADMIN_PORT} ${STAFF_PORT}' \
  < /app/deploy/nginx.conf.template > /etc/nginx/conf.d/default.conf

_start_streamlit() {  # $1=script $2=port $3=baseUrlPath(空可) $4=showErrorDetails
  local extra=()
  [[ -n "${3:-}" ]] && extra+=(--server.baseUrlPath="$3")
  extra+=(--client.showErrorDetails="${4:-full}")
  # 2026-07-29: Streamlitは非特権ユーザーで実行する（rootで動かさない）。
  # Basic認証の資格情報はnginxが使うものでアプリには不要なので、環境から除いて渡す。
  # HOME を p1app 用に差し替える。setpriv はユーザーを変えても HOME を変えないため、
  # 未指定だと Streamlit が /root/.streamlit/secrets.toml を読もうとして
  # Permission denied で起動できない（2026-07-29 本番で発生）。
  setpriv --reuid=p1app --regid=p1app --init-groups --inh-caps=-all \
    env -u BASIC_AUTH_USER -u BASIC_AUTH_PASSWORD HOME=/home/p1app \
    streamlit run "$1" \
    --server.port="$2" \
    --server.address=127.0.0.1 \
    --server.headless=true \
    --server.maxUploadSize="$MAX_UPLOAD_MB" \
    --browser.gatherUsageStats=false \
    "${extra[@]}" &
}

# 管理側は社内利用なので、障害調査のためエラー詳細を出す
_start_streamlit app.py "$ADMIN_PORT" "" "full"
ADMIN_PID=$!
# スタッフ側は社外の125名が開く。トレースバックにファイルパスや内部構造が
# 出るのは情報漏洩なので、エラー詳細を出さない（2026-07-29 実機で確認して修正）
_start_streamlit staff_site/app.py "$STAFF_PORT" "staff" "none"
STAFF_PID=$!

# 両アプリの起動待ち（最大90秒）
_wait_up() {  # $1=url $2=名前
  local i
  for i in $(seq 1 90); do
    curl -sf -o /dev/null "$1" && return 0
    sleep 1
  done
  echo "FATAL: $2 が起動しませんでした（$1 に応答なし）" >&2
  return 1
}
_wait_up "http://127.0.0.1:${ADMIN_PORT}/_stcore/health" "管理アプリ"
_wait_up "http://127.0.0.1:${STAFF_PORT}/staff/_stcore/health" "スタッフ用アプリ"

nginx -g 'daemon off;' &
NGINX_PID=$!

# SIGTERM を受けたら子プロセスへ伝播させる（PID 1 の bash は既定では無視するため、
# ハンドラを張らないと再デプロイのたびに強制終了になる）
trap 'kill -TERM "$ADMIN_PID" "$STAFF_PID" "$NGINX_PID" 2>/dev/null || true' TERM INT

# ------------------------------------------------------------
# 起動セルフテスト
#   「黙って穴が空いた状態で公開する」ことを防ぐ最終防衛線。
#   curl の失敗で set -e に殺されないよう、各行に || true を付ける。
# ------------------------------------------------------------
_probe() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$@" || true; }

for _ in $(seq 1 30); do
  [[ "$(_probe "http://127.0.0.1:${PORT}/staff/_stcore/health")" == "200" ]] && break
  sleep 1
done

_fail=0
_expect() {  # $1=説明 $2=実測 $3=期待
  if [[ "$2" == "$3" ]]; then
    echo "  OK   $1 （$2）"
  else
    echo "  NG   $1 — 実測 $2 / 期待 $3" >&2
    _fail=1
  fi
}

echo "起動セルフテスト:"
# ①管理画面は認証なしで開けない
_expect "管理トップ 認証なし"        "$(_probe "http://127.0.0.1:${PORT}/")" "401"
# ②管理アプリのWebSocketも認証の内側（ここが素通りだと画面全体が漏れる）
_expect "管理WebSocket 認証なし"     "$(_probe -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
                                        -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
                                        "http://127.0.0.1:${PORT}/_stcore/stream")" "401"
# ③管理ページ個別も認証の内側
_expect "管理ページ 認証なし"        "$(_probe "http://127.0.0.1:${PORT}/3_payment")" "401"
# ④正しい資格情報なら通る（bcrypt非対応環境なら401のままになり検出できる）
_expect "管理トップ 認証あり"        "$(_probe -u "${BASIC_AUTH_USER}:${BASIC_AUTH_PASSWORD}" "http://127.0.0.1:${PORT}/")" "200"
# ⑤スタッフ用は認証なしで開ける（本体・静的資産・WebSocketの土台）
_expect "スタッフ領収書 認証なし"    "$(_probe "http://127.0.0.1:${PORT}/staff/receipt_download?token=selftest")" "200"
_expect "スタッフ静的資産 認証なし"  "$(_probe "http://127.0.0.1:${PORT}/staff/static/index.html")" "200"
_expect "スタッフ死活 認証なし"      "$(_probe "http://127.0.0.1:${PORT}/staff/_stcore/health")" "200"

# ⑥データベースに実際に到達できるか（ヘルスチェックは画面の応答しか見ないため、
#   DBが落ちていても「正常」と判定されてしまう。ここで実接続を確認する）
if setpriv --reuid=p1app --regid=p1app --init-groups --inh-caps=-all \
     env HOME=/home/p1app python -c "
import sys
sys.path.insert(0, '/app')
import db
ok = db.connection_health().get('ok')
sys.exit(0 if ok else 1)
" >/dev/null 2>&1; then
  echo "  OK   データベース接続"
else
  echo "  NG   データベース接続 — 接続できません（URLキーの設定を確認）" >&2
  _fail=1
fi

unset BASIC_AUTH_PASSWORD  # このシェルの環境からは消す（既に起動した子には残る点は承知の上）

if (( _fail )); then
  echo "FATAL: 起動セルフテストに失敗しました。想定外の公開・全員締め出しを避けるため停止します。" >&2
  kill -TERM "$ADMIN_PID" "$STAFF_PID" "$NGINX_PID" 2>/dev/null || true
  exit 1
fi
echo "起動セルフテスト: 全項目パス"

# いずれかが落ちたらコンテナごと終了（ホスティング側が再起動する）
wait -n "$ADMIN_PID" "$STAFF_PID" "$NGINX_PID"
exit $?
