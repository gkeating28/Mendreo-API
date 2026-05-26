from django.urls import path

from .views import ListCreate, Detail, DuplicateExerciseView

urlpatterns = [
    path('', ListCreate.as_view()),
    path('/duplicate', DuplicateExerciseView.as_view()),
    path('/<str:id>', Detail.as_view())
]
