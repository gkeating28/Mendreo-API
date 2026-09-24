from django.urls import path

from .views import EntryAccept, EntryBulkAccept, EntryDetail, EntryListCreate, EntryReject

urlpatterns = [
    path("", EntryListCreate.as_view()),
    path("/accept", EntryBulkAccept.as_view()),
    path("/<str:id>/accept", EntryAccept.as_view()),
    path("/<str:id>/reject", EntryReject.as_view()),
    path("/<str:id>", EntryDetail.as_view()),
]
