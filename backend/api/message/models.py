from django.contrib.postgres.fields import ArrayField
from django.db import models

from ..utils import Constants
from ..utils.Fields import CharIDField, EnumField
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

    completion_label = models.TextField(null=True)

    usage = models.JSONField(null=True)

    resources = models.JSONField(null=True, blank=True)
    suggested_responses_kind = EnumField(
        options=Constants.SUGGESTED_RESPONSES_KINDS,
        default=Constants.SUGGESTED_RESPONSES_KIND_FREE,
    )
    question_kind = EnumField(
        options=Constants.QUESTION_KINDS,
        default=Constants.QUESTION_KIND_NONE,
    )
    probe_count = models.PositiveIntegerField(default=0)

    # Voice (ElevenLabs) idempotency — nullable; typed chat leaves these unset.
    voice_conversation_id = models.CharField(max_length=64, null=True, blank=True)
    voice_turn_index = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["session", "created_at"], name="message_session_created_idx"),
            models.Index(
                fields=["session", "voice_conversation_id", "voice_turn_index"],
                name="message_voice_turn_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "voice_conversation_id", "voice_turn_index"],
                condition=models.Q(
                    voice_conversation_id__isnull=False,
                    voice_turn_index__isnull=False,
                ),
                name="uniq_message_voice_turn",
            ),
        ]

    def __str__(self):
        """Return a human-readable representation of the model instance."""
        return "Message: {}".format(self.id)