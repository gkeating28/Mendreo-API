from django.urls import path

from .views import VoiceToken, VoiceTts

urlpatterns = [
    path("/token", VoiceToken.as_view()),
    path("/tts", VoiceTts.as_view()),
]
