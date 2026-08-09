from django.urls import path

from .views import Detail, ListCreate

urlpatterns = [
    path("", ListCreate.as_view()),
    path("/<str:id>", Detail.as_view()),
]
