from django.core.management.base import BaseCommand
from django.db import transaction

from api.message.models import Message
from api.run.services import iter_placed_transcript_steps
from api.session.models import Session


def _assigned_step(message, placed, check_in_completed_at):
    """0 at or before the check-in stamp. Otherwise the walk, or None."""
    created = message.created_at
    if (
        check_in_completed_at is not None
        and created is not None
        and created <= check_in_completed_at
    ):
        return 0
    return placed.get(message.id)


def backfill_session(session, *, dry_run: bool) -> tuple[int, int]:
    """Place null step_no rows on one session. Returns (placed, left_null)."""
    null_ids = set(
        Message.objects.filter(session=session, step_no__isnull=True).values_list(
            "id", flat=True
        )
    )
    if not null_ids:
        return 0, 0
    if not session.exercise_id:
        return 0, len(null_ids)

    messages = list(
        Message.objects.filter(session=session)
        .select_related("sender")
        .order_by("created_at", "id")
    )
    placed_map = {
        message.id: step
        for message, step in iter_placed_transcript_steps(
            messages,
            check_in_completed_at=session.pre_exercise_completed_at,
        )
    }
    updates = []
    left_null = 0
    for message in messages:
        if message.id not in null_ids:
            continue
        step = _assigned_step(message, placed_map, session.pre_exercise_completed_at)
        if step is None:
            left_null += 1
            continue
        updates.append((message.id, step))

    if dry_run or not updates:
        return len(updates), left_null

    with transaction.atomic():
        for message_id, step in updates:
            Message.objects.filter(id=message_id, step_no__isnull=True).update(
                step_no=step
            )
    return len(updates), left_null


def sessions_with_null_step(session_id=None):
    queryset = Session.objects.filter(messages__step_no__isnull=True).distinct()
    if session_id:
        queryset = queryset.filter(id=session_id)
    return list(queryset.order_by("id"))


class Command(BaseCommand):
    help = (
        "Fill Message.step_no where it is null, using the check-in stamp and "
        "the completion-label walk. Does not guess step 1."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print counts only. Does not write.",
        )
        parser.add_argument(
            "--session-id",
            default=None,
            help="Restrict the run to one session id.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        session_id = (options.get("session_id") or "").strip() or None
        placed = 0
        left_null = 0
        touched = 0
        for session in sessions_with_null_step(session_id):
            session_placed, session_left = backfill_session(session, dry_run=dry_run)
            if session_placed or session_left:
                touched += 1
            placed += session_placed
            left_null += session_left

        self.stdout.write(f"placed: {placed}")
        self.stdout.write(f"left null: {left_null}")
        self.stdout.write(f"sessions touched: {touched}")
