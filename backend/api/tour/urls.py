from django.urls import path

from .views import Tour, TourConfig, TourStepAudio

urlpatterns = [
    path('', Tour.as_view()),
    path('/config', TourConfig.as_view()),
    path('/steps/<str:step_id>/audio', TourStepAudio.as_view()),
]
