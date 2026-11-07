import logging
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


def select_consumers(*, limit, consumer_id=None):
    """Consumers to generate for. One id, or anyone active in the last 30 days."""
    from api.consumer.models import Consumer

    if consumer_id:
        return list(Consumer.objects.filter(pk=consumer_id).order_by("user_id")[:limit])

    since = timezone.now() - timedelta(days=30)
    ids = set(
        Consumer.objects.filter(sessions__created_at__gte=since)
        .values_list("user_id", flat=True)
        .distinct()
    )
    ids.update(
        Consumer.objects.filter(knowledge_entries__created_at__gte=since)
        .values_list("user_id", flat=True)
        .distinct()
    )
    return list(Consumer.objects.filter(pk__in=ids).order_by("user_id")[:limit])


class Command(BaseCommand):
    help = "Generate conversation-starter insights. Prints consumer ids and result codes only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Maximum consumers to consider (default 50).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List ids and a count. Does not generate insights.",
        )
        parser.add_argument(
            "--consumer-id",
            default=None,
            help="Restrict the selection to one consumer id.",
        )

    def handle(self, *args, **options):
        from api.progress.insights import generate_insights_for_consumer

        limit = options["limit"]
        dry_run = options["dry_run"]
        consumer_id = (options.get("consumer_id") or "").strip() or None
        consumers = select_consumers(limit=limit, consumer_id=consumer_id)

        for index, consumer in enumerate(consumers):
            if dry_run:
                self.stdout.write(consumer.pk)
                continue
            if index:
                time.sleep(1)
            try:
                result = generate_insights_for_consumer(consumer)
            except Exception as exc:
                logger.warning(
                    "Insight generation failed for %s (%s)",
                    consumer.pk,
                    type(exc).__name__,
                )
                result = "failed"
            self.stdout.write(f"{consumer.pk} {result}")

        if dry_run:
            self.stdout.write(f"count {len(consumers)}")
