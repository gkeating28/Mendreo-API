from __future__ import absolute_import, unicode_literals

import os

# Defer Celery import in serverless and Gunicorn web processes (Celery runs separately).
if os.environ.get("DEPLOYMENT_TARGET") == "vercel" or os.environ.get("MENDREO_SKIP_CELERY_IMPORT") == "1":
    def __getattr__(name):
        if name == "celery_app":
            from .celerySettings import app as celery_app
            return celery_app
        raise AttributeError(name)
else:
    from .celerySettings import app as celery_app

    __all__ = ('celery_app',)