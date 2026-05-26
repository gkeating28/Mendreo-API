from django.urls import path

from .views import Survey

urlpatterns = [
    path('', Survey.as_view()),
]