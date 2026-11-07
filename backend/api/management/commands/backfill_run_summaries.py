import logging
import time

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


def select_sessions(*, limit, session_id=None):
    """Completed exercise runs that never received a run summary, newest first."""
    from api.session.models import Session

    queryset = Session.objects.filter(
        completed=True,
        run_summary__isnull=True,
        exercise__isnull=False,
        authoring_test=False,
    ).order_by("-completed_at", "-updated_at", "-id")
    if session_id:
        queryset = queryset.filter(id=session_id)
    return list(queryset[:limit])


class Command(BaseCommand):
    help = (
        "Write missing run summaries for completed exercise sessions. "
        "Prints session ids and counts only."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Maximum sessions to consider (default 50).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List ids and a count. Does not call the model.",
        )
        parser.add_argument(
            "--session-id",
            default=None,
            help="Restrict the selection to one session id.",
        )

    def handle(self, *args, **options):
        from api.utils.session_close import _update_run_summary

        limit = options["limit"]
        dry_run = options["dry_run"]
        session_id = (options.get("session_id") or "").strip() or None
        sessions = select_sessions(limit=limit, session_id=session_id)

        generated = 0
        skipped = 0
        failed = 0
        for index, session in enumerate(sessions):
            self.stdout.write(session.id)
            if dry_run:
                continue
            if index:
                time.sleep(1)
            try:
                _update_run_summary(session)
            except Exception as exc:
                failed += 1
                logger.warning(
                    "Run summary failed for %s (%s)",
                    session.id,
                    type(exc).__name__,
                )
                continue
            if session.run_summary:
                generated += 1
            else:
                skipped += 1

        if dry_run:
            self.stdout.write(f"count {len(sessions)}")
            return

        self.stdout.write(f"generated {generated}")
        self.stdout.write(f"skipped {skipped}")
        self.stdout.write(f"failed {failed}")
