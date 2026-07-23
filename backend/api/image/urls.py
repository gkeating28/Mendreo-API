from django.urls import path

from .views import Create, Edit

urlpatterns = [
    path('', Create.as_view()),
    path('/<str:id>', Edit.as_view()),
]
