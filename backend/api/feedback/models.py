from django.db import models

from ..user.models import User
from ..message.models import Message

from ..utils.Fields import CharIDField
from ..utils.Models import SmartModel


class Feedback(SmartModel):
    id = CharIDField(primary_key=True, prefix="fdbk_")

    user = models.ForeignKey(User, related_name='feedbacks', null=True, on_delete=models.CASCADE)

    message = models.ForeignKey(Message, related_name='feedbacks', null=True, on_delete=models.CASCADE)
    positive = models.BooleanField(null=True)

    reason = models.TextField(null=True)

    value = models.TextField(null=True)

    def __str__(self):
        """Return a human-readable representation of the model instance."""
        return "Feedback: {}".format(self.id)
