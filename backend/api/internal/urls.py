from django.urls import path

from .elevenlabs_views import ElevenLabsChatCompletions, ElevenLabsPostCallWebhook
from .views import (
    CheckSubscriptionsCron,
    IndexKnowledgeSource,
    MessageResponse,
    SessionGreeting,
)

urlpatterns = [
    path("ai/message-response", MessageResponse.as_view()),
    path("ai/session-greeting", SessionGreeting.as_view()),
    path("knowledge/index", IndexKnowledgeSource.as_view()),
    path("cron/check-subscriptions", CheckSubscriptionsCron.as_view()),
    path("elevenlabs/v1/chat/completions", ElevenLabsChatCompletions.as_view()),
    path("elevenlabs/webhook", ElevenLabsPostCallWebhook.as_view()),
]
