from django.urls import path

from .views import ListCreate, MessageDebug, MessagePrompt

urlpatterns = [
    path('', ListCreate.as_view()),
    path('/<str:id>/prompt', MessagePrompt.as_view()),
    path('/<str:id>/debug', MessageDebug.as_view()),
]
