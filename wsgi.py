"""
Vercel entrypoint shim.

Django lives under mendreo/ (manage.py is there). Vercel may run from the repo
root, so this file adds mendreo/ to sys.path before booting Django.
"""
import importlib.util
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent / "mendreo"
_INNER_PKG = _PROJECT_ROOT / "mendreo"

sys.path.insert(0, str(_PROJECT_ROOT))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_load_module("mendreo.settings", _INNER_PKG / "settings.py")
_load_module("mendreo.urls", _INNER_PKG / "urls.py")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mendreo.settings")

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
app = application
