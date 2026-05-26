from rest_framework import permissions

from ..utils import Constants


# Allow web browsers to query authenticated endpoints for OPTIONS without passing in authentication headers
class IsAuthenticated(permissions.IsAuthenticated):

    def has_permission(self, request, view):
        if request.method == 'OPTIONS':
            return True
        return super(IsAuthenticated, self).has_permission(request, view)


class IsAdminPermission(permissions.BasePermission):
    message = "Only admin accounts are able to access this"

    def has_permission(self, request, view):
        if request.user.is_anonymous:
            return False

        return request.user.type == Constants.USER_TYPE_ADMIN


class IsConsumerPermission(permissions.BasePermission):
    message = "Only consumer accounts are able to access this"

    def has_permission(self, request, view):
        if request.user.is_anonymous:
            return False

        return request.user.type == Constants.USER_TYPE_CONSUMER

