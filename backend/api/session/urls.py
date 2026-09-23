from django.urls import path

from .views import (
    CompletePreExercise,
    Detail,
    Finish,
    List,
    Ready,
    Start,
    StartExercise,
    Summary,
    Today,
)

urlpatterns = [
    path('', List.as_view()),
    path('/today', Today.as_view()),
    path('/start', Start.as_view()),
    path('/<str:id>/complete-pre-exercise', CompletePreExercise.as_view()),
    path('/<str:id>/start', StartExercise.as_view()),
    path('/<str:id>/ready', Ready.as_view()),
    path('/<str:id>/finish', Finish.as_view()),
    path('/<str:id>', Detail.as_view()),
    path('/<str:id>/summary', Summary.as_view())
]
