FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements-worker.txt ./requirements-worker.txt
RUN echo "railway-build: installing python dependencies" \
    && pip install --no-cache-dir -r requirements-worker.txt \
    && echo "railway-build: python dependencies installed"

COPY backend ./backend
COPY set_db_env.sh ./set_db_env.sh
COPY deploy/worker/start.sh ./start-all.sh
COPY deploy/web/start.sh ./start-web.sh
COPY deploy/celery-worker/start.sh ./start-celery-worker.sh
COPY deploy/celery-beat/start.sh ./start-celery-beat.sh

RUN chmod +x ./start-all.sh ./start-web.sh ./start-celery-worker.sh ./start-celery-beat.sh

ENV DEPLOYMENT_TARGET=worker \
    PORT=8000

EXPOSE 8000

CMD ["./start-all.sh"]
