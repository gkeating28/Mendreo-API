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
COPY deploy/worker/start.sh ./start.sh

RUN chmod +x ./start.sh

ENV DEPLOYMENT_TARGET=worker

# Railway sets PORT at runtime (typically 8080). Do not hardcode it here.
EXPOSE 8080

CMD ["./start.sh"]
