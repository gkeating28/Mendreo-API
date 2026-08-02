from django.urls import path

from .views import QuestionDetail, QuestionListCreate, QuestionTestExtraction

urlpatterns = [
    path("", QuestionListCreate.as_view()),
    path("/<str:id>", QuestionDetail.as_view()),
    path("/<str:id>/test-extraction", QuestionTestExtraction.as_view()),
]
