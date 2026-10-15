from django.urls import path

from .views import ListCreate, MessagePrompt

urlpatterns = [
    path('', ListCreate.as_view()),
    path('/<str:id>/prompt', MessagePrompt.as_view()),
]
