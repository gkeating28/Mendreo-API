FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Runtime libs for psycopg2/lxml/pillow wheels; no GeoDjango/GDAL in this project.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        libxml2 \
        libxslt1.1 \
        libjpeg62-turbo \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-worker.txt ./requirements-worker.txt
RUN pip install --no-cache-dir -r requirements-worker.txt

COPY backend ./backend
COPY set_db_env.sh ./set_db_env.sh
COPY deploy/worker/start.sh ./start.sh

RUN chmod +x ./start.sh

ENV DEPLOYMENT_TARGET=worker \
    PORT=8000

EXPOSE 8000

CMD ["./start.sh"]
