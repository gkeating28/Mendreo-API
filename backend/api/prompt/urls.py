from django.urls import path

from .views import PromptActivate, PromptVersions

urlpatterns = [
    path("/<str:key>/versions", PromptVersions.as_view()),
    path("/<str:key>/versions/<int:version>/activate", PromptActivate.as_view()),
]
