from django.urls import path

from .views import (
    ListCreate,
    Detail,
    DuplicateExerciseView,
    TestPreExercisePrompt,
    ExerciseTokens,
)

urlpatterns = [
    path('', ListCreate.as_view()),
    path('/duplicate', DuplicateExerciseView.as_view()),
    path('/<str:id>/test-pre-exercise-prompt', TestPreExercisePrompt.as_view()),
    path('/<str:id>/tokens', ExerciseTokens.as_view()),
    path('/<str:id>', Detail.as_view())
]
