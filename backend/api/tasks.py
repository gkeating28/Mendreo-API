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
    from .utils import DateUtils

    yesterday = timezone.now().date() - timedelta(days=1)  # previous day
    start, end = DateUtils.day_bounds(yesterday)
    consumer_ids = Consumer.objects.filter(
        sessions__created_at__gte=start,
        sessions__created_at__lt=end,
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


@shared_task(
    name="process_agent_response",
    ignore_result=True,
    base=TransactionAwareTask,
    soft_time_limit=150,
    time_limit=180,
)
def process_agent_response(user_message_id):
    """Generate the agent reply for a committed user message (async chat)."""
    from .agent.models import Agent
    from .message.models import Message
    from .utils.MessageFlow import apply_agent_response

    logger.info("Start > process_agent_response %s", user_message_id)
    user_message = Message.objects.select_related("session").filter(id=user_message_id).first()
    if not user_message:
        logger.warning("process_agent_response: message %s not found", user_message_id)
        return

    agent_message = Agent.get_response(user_message=user_message, session=user_message.session)
    apply_agent_response(user_message, agent_message)
    logger.info("End > process_agent_response %s -> %s", user_message_id, agent_message.id)


@shared_task(
    name="process_session_greeting",
    ignore_result=True,
    base=TransactionAwareTask,
    soft_time_limit=150,
    time_limit=180,
)
def process_session_greeting(session_id):
    """Generate the exercise opener without blocking session start."""
    from .session.models import Session
    from .utils.AIWorkerClient import _run_session_greeting

    logger.info("Start > process_session_greeting %s", session_id)
    session = Session.objects.filter(id=session_id).first()
    if not session:
        logger.warning("process_session_greeting: session %s not found", session_id)
        return
    _run_session_greeting(session)
    logger.info("End > process_session_greeting %s", session_id)


@shared_task(
    name="backfill_knowledge_from_onboarding",
    ignore_result=True,
    base=TransactionAwareTask,
)
def backfill_knowledge_from_onboarding(consumer_id=None):
    """
    One-shot / re-runnable backfill of KnowledgeEntry rows from onboarding Attribute answers.
    Matching uses Attribute.key → KnowledgeField.key. Idempotent via attribute FK.
    """
    from .knowledge.services import backfill_knowledge_from_onboarding as _backfill

    logger.info("Start > backfill_knowledge_from_onboarding consumer_id=%s", consumer_id)
    result = _backfill(consumer_id=consumer_id)
    logger.info("End > backfill_knowledge_from_onboarding %s", result)
    return result


@shared_task(
    base=PeriodicTask,
    run_every=crontab(minute=0, hour=2),  # 2:00 AM
    name="generate_user_observations",
    ignore_result=True,
)
def generate_user_observations():
    """Fan-out overnight observation generation for active consumers."""
    from .consumer.models import Consumer
    from .setting.models import Setting

    if not Setting.get_observations_enabled():
        logger.info("generate_user_observations skipped — observations disabled")
        return

    # Consumers with recent activity (knowledge or sessions in last 30 days)
    since = timezone.now() - timedelta(days=30)
    consumer_ids = set(
        Consumer.objects.filter(sessions__created_at__gte=since)
        .values_list("user_id", flat=True)
        .distinct()
    )
    consumer_ids.update(
        Consumer.objects.filter(knowledge_entries__created_at__gte=since)
        .values_list("user_id", flat=True)
        .distinct()
    )

    for consumer_id in consumer_ids:
        generate_user_observation.delay_on_commit(consumer_id)

    logger.info("generate_user_observations queued %s consumers", len(consumer_ids))


@shared_task(
    name="generate_user_observation",
    ignore_result=True,
    base=TransactionAwareTask,
    soft_time_limit=120,
    time_limit=150,
)
def generate_user_observation(consumer_id):
    from .consumer.models import Consumer
    from .progress.services import generate_observation_for_consumer

    logger.info("Start > generate_user_observation %s", consumer_id)
    consumer = Consumer.objects.filter(pk=consumer_id).first()
    if not consumer:
        logger.warning("generate_user_observation: consumer %s not found", consumer_id)
        return
    observation = generate_observation_for_consumer(consumer)
    logger.info(
        "End > generate_user_observation %s -> %s",
        consumer_id,
        getattr(observation, "id", None),
    )
    return getattr(observation, "id", None)
