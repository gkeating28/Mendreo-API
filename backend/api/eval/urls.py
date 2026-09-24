from django.urls import path

from .views import EvalRunList, EvalRunNow

urlpatterns = [
    path("/run", EvalRunNow.as_view()),
    path("/runs", EvalRunList.as_view()),
]
