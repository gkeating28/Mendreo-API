FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gdal-bin libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mendreo ./mendreo
COPY set_db_env.sh ./set_db_env.sh
COPY deploy/worker/start.sh ./start.sh

RUN chmod +x ./start.sh

ENV DEPLOYMENT_TARGET=worker \
    PORT=8000

EXPOSE 8000

CMD ["./start.sh"]
