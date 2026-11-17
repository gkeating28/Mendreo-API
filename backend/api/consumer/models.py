from django.db import models

from ..agent.models import Agent
from ..user.models import User
from ..utils.Models import SmartModel


class Consumer(SmartModel):
    """
    Model instance for storing a consumer/regular user of the platform
    """

    user = models.OneToOneField(User, primary_key=True, related_name='consumer', on_delete=models.CASCADE)

    agent = models.ForeignKey(Agent, related_name='consumers', on_delete=models.DO_NOTHING)

    stripe_customer_id = models.CharField(max_length=255, null=True)

    date_of_birth = models.DateField(null=True)

    onboarded = models.BooleanField(default=False)

    # Set when a turn closes for the person's own high risk. The apps read
    # this on the consumer payload and show the support modal until dismiss.
    # Database default so older inserts that omit the column still succeed.
    crisis_notice_pending = models.BooleanField(default=False, db_default=False)

    # How the account was created. Nullable with a database default so the
    # current main branch, which does not know this column, can still insert
    # consumers on the shared dev database.
    signup_source = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        default="register",
        db_default="register",
    )

    # Set when the welcome flow is submitted complete. Null means "not submitted".
    # No active welcome questions (or all skipped as already known) counts as
    # complete without writing this timestamp.
    welcome_completed_at = models.DateTimeField(
        null=True, blank=True, default=None, db_default=None
    )

    surveyed = models.BooleanField(default=False)

    # Last completed Initial / Return / Refresh onboarding flow (V2 Slice D).
    last_onboarding_flow_completed_at = models.DateTimeField(null=True, blank=True)
    last_onboarding_flow_variant = models.CharField(max_length=32, null=True, blank=True)

    # Set on the first post-onboarding general-chat user message. Follow-up
    # injection never runs again after this, even if flagged answers remain.
    onboarding_followup_consumed_at = models.DateTimeField(null=True, blank=True)
    onboarding_followup_session_id = models.CharField(max_length=40, null=True, blank=True)
    onboarding_followup_consent = models.CharField(max_length=16, null=True, blank=True)
    onboarding_followup_classified_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        """Return a human readable representation of the model instance."""
        return "Consumer: {}".format(self.user)

    def update_onboarding_status(self):
        from ..question.models import Question
        if self.onboarded or not self.subscription.active or not self.user.email_verified:
            return

        if not self.date_of_birth:
            return

        answered_question_ids = self.attributes.values_list("question_id", flat=True)
        if not Question.objects.filter(survey=False).exclude(id__in=answered_question_ids).exists():
            self.onboarded = True
            self.save()

    def update_surveyed_status(self):
        from ..question.models import Question
        if self.surveyed or not self.onboarded:
            return

        answered_question_ids = self.attributes.values_list("question_id", flat=True)
        if not Question.objects.filter(survey=True).exclude(id__in=answered_question_ids).exists():
            self.surveyed = True
            self.save()
