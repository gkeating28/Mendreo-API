from django.urls import path

from .views import (
    SourceApprove,
    SourceChunks,
    SourceDetail,
    SourceListCreate,
    SourceReindex,
    SourceSearch,
    SourceSubmit,
)

urlpatterns = [
    path("sources", SourceListCreate.as_view()),
    path("sources/<str:id>", SourceDetail.as_view()),
    path("sources/<str:id>/submit", SourceSubmit.as_view()),
    path("sources/<str:id>/approve", SourceApprove.as_view()),
    path("sources/<str:id>/reindex", SourceReindex.as_view()),
    path("sources/<str:id>/chunks", SourceChunks.as_view()),
    path("search", SourceSearch.as_view()),
]
