from __future__ import absolute_import, unicode_literals

from datetime import timedelta

from celery.schedules import crontab
from celery.utils.log import get_task_logger
from celery import shared_task, Task, Celery
from django.db import transaction
from django.conf import settings
from django.utils import timezone


logger = get_task_logger(__name__)

app = Celery('mendreo')
# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object(settings, namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()


class TransactionAwareTask(Task):
    def delay_on_commit(self, *args, **kwargs):
        def _safe_delay():
            # A failure to dispatch a background task (e.g. email) must never
            # crash the request that triggered it - log loudly instead.
            try:
                self.delay(*args, **kwargs)
            except Exception:
                logger.exception(f"Failed to dispatch task '{self.name}'")

        return transaction.on_commit(_safe_delay)


class PeriodicTask(Task):

    @classmethod
    def on_bound(cls, app):
        app.conf.beat_schedule[cls.name] = {
            'task': cls.name,
            'schedule': cls.run_every,
            'args': (),
            'kwargs': {},
            'options': {},
            'relative': {},
        }

@shared_task(
    name="send_mail",
    ignore_result=True,
    base=TransactionAwareTask
)
def send_mail(mail_function_to_be_triggered, *args):
    from .utils import Mail
    logger.info(f"Start > send_mail with function: {mail_function_to_be_triggered}")

    getattr(Mail, mail_function_to_be_triggered)(*args)

    logger.info(f"End > send_mail with function: {mail_function_to_be_triggered}")


@app.task(
    base=PeriodicTask,
    run_every=(crontab(minute=0, hour=1)),
    name='check_subscriptions',
    ignore_result=True,
)
def check_subscriptions():
    logger.info("Start > check_subscriptions")

    from django.db.models import Q
    from .subscription.models import Subscription
    from .utils import Subscription as SubscriptionUtils

    subscriptions = Subscription.objects.filter(
        Q(payment__apple_receipt_id__isnull=False) |
        Q(payment__google_receipt_id__isnull=False) |
        Q(payment__stripe_receipt_id__isnull=False),
        payment__price__gt=0
    )

    for subscription in subscriptions:
        SubscriptionUtils.validate_subscription(subscription)

    logger.info("End > check_subscriptions")


@shared_task(
    base=PeriodicTask,
    run_every=crontab(minute=0, hour=1),  # 1:00 AM
    name='update_daily_summaries',
    ignore_result=True
)
def update_daily_summaries():
    from .consumer.models import Consumer

    yesterday = timezone.now().date() - timedelta(days=1)  # previous day
    consumer_ids = Consumer.objects.filter(
        sessions__created_at__date=yesterday
    ).values_list("user_id", flat=True).distinct()

    for consumer_id in consumer_ids:
        update_chat_summary.delay_on_commit(consumer_id)


@shared_task(
    name="update_chat_summary",
    ignore_result=True,
    base=TransactionAwareTask
)
def update_chat_summary(consumer_id, freezer=None):
    from .summary.models import Summary

    summary = Summary.objects.get(consumer_id=consumer_id)
    summary.update(freezer)


@shared_task(
    name="generate_article",
    ignore_result=True,
    base=TransactionAwareTask
)
def generate_post(id_, prompt):
    """
    Celery task to generate a new AI article every Monday at 6 AM.
    """
    from .post.models import Post

    post = Post.objects.get(id=id_)
    Post.generate(post, prompt)
