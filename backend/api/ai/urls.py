from django.urls import path

from .views import Create

urlpatterns = [
    path('', Create.as_view()),
]
