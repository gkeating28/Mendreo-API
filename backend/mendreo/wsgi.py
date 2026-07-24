"""
WSGI config for mendreo project.

It exposes the WSGI callable as a module-level variable named ``application``.
"""
import os
import sys
from pathlib import Path

# Django project root (contains manage.py and api/).
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mendreo.settings")

from django.core.wsgi import get_wsgi_application

_HEALTH_PATHS = frozenset(("/", "/healthz"))
_HEALTH_BODY = b'{"service":"mendreo-api","status":"ok"}'

_django_app = get_wsgi_application()


def application(environ, start_response):
    # Respond before Django URL resolution so health probes never load the full API urlconf.
    if environ.get("PATH_INFO") in _HEALTH_PATHS:
        start_response(
            "200 OK",
            [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(_HEALTH_BODY))),
            ],
        )
        return [_HEALTH_BODY]
    return _django_app(environ, start_response)


app = application
