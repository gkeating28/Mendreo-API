"""
WSGI config for mendreo project.

Vercel imports this module as mendreo.mendreo.wsgi, which breaks normal
mendreo.settings resolution. Bootstrap Django modules by file path first.
"""
import importlib.util
import os
import sys
from pathlib import Path

_pkg_root = Path(__file__).resolve().parent
_project_root = _pkg_root.parent
_inner_pkg = _pkg_root

sys.path.insert(0, str(_project_root))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Register settings/urls before Django reads DJANGO_SETTINGS_MODULE.
_load_module("mendreo.settings", _inner_pkg / "settings.py")
_load_module("mendreo.urls", _inner_pkg / "urls.py")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mendreo.settings")

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
app = application
