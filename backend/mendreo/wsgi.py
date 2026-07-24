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

application = get_wsgi_application()
app = application
