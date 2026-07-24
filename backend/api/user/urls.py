from django.urls import path, include

from .views import (
    Login,
    Logout,
    Refresh,
    Info,
    RequestPasswordReset,
    ResetPassword,
    RequestVerifyEmail,
    VerifyEmail,
    FacebookCode
)

urlpatterns = [
    path('/login', Login.as_view()),
    path('/login/', include('rest_social_auth.urls_jwt_pair')),
    path('/facebook-code', FacebookCode.as_view()),
    path('/logout', Logout.as_view()),
    path('/refresh-token', Refresh.as_view()),
    path('/info', Info.as_view()),
    path('/request-reset-password', RequestPasswordReset.as_view()),
    path('/reset-password', ResetPassword.as_view()),
    path("/request-verify-email", RequestVerifyEmail.as_view()),
    path("/verify-email", VerifyEmail.as_view()),
]