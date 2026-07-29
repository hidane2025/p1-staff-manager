# P1 Staff Manager — Basic認証つき本番コンテナ（2026-07-28）
#   ・外部に出るのは nginx のみ。Streamlit は 127.0.0.1 でしか待ち受けない
#   ・管理画面は Basic認証必須／スタッフのトークンURL 2本のみ免除
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_PORT=8501

RUN apt-get update && apt-get install -y --no-install-recommends \
        nginx apache2-utils gettext-base curl \
    && rm -rf /var/lib/apt/lists/* \
    # Debianのnginxが同梱する既定サイト（認証なしでlisten 80）を消す
    && rm -f /etc/nginx/sites-enabled/default \
    # nginxのログをコンテナの標準出力/エラーへ向け、ホスティングのログに出す
    #（既定はファイル出力のため502等の実行時エラーが完全に不可視になる）
    && ln -sf /dev/stdout /var/log/nginx/access.log \
    && ln -sf /dev/stderr /var/log/nginx/error.log

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8080
CMD ["/app/deploy/entrypoint.sh"]
