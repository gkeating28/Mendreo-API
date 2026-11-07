from django.urls import path

from .views import (
    InviteCodeListCreate,
    InviteCodeReactivate,
    InviteCodeReset,
    InviteCodeRevoke,
    Redeem,
)

urlpatterns = [
    path("/redeem", Redeem.as_view()),
    path("", InviteCodeListCreate.as_view()),
    path("/<str:id>/revoke", InviteCodeRevoke.as_view()),
    path("/<str:id>/reactivate", InviteCodeReactivate.as_view()),
    path("/<str:id>/reset", InviteCodeReset.as_view()),
]
