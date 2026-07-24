from django.urls import path

from .views import CheckSubscriptionsCron, MessageResponse, SessionGreeting

urlpatterns = [
    path("ai/message-response", MessageResponse.as_view()),
    path("ai/session-greeting", SessionGreeting.as_view()),
    path("cron/check-subscriptions", CheckSubscriptionsCron.as_view()),
]
