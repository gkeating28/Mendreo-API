from django.urls import path

from .views import ListCreate, Detail, DuplicateExerciseView, TestPreExercisePrompt

urlpatterns = [
    path('', ListCreate.as_view()),
    path('/duplicate', DuplicateExerciseView.as_view()),
    path('/<str:id>/test-pre-exercise-prompt', TestPreExercisePrompt.as_view()),
    path('/<str:id>', Detail.as_view())
]
