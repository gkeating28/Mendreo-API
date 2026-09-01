from django.urls import path

from .views import (
    Onboarding,
    OnboardingAnswers,
    OnboardingComplete,
    OnboardingFlow,
    OnboardingKnowledge,
    OnboardingRestart,
    OnboardingStatus,
)

urlpatterns = [
    path('', Onboarding.as_view()),
    path('/status', OnboardingStatus.as_view()),
    path('/flow', OnboardingFlow.as_view()),
    path('/answers', OnboardingAnswers.as_view()),
    path('/knowledge', OnboardingKnowledge.as_view()),
    path('/complete', OnboardingComplete.as_view()),
    path('/restart', OnboardingRestart.as_view()),
]
