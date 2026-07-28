#!/usr/bin/env bash
# P1 Staff Manager 起動スクリプト（Basic認証プロキシ + Streamlit）
set -euo pipefail

: "${PORT:=8080}"            # ホスティングが割り当てる公開ポート
: "${STREAMLIT_PORT:=8501}"  # 内部ポート（外部公開しない）

if [[ -z "${BASIC_AUTH_USER:-}" || -z "${BASIC_AUTH_PASSWORD:-}" ]]; then
  echo "FATAL: BASIC_AUTH_USER / BASIC_AUTH_PASSWORD が未設定です。" >&2
  echo "       認証なしで公開してしまうため起動を中止します。" >&2
  exit 1
fi

# Basic認証ファイルを起動時に生成（パスワードはイメージにも配布物にも残さない）
#   -B = bcrypt。Debian(libxcrypt)は解釈できるが、環境によっては非対応で
#   「全員が入れない」状態になりうるため、下の起動時セルフテストで実際に検証する。
htpasswd -bcB /etc/nginx/.htpasswd "$BASIC_AUTH_USER" "$BASIC_AUTH_PASSWORD" >/dev/null 2>&1

cp /app/deploy/proxy_params.conf /etc/nginx/p1_proxy_params.conf
export PORT STREAMLIT_PORT
envsubst '${PORT} ${STREAMLIT_PORT}' \
  < /app/deploy/nginx.conf.template > /etc/nginx/conf.d/default.conf

# Streamlit を内部ポートで起動（外向きはnginxのみ）
streamlit run app.py \
  --server.port="$STREAMLIT_PORT" \
  --server.address=127.0.0.1 \
  --server.headless=true \
  --server.enableCORS=false \
  --server.enableXsrfProtection=true \
  --browser.gatherUsageStats=false &
STREAMLIT_PID=$!

# Streamlitの起動待ち（最大60秒）
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${STREAMLIT_PORT}/_stcore/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# どちらかが落ちたらコンテナごと終了させる（ホスティング側が自動再起動する）
nginx -g 'daemon off;' &
NGINX_PID=$!

# ------------------------------------------------------------
# 起動時セルフテスト（黙って壊れた状態で公開しないための最終防衛線）
#   ①認証なしで管理画面に入れてしまわないか（＝公開事故）
#   ②正しい資格情報で本当に入れるか（＝全員締め出し事故。bcrypt非対応環境の検出）
# ------------------------------------------------------------
for _ in $(seq 1 20); do
  curl -sf -o /dev/null "http://127.0.0.1:${PORT}/_stcore/health" && break
  sleep 1
done

_code_noauth=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/")
_code_auth=$(curl -s -o /dev/null -w '%{http_code}' \
             -u "${BASIC_AUTH_USER}:${BASIC_AUTH_PASSWORD}" "http://127.0.0.1:${PORT}/")
unset BASIC_AUTH_PASSWORD

if [[ "$_code_noauth" != "401" ]]; then
  echo "FATAL: 認証なしで管理画面に到達できます (HTTP ${_code_noauth})。公開事故を防ぐため停止します。" >&2
  exit 1
fi
if [[ "$_code_auth" == "401" ]]; then
  echo "FATAL: 正しい資格情報でも認証が通りません。全員が締め出されるため停止します。" >&2
  echo "       原因の候補: bcrypt(\$2y\$)非対応の実行環境。htpasswd の -B を -m に変えて再デプロイしてください。" >&2
  exit 1
fi
echo "起動セルフテストOK: 未認証=401 / 認証済み=${_code_auth}"

wait -n "$STREAMLIT_PID" "$NGINX_PID"
exit $?
