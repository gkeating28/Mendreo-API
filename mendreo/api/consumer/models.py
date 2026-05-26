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

    surveyed = models.BooleanField(default=False)

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
