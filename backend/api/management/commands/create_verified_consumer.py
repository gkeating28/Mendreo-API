from datetime import date, datetime

from django.contrib.auth import password_validation as validators
from django.contrib.auth.hashers import make_password
from django.core import exceptions as django_exceptions
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from api.agent.models import Agent
from api.consumer.models import Consumer
from api.summary.models import Summary
from api.subscription.models import Subscription
from api.user.models import User
from api.utils import Constants
from api.utils import Subscription as SubscriptionUtils


class Command(BaseCommand):
    help = (
        "Create a consumer with a given email and password, already email-verified, "
        "so signup can skip the verification-email loop. Also grants complimentary "
        "access (active subscription + onboarded by default)."
    )

    def add_arguments(self, parser):
        parser.add_argument("email", type=str, help="Consumer email address")
        parser.add_argument("password", type=str, help="Login password")
        parser.add_argument(
            "--first-name",
            type=str,
            default="Test",
            help="First name (default: Test)",
        )
        parser.add_argument(
            "--last-name",
            type=str,
            default="User",
            help="Last name (default: User)",
        )
        parser.add_argument(
            "--date-of-birth",
            type=str,
            default="1990-01-01",
            help="YYYY-MM-DD (default: 1990-01-01)",
        )
        parser.add_argument(
            "--update",
            action="store_true",
            help="If the email already exists as a consumer, reset password and verify",
        )
        parser.add_argument(
            "--skip-onboarded",
            action="store_true",
            help="Do not force onboarded=True (still activates subscription + verifies email)",
        )

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        password = options["password"]
        first_name = options["first_name"].strip()
        last_name = options["last_name"].strip()
        skip_onboarded = options["skip_onboarded"]

        try:
            dob = datetime.strptime(options["date_of_birth"], "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError("--date-of-birth must be YYYY-MM-DD") from exc

        if dob >= date.today():
            raise CommandError("--date-of-birth must be in the past")

        try:
            validators.validate_password(password=password, user=User)
        except django_exceptions.ValidationError as exc:
            raise CommandError(exc.messages[0]) from exc

        hashed = make_password(password)

        with transaction.atomic():
            existing = User.objects.filter(email__iexact=email).first()
            if existing:
                if not options["update"]:
                    raise CommandError(
                        f"User {email!r} already exists. Re-run with --update to "
                        "reset password, verify email, and grant complimentary access."
                    )
                if not hasattr(existing, "consumer"):
                    raise CommandError(f"User {email!r} exists but is not a consumer")

                existing.password = hashed
                existing.email_verified = True
                existing.verification_code = None
                existing.status = Constants.USER_STATUS_DEFAULT
                existing.first_name = first_name or existing.first_name
                existing.last_name = last_name or existing.last_name
                existing.save()

                consumer = existing.consumer
                if existing.consumer.date_of_birth != dob:
                    consumer.date_of_birth = dob
                    consumer.save(update_fields=["date_of_birth"])

                created = False
            else:
                agent = Agent.get_default()
                if agent is None:
                    raise CommandError("No Agent exists; seed an agent before creating consumers")

                user = User.objects.create(
                    email=email,
                    password=hashed,
                    type=Constants.USER_TYPE_CONSUMER,
                    first_name=first_name,
                    last_name=last_name,
                    email_verified=True,
                    status=Constants.USER_STATUS_DEFAULT,
                )
                consumer = Consumer.objects.create(
                    user=user,
                    agent=agent,
                    date_of_birth=dob,
                )
                Summary.get_or_create(consumer)
                Subscription.create(consumer)
                created = True

            SubscriptionUtils.grant_complimentary_access(
                consumer,
                mark_onboarded=not skip_onboarded,
            )

        consumer.refresh_from_db()
        user = consumer.user
        subscription = consumer.subscription
        action = "Created" if created else "Updated"

        self.stdout.write(
            self.style.SUCCESS(
                f"{action} verified consumer {user.email}: "
                f"email_verified={user.email_verified}, "
                f"active={subscription.active}, "
                f"onboarded={consumer.onboarded}"
            )
        )
