from django.urls import path

from .views import CheckIns, Mood, Exercises, Patterns, Streaks

urlpatterns = [
    path("/mood", Mood.as_view()),
    path("/exercises", Exercises.as_view()),
    path("/patterns", Patterns.as_view()),
    path("/streaks", Streaks.as_view()),
    path("/check-ins", CheckIns.as_view()),
]
