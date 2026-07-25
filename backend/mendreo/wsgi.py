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

# get_wsgi_application() only runs django.setup() (installed apps/models); the
# URL tree (mendreo.urls -> api.urls -> every view/serializer, which pulls in
# stripe, boto3, pydantic_ai, etc.) is resolved lazily on first use, which is
# PER WORKER PROCESS, not shared by gunicorn's --preload copy-on-write fork.
# On a CPU-constrained host that first-request import cost can be large
# enough to blow past request timeouts. Force it here, once, in the master
# process before gunicorn forks, so every worker inherits it for free.
try:
    from django.urls import get_resolver

    get_resolver().url_patterns
except Exception:
    # Don't block startup on a warm-up failure; the real error (if any)
    # will surface on the first actual request instead.
    pass


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
