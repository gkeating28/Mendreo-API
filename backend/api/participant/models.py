from django.db import models

from ..utils.Fields import CharIDField
from ..utils.Models import SmartModel


class Participant(SmartModel):
    id = CharIDField(primary_key=True, prefix="ptcp_")
    
    consumer = models.ForeignKey("api.Consumer", related_name="participants", null=True, on_delete=models.CASCADE)
    agent = models.ForeignKey("api.Agent", related_name="participants", null=True, on_delete=models.CASCADE)
    session = models.ForeignKey("api.Session", related_name="participants", on_delete=models.CASCADE)

    class Meta:
        indexes = [
            models.Index(fields=["session", "consumer"], name="participant_session_cons_idx"),
            models.Index(fields=["session", "agent"], name="participant_session_agent_idx"),
        ]
    
    def __str__(self):
        """Return a human-readable representation of the model instance."""
        return "Participant: {}".format(self.id)

    @staticmethod
    def create_participants(session):
        consumer_participant = Participant.objects.create(consumer=session.consumer, session=session)
        agent_participant = Participant.objects.create(agent=session.consumer.agent, session=session)

        return consumer_participant, agent_participant
