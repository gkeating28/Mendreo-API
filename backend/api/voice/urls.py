from django.urls import path

from .views import VoiceToken

urlpatterns = [
    path("/token", VoiceToken.as_view()),
]
