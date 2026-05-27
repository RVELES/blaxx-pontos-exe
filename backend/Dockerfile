# =============================================================================
# Blaxx Pontos · backend · imagem Docker para Fly.io
# =============================================================================
# CACHE BUSTER 2026-05-25-google-login (bumpa este número sempre que alterar
# requirements.txt pra GARANTIR que pip install rebuilda do zero).
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# psycopg precisa de libpq + build-essential temporariamente
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependências primeiro (cache de camada melhor)
COPY requirements.txt .
# Verifica imediatamente que google-auth foi instalado, falha o build se não.
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && python -c "from google.oauth2 import id_token; from google.auth.transport import requests as gr; import requests; print('✓ Google OAuth stack OK')" \
    && apt-get purge -y build-essential libpq-dev \
    && apt-get autoremove -y

# Código da aplicação
COPY . .

# Fly.io seta $PORT (default 8080 no fly.toml abaixo)
ENV PORT=8080
EXPOSE 8080

# Healthcheck do container (Fly também faz HTTP /health)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen(f'http://127.0.0.1:{__import__(\"os\").environ.get(\"PORT\",\"8080\")}/health', timeout=3); sys.exit(0)" \
    || exit 1

# Entry: cria tabelas e sobe o gunicorn.
# Seed roda separado via `fly ssh console -C "python seed.py"`.
CMD sh -c "python -c 'from app import create_app; create_app()' && \
           gunicorn --bind 0.0.0.0:${PORT} \
                    --workers 2 \
                    --threads 4 \
                    --timeout 60 \
                    --access-logfile - \
                    --error-logfile - \
                    run:app"
