from django.urls import path

from .views import RunDetail, RunList, RunReflection

urlpatterns = [
    path("", RunList.as_view()),
    path("/<str:id>", RunDetail.as_view()),
    path("/<str:id>/reflections/<str:step_id>", RunReflection.as_view()),
]
