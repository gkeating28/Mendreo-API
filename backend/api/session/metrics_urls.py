from django.urls import path

from .metrics_view import Metrics

urlpatterns = [
    path('', Metrics.as_view()),
]
