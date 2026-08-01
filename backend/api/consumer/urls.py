from django.urls import path

from .views import ListCreate, Detail
from ..knowledge.consumer_views import (
    ConsumerKnowledgeActivity,
    ConsumerKnowledgeFieldHistory,
    ConsumerKnowledgeProfile,
)

urlpatterns = [
    path('', ListCreate.as_view()),
    path('/<str:id>/knowledge/activity', ConsumerKnowledgeActivity.as_view()),
    path('/<str:id>/knowledge/fields/<str:field_id>/history', ConsumerKnowledgeFieldHistory.as_view()),
    path('/<str:id>/knowledge', ConsumerKnowledgeProfile.as_view()),
    path('/<str:id>', Detail.as_view()),
]
