from django.urls import path

from .views import (
    CheckIns,
    Insights,
    InsightsRefresh,
    InsightsStart,
    Mood,
    Exercises,
    Observation,
    Patterns,
    Streaks,
)

urlpatterns = [
    path("/mood", Mood.as_view()),
    path("/exercises", Exercises.as_view()),
    path("/patterns", Patterns.as_view()),
    path("/streaks", Streaks.as_view()),
    path("/check-ins", CheckIns.as_view()),
    path("/observations/<str:id>", Observation.as_view()),
    path("/insights", Insights.as_view()),
    path("/insights/refresh", InsightsRefresh.as_view()),
    path("/insights/<str:id>/start", InsightsStart.as_view()),
]
