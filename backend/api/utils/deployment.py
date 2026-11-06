"""Shared check for endpoints that exist only on local and worker processes."""

from django.conf import settings


def allows_dev_controls() -> bool:
    """True only when DEPLOYMENT_TARGET is "local" or starts with "worker".

    settings.DEPLOYMENT_TARGET is the environment value, or "local" when that
    variable is unset. Every other value, including an unexpected one, is closed.
    """
    target = getattr(settings, "DEPLOYMENT_TARGET", "")
    if not isinstance(target, str):
        return False
    return target == "local" or target.startswith("worker")
