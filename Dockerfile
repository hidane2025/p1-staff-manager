# P1 Staff Manager — Basic認証つき本番コンテナ（2026-07-28）
#   ・外部に出るのは nginx のみ。Streamlit は 127.0.0.1 でしか待ち受けない
#   ・管理画面は Basic認証必須／スタッフのトークンURL 2本のみ免除
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_PORT=8501

RUN apt-get update && apt-get install -y --no-install-recommends \
        nginx apache2-utils gettext-base curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8080
CMD ["/app/deploy/entrypoint.sh"]
