from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Exists, OuterRef

from api.message.models import Message
from api.session.models import Session
from api.user.models import User


class Command(BaseCommand):
    help = (
        "Soft-delete empty general chats (Chat with Toni placeholders) for one "
        "consumer email. Dry-run unless --execute is passed. Never touches "
        "other users."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            required=True,
            help="Consumer email to clean (case-insensitive). Required.",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Actually soft-delete. Omit this flag to print counts only.",
        )

    def handle(self, *args, **options):
        email = options["email"].strip()
        if not email:
            raise CommandError("--email is required")

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist as exc:
            raise CommandError(f"No user found with email {email!r}") from exc
        except User.MultipleObjectsReturned as exc:
            raise CommandError(f"Multiple users match {email!r}; refusing to run") from exc

        if not hasattr(user, "consumer"):
            raise CommandError(f"{email!r} is not a consumer account")

        consumer = user.consumer
        consumer_id = consumer.user_id

        has_real_message = Message.objects.filter(
            session_id=OuterRef("pk"),
            deleted_at__isnull=True,
        ).exclude(text__regex=r"^\s*$")

        general = Session.objects.filter(consumer=consumer, exercise__isnull=True)
        empty = (
            general.filter(
                messages_no=0,
                consumer_messages_no=0,
                agent_messages_no=0,
                last_message__isnull=True,
            )
            .annotate(has_real=Exists(has_real_message))
            .filter(has_real=False)
        )
        kept = general.exclude(id__in=empty.values("id"))

        empty_ids = list(empty.order_by("-updated_at").values_list("id", flat=True))
        kept_ids = list(kept.order_by("-updated_at").values_list("id", "messages_no")[:12])

        self.stdout.write(
            f"Account: {user.email} (user {user.id}, consumer {consumer_id})"
        )
        self.stdout.write(f"General chats: {general.count()}")
        self.stdout.write(f"Would keep (have message content): {kept.count()}")
        self.stdout.write(f"Would delete (empty placeholders): {len(empty_ids)}")
        if empty_ids:
            self.stdout.write("Empty ids: " + ", ".join(empty_ids[:25]))
            if len(empty_ids) > 25:
                self.stdout.write(f"... and {len(empty_ids) - 25} more")
        if kept_ids:
            kept_preview = ", ".join(f"{sid} (msgs {n})" for sid, n in kept_ids)
            self.stdout.write("Kept sample: " + kept_preview)

        other_users = empty.exclude(consumer_id=consumer_id).count()
        if other_users:
            raise CommandError(
                f"Safety abort: queryset included {other_users} rows for other consumers"
            )

        if not options["execute"]:
            self.stdout.write(self.style.WARNING("Dry-run only. Pass --execute to soft-delete."))
            return

        if not empty_ids:
            self.stdout.write("Nothing to delete.")
            return

        with transaction.atomic():
            deleted = Session.objects.filter(
                consumer=consumer,
                id__in=empty_ids,
            ).delete()

        remaining_empty = (
            Session.objects.filter(consumer=consumer, exercise__isnull=True)
            .filter(
                messages_no=0,
                consumer_messages_no=0,
                agent_messages_no=0,
                last_message__isnull=True,
            )
            .annotate(has_real=Exists(has_real_message))
            .filter(has_real=False)
            .count()
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Soft-deleted {deleted} empty general chats for {user.email}. "
                f"Remaining empty: {remaining_empty}."
            )
        )
