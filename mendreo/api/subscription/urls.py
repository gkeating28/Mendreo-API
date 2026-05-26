from django.urls import path

from .views import Detail

urlpatterns = [
    path('/<str:id>', Detail.as_view())
]
