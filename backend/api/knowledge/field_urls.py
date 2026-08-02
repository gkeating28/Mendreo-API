from django.urls import path

from .views import FieldDetail, FieldListCreate

urlpatterns = [
    path("", FieldListCreate.as_view()),
    path("/<str:id>", FieldDetail.as_view()),
]
