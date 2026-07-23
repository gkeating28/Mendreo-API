"""
Vercel entrypoint shim.

Django lives under mendreo/ (manage.py is there). Vercel runs from the repo
root, so this file adds mendreo/ to sys.path before booting Django.
"""
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent / "mendreo"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mendreo.settings")

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
app = application  # Vercel may look for either name
