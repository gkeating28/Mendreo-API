from __future__ import absolute_import, unicode_literals

import os

# Defer Celery import on Vercel to reduce cold-start memory and import time.
if os.environ.get("DEPLOYMENT_TARGET") == "vercel":
    def __getattr__(name):
        if name == "celery_app":
            from .celerySettings import app as celery_app
            return celery_app
        raise AttributeError(name)
else:
    from .celerySettings import app as celery_app

    __all__ = ('celery_app',)