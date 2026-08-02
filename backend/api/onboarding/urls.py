from django.urls import path

from .views import Onboarding, OnboardingStatus, OnboardingFlow, OnboardingAnswers

urlpatterns = [
    path('', Onboarding.as_view()),
    path('/status', OnboardingStatus.as_view()),
    path('/flow', OnboardingFlow.as_view()),
    path('/answers', OnboardingAnswers.as_view()),
]
