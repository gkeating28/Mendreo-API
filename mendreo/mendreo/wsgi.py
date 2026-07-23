"""
WSGI config for mendreo project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os
import sys
from pathlib import Path

# Vercel runs from the repo root; Django lives under mendreo/ (see manage.py).
_project_root = Path(__file__).resolve().parent.parent
# Always prepend (see repo-root wsgi.py) — avoid mendreo/ dir shadowing imports.
sys.path.insert(0, str(_project_root))

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mendreo.settings')

application = get_wsgi_application()
app = application
