from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models.expressions import DatabaseDefault

from ..utils import Constants
from ..utils.Fields import CharIDField, EnumField
from ..utils.Models import SmartModel, SoftDeletionManager


def stamp_message_step_no(message) -> None:
    """Copy the session's live step onto a new message when the caller omitted it.

    Check-in is 0. A general chat has no step, so the column stays null.
    An explicit step_no, including 0, is left alone. Updates do not restamp.
    """
    raw = message.__dict__.get("step_no", None)
    # db_default=None puts a DatabaseDefault sentinel on unsaved rows.
    if raw is not None and not isinstance(raw, DatabaseDefault):
        return
    if not getattr(message, "session_id", None):
        return
    current = message.session.current_step_no
    if current is None:
        return
    message.step_no = current


class MessageManager(SoftDeletionManager):
    def bulk_create(self, objs, *args, **kwargs):
        objs = list(objs)
        for obj in objs:
            stamp_message_step_no(obj)
        return super().bulk_create(objs, *args, **kwargs)


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
    retrieval = models.JSONField(null=True, blank=True)
    retrieval_skipped = models.CharField(max_length=32, blank=True, default="")

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

    # Nullable, database DEFAULT NULL. Main's Message insert omits this column
    # until that code is deployed. Do not default to 0 or 1.
    step_no = models.PositiveIntegerField(null=True, blank=True, db_default=None)

    objects = MessageManager()
    all_objects = MessageManager(alive_only=False)

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

    def save(self, *args, **kwargs):
        if self._state.adding:
            stamp_message_step_no(self)
        super().save(*args, **kwargs)


class TurnPrompt(SmartModel):
    """Exact model payload for one assistant reply. QA only."""

    id = CharIDField(primary_key=True, prefix="tpr_")

    message = models.OneToOneField(
        Message,
        related_name="turn_prompt",
        on_delete=models.CASCADE,
    )
    model_name = models.CharField(max_length=255, blank=True, default="")
    system_prompt = models.TextField(blank=True, default="")
    user_prompt = models.TextField(blank=True, default="")
    history = models.JSONField(default=list, blank=True)
    # db_default stays on the column. Main's TurnPrompt insert omits this
    # field until that code is deployed, and Postgres fills [].
    decisions = models.JSONField(blank=True, default=list, db_default=[])

    def __str__(self):
        return f"TurnPrompt: {self.id}"
