"""
Vercel entrypoint shim (optional fallback if Vercel uses repo-root wsgi.py).
"""
import os
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(_project_root))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mendreo.settings")

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
app = application
