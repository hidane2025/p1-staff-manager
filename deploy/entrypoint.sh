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
htpasswd -bcB /etc/nginx/.htpasswd "$BASIC_AUTH_USER" "$BASIC_AUTH_PASSWORD" >/dev/null 2>&1
unset BASIC_AUTH_PASSWORD

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
wait -n "$STREAMLIT_PID" "$NGINX_PID"
exit $?
