from django.urls import path

from .views import AuditList, Detail, ListCreate, SetDefault

urlpatterns = [
    path("", ListCreate.as_view()),
    path("/audit", AuditList.as_view()),
    path("/<str:id>", Detail.as_view()),
    path("/<str:id>/set-default", SetDefault.as_view()),
]
