from django.urls import path

from .views import Detail, Today, List, Start, Summary, CompletePreExercise

urlpatterns = [
    path('', List.as_view()),
    path('/today', Today.as_view()),
    path('/start', Start.as_view()),
    path('/<str:id>/complete-pre-exercise', CompletePreExercise.as_view()),
    path('/<str:id>', Detail.as_view()),
    path('/<str:id>/summary', Summary.as_view())
]
