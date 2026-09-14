from django.urls import path

from .views import VoicePreview, VoiceToken, VoiceTts

urlpatterns = [
    path("/token", VoiceToken.as_view()),
    path("/tts", VoiceTts.as_view()),
    path("/preview", VoicePreview.as_view()),
]
