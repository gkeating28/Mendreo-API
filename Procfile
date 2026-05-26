release: cd mendreo && python manage.py migrate
web: cd mendreo && gunicorn mendreo.wsgi --log-file - --error-logfile -
worker: cd mendreo && celery -A mendreo worker --loglevel=info --concurrency=2
scheduler: cd mendreo && celery -A mendreo beat --loglevel=info
