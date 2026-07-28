from django.contrib.postgres.fields import ArrayField
from django.db import models

from ..utils.Fields import CharIDField
from ..utils.Models import SmartModel


class Message(SmartModel):
    id = CharIDField(primary_key=True, prefix="msg_")
    
    session = models.ForeignKey('api.Session', related_name='messages', on_delete=models.CASCADE)
    sender = models.ForeignKey('api.Participant', related_name='messages', on_delete=models.CASCADE)
    asset = models.ForeignKey("api.Asset", related_name="messages", null=True, on_delete=models.SET_NULL)
    exercise = models.ForeignKey("api.Exercise", related_name="messages", null=True, on_delete=models.SET_NULL)

    text = models.TextField()
    reasoning = models.TextField(null=True)
    suggested_responses = ArrayField(models.CharField(max_length=255, blank=False), blank=True, null=True)

    step_no = models.PositiveIntegerField(null=True)
    completion_label = models.TextField(null=True)
    completion_result = models.TextField(null=True)
    is_step_complete = models.BooleanField(null=True)

    usage = models.JSONField(null=True)

    class Meta:
        indexes = [
            models.Index(fields=["session", "created_at"], name="message_session_created_idx"),
        ]

    def __str__(self):
        """Return a human-readable representation of the model instance."""
        return "Message: {}".format(self.id)