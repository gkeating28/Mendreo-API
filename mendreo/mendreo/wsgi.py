"""
WSGI config for mendreo project.

Vercel imports this file as mendreo.mendreo.wsgi, which breaks mendreo.settings
resolution. Delegate to the repo-root wsgi shim instead.
"""
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_repo_root))

from wsgi import app, application  # noqa: F401

__all__ = ("application", "app")
