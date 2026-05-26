release: cd mendreo && python manage.py migrate
web: cd mendreo && newrelic-admin run-program gunicorn mendreo.wsgi --log-file - --error-logfile -
worker: cd mendreo && newrelic-admin run-program celery -A mendreo worker --loglevel=info --concurrency=2
scheduler: cd mendreo && newrelic-admin run-program celery -A mendreo beat --loglevel=info
