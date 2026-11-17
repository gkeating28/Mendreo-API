"""Play a scripted general chat and print whether a persona marker survives.

This calls the real model through Agent.get_response and spends tokens.
It needs local API keys. It is not part of the pytest suite.

The chat runs in one database transaction that is rolled back. It never
calls AIWorkerClient. It refuses to start unless the database is local
Postgres on port 5433 and neither SUPABASE_DEV_DB_URL nor AI_WORKER_URL
is set.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse


def _configured_database():
    """Host, port, and name from the environment, before Django connects."""
    url = os.environ.get("SUPABASE_DEV_DB_URL", "").strip()
    if url:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = str(parsed.port or 5432)
        name = parsed.path.lstrip("/") or "(none)"
        return host, port, name
    host = os.environ.get("DATABASE_HOST", "localhost")
    port = os.environ.get("DATABASE_PORT", "5432")
    name = os.environ.get("DATABASE_NAME", "postgres")
    return host, port, name


def _guard_reasons(host: str, port: str) -> list[str]:
    reasons = []
    if os.environ.get("SUPABASE_DEV_DB_URL", "").strip():
        reasons.append("SUPABASE_DEV_DB_URL is set")
    if os.environ.get("AI_WORKER_URL", "").strip():
        reasons.append("AI_WORKER_URL is set")
    if host not in ("localhost", "127.0.0.1"):
        reasons.append(f"database host is {host or '(empty)'}")
    if str(port) != "5433":
        reasons.append(f"database port is {port or '(empty)'}")
    return reasons


def _print_target(host: str, port: str, name: str) -> None:
    print(f"host={host}")
    print(f"port={port}")
    print(f"database={name}")


def _print_turn(user_text: str, reply, marker: str) -> None:
    text = (getattr(reply, "text", None) or "") if reply is not None else ""
    exercise_id = getattr(reply, "exercise_id", None) if reply is not None else None
    chips = getattr(reply, "suggested_responses", None) if reply is not None else None
    found = marker.casefold() in text.casefold()
    print(f"user: {user_text}")
    print(f"toni: {text}")
    print(f"persona: {found}")
    print(f"exercise_id: {exercise_id}")
    print(f"chips: {chips}")
    print("---")


def _play(marker: str) -> None:
    from django.db import transaction

    from api.agent.models import Agent
    from api.consumer.models import Consumer
    from api.exercise.models import Exercise
    from api.message.models import Message
    from api.participant.models import Participant
    from api.prompt.models import PromptVersion
    from api.session.models import Session
    from api.user.models import User
    from api.utils import Constants
    from api.utils.SessionStateMachine import consume_chip
    from api.utils.prompt_blocks import invalidate_published_exercises_cache

    agent = Agent.get_default()
    if agent is None:
        print("Refusing to run: no agent row on this database.")
        raise SystemExit(1)

    with transaction.atomic():
        user = User(
            email=f"persona-probe-{uuid.uuid4().hex}@example.com",
            type=Constants.USER_TYPE_CONSUMER,
            first_name="Probe",
            last_name="User",
            password="!",
        )
        user.save()
        consumer = Consumer.objects.create(user=user, agent=agent, onboarded=True)
        session = Session.objects.create(consumer=consumer)
        user_sender, _agent_sender = Participant.create_participants(session)

        latest = (
            PromptVersion.objects.filter(key=Constants.PROMPT_KEY_GOALS)
            .order_by("-version")
            .only("version")
            .first()
        )
        goals = PromptVersion.objects.create(
            key=Constants.PROMPT_KEY_GOALS,
            body=(
                f"Speak like a {marker} in every reply, including after an exercise "
                f"offer and after the person says no. Use the word {marker}."
            ),
            version=(latest.version + 1) if latest else 1,
            active=False,
        )
        session.prompt_version = goals
        session.cached_prompt_meta = {
            "versions": {Constants.PROMPT_KEY_GOALS: goals.version},
        }
        session.save(update_fields=["prompt_version", "cached_prompt_meta", "updated_at"])

        Exercise.objects.create(
            title="Name the Worry",
            subtitle="A short exercise",
            description="When a worry keeps circling.",
            use_when="Use when the person is stuck on a worry.",
            steps_no=1,
            icon="leaf",
            icon_background_color="tan",
            status=Constants.EXERCISE_STATUS_PUBLISHED,
            authoring_snapshot=False,
        )
        invalidate_published_exercises_cache()

        def say(text: str):
            message = Message.objects.create(
                session=session, sender=user_sender, text=text
            )
            reply = Agent.get_response(session, message)
            _print_turn(text, reply, marker)
            return reply

        say("Hello. How are you today?")
        say("I have been thinking about work all morning.")
        offer = say("Can you suggest an exercise that would help with this worry?")

        chip = Message.objects.create(session=session, sender=user_sender, text="No")
        if (
            offer is not None
            and offer.exercise_id
            and offer.suggested_responses_kind == Constants.SUGGESTED_RESPONSES_KIND_OFFER
        ):
            outcome = consume_chip(chip, True)
            reply = outcome.message if outcome is not None else None
        else:
            reply = None
        _print_turn("No", reply, marker)

        say("no")
        say("Tell me more about what you just said.")
        say("What should I do this evening?")

        transaction.set_rollback(True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--marker",
        default="pirate",
        help="Word that must appear in Toni's reply if the persona survived.",
    )
    args = parser.parse_args(argv)

    host, port, name = _configured_database()
    _print_target(host, port, name)
    reasons = _guard_reasons(host, port)
    if reasons:
        print("Refusing to run: " + "; ".join(reasons))
        return 1

    backend = Path(__file__).resolve().parents[1]
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mendreo.settings")

    import django
    from django.conf import settings

    django.setup()
    configured = settings.DATABASES["default"]
    live_host = configured.get("HOST") or ""
    live_port = str(configured.get("PORT") or "")
    live_name = configured.get("NAME") or ""
    if (live_host, live_port, live_name) != (host, str(port), name):
        _print_target(live_host, live_port, live_name)
    live_reasons = _guard_reasons(live_host, live_port)
    if live_reasons:
        print("Refusing to run: " + "; ".join(live_reasons))
        return 1

    _play(args.marker)
    return 0


if __name__ == "__main__":
    sys.exit(main())
