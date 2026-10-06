"""Gates for an exercise-builder test session.

The session row and its messages may exist. Nothing else about the
consumer or the real exercise may change.
"""

from __future__ import annotations


def is_authoring_test(session) -> bool:
    return bool(getattr(session, "authoring_test", False))
