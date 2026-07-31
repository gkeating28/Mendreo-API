"""
WSGI config for mendreo project.

It exposes the WSGI callable as a module-level variable named ``application``.
"""
import os
import sys
import time
from pathlib import Path

# Django project root (contains manage.py and api/).
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mendreo.settings")


def _log(msg: str) -> None:
    # Plain stderr write, unbuffered-ish (flush explicitly): gunicorn's
    # --error-logfile - captures this straight into Railway's Deploy Logs.
    print(f"wsgi: {msg}", file=sys.stderr, flush=True)


_t0 = time.monotonic()
_log("importing django application...")

from django.core.wsgi import get_wsgi_application

_HEALTH_PATHS = frozenset(("/", "/healthz"))
_HEALTH_BODY = b'{"service":"mendreo-api","status":"ok"}'

_django_app = get_wsgi_application()
_log(f"get_wsgi_application() done at +{time.monotonic() - _t0:.2f}s")

# Populate api_aiprovider from env when empty so a blank table after migrate
# does not leave the worker unable to serve AI. Failures are logged, not fatal.
try:
    from api.utils.AiProviderFactory import ensure_providers_ready

    _providers = ensure_providers_ready()
    _log(f"AI providers ready: {len(_providers)} candidate(s)")
except Exception as exc:
    _log(f"AI provider startup seed FAILED: {exc!r}")

def _warn_if_still_running(done_flag: list) -> None:
    """Background watchdog: logs progress if the warm-up below never returns,
    so Deploy Logs show a hang in progress instead of just going silent."""
    for _ in range(12):  # check every 5s, up to 60s
        time.sleep(5)
        if done_flag[0]:
            return
        _log(f"urlconf warm-up STILL RUNNING after +{time.monotonic() - _t0:.2f}s (this is the hang)")


# get_wsgi_application() only runs django.setup() (installed apps/models); the
# URL tree (mendreo.urls -> api.urls -> every view/serializer, which pulls in
# stripe, boto3, pydantic_ai, etc.) is resolved lazily on first use, which is
# PER WORKER PROCESS, not shared by gunicorn's --preload copy-on-write fork.
# On a CPU-constrained host that first-request import cost can be large
# enough to blow past request timeouts. Force it here, once, in the master
# process before gunicorn forks, so every worker inherits it for free.
try:
    _log("warming up full URL tree (urlconf)...")
    from django.urls import get_resolver
    import threading

    _done = [False]
    _watchdog = threading.Thread(target=_warn_if_still_running, args=(_done,), daemon=True)
    _watchdog.start()

    get_resolver().url_patterns
    _done[0] = True
    _log(f"urlconf warm-up done at +{time.monotonic() - _t0:.2f}s")
except Exception as exc:
    _done[0] = True
    # Don't block startup on a warm-up failure; the real error (if any)
    # will surface on the first actual request instead. Log it loudly so
    # it's visible in Deploy Logs rather than silently swallowed.
    _log(f"urlconf warm-up FAILED at +{time.monotonic() - _t0:.2f}s: {exc!r}")


def application(environ, start_response):
    path = environ.get("PATH_INFO")
    # Respond before Django URL resolution so health probes never load the full API urlconf.
    if path in _HEALTH_PATHS:
        start_response(
            "200 OK",
            [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(_HEALTH_BODY))),
            ],
        )
        return [_HEALTH_BODY]

    req_t0 = time.monotonic()
    _log(f"-> entering django for {environ.get('REQUEST_METHOD')} {path}")
    try:
        result = _django_app(environ, start_response)
    except Exception as exc:
        _log(f"<- django RAISED for {path} after {time.monotonic() - req_t0:.2f}s: {exc!r}")
        raise
    _log(f"<- django returned for {path} after {time.monotonic() - req_t0:.2f}s")
    return result


app = application
