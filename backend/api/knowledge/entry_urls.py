from django.urls import path

from .views import EntryDetail, EntryListCreate

urlpatterns = [
    path("", EntryListCreate.as_view()),
    path("/<str:id>", EntryDetail.as_view()),
]
