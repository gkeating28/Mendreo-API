from django.urls import path

from .views import Onboarding

urlpatterns = [
    path('', Onboarding.as_view()),
]
