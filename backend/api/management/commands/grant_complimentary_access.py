from django.core.management.base import BaseCommand, CommandError

from api.user.models import User
from api.utils import Subscription as SubscriptionUtils


class Command(BaseCommand):
    help = (
        "Grant complimentary access (active subscription, verified email, "
        "optionally onboarded) without Stripe. Temporary until billing is wired."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "email",
            type=str,
            help="Consumer email address (case-insensitive)",
        )
        parser.add_argument(
            "--skip-onboarded",
            action="store_true",
            help="Do not force onboarded=True (still activates subscription)",
        )

    def handle(self, *args, **options):
        email = options["email"].strip()
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist as exc:
            raise CommandError(f"No user found with email {email!r}") from exc

        if not hasattr(user, "consumer"):
            raise CommandError(f"User {email!r} is not a consumer")

        consumer = user.consumer
        SubscriptionUtils.grant_complimentary_access(
            consumer,
            mark_onboarded=not options["skip_onboarded"],
        )
        consumer.refresh_from_db()
        subscription = consumer.subscription

        self.stdout.write(
            self.style.SUCCESS(
                f"Granted complimentary access to {user.email}: "
                f"active={subscription.active}, onboarded={consumer.onboarded}, "
                f"email_verified={user.email_verified}"
            )
        )
