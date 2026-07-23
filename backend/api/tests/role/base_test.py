from ...tests.TestCase import TestCase

from abc import ABC, abstractmethod

from rest_framework.test import APIClient
from rest_framework import status

from ...role.models import Role

from ...utils import Constants


def set_permissions(role, permission_key, view=False, create=False, edit=False, delete=False):
    """Helper function to set permissions on a role"""
    permissions = role.permissions
    permission_list = []

    if view:
        permission_list.append(Constants.PERMISSION_VIEW)
    if create:
        permission_list.append(Constants.PERMISSION_CREATE)
    if edit:
        permission_list.append(Constants.PERMISSION_EDIT)
    if delete:
        permission_list.append(Constants.PERMISSION_DELETE)

    setattr(permissions, permission_key, permission_list)
    permissions.save()


class RolePermissionsTests(TestCase, ABC):
    """Base test class for testing role-based permissions on resources"""

    client = APIClient()

    disable_view_owned_tests = False
    disable_view_all_tests = False

    disable_edit_owned_tests = False
    disable_edit_all_tests = False

    disable_create_tests = False

    disable_delete_owned_tests = False
    disable_delete_all_tests = False

    view_all_count = 2
    view_owned_count = 1

    def setUp(self):
        """Set up test environment with admins and roles"""
        from ..utils.manager.Auth import get_access_token, get_or_create_admin, get_or_create_consumer, create_admin

        self.super_admin = get_or_create_admin()
        self.super_admin_access_token = get_access_token(self.super_admin.user)

        from ...permissions.models import Permissions

        self.role = Role.objects.create(name="Test Role", is_default=False)
        Permissions.objects.create(
            role=self.role,
            users=[],
            sessions=[],
            signups=[],
            feedback=[],
            exercises=[],
            assets=[],
            questions=[],
            roles=[],
            pii=[]
        )

        self.admin_one = create_admin()
        self.admin_one.role = self.role
        self.admin_one.save()
        self.admin_one_access_token = get_access_token(self.admin_one.user)

        self.admin_two = create_admin()
        self.admin_two.role = self.role
        self.admin_two.save()
        self.admin_two_access_token = get_access_token(self.admin_two.user)

        self.consumer = get_or_create_consumer()


        self.owned_object = self._make_owned_object()
        self.owned_object_id = self._get_object_id(self.owned_object)

        self.non_owned_object = self._make_non_owned_object()
        self.non_owned_object_id = self._get_object_id(self.non_owned_object)

        self.objects = [self.owned_object, self.non_owned_object]


    def test_fail_view_with_no_view_permissions(self):
        if self.disable_view_owned_tests:
            return

        set_permissions(self.role, self._get_permission_key())
        object_response = self._list(self.admin_one_access_token)

        self.assertEqual(object_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_view_with_view_owned_permission(self):
        if self.disable_view_owned_tests:
            return

        set_permissions(self.role, self._get_permission_key(), view=True)
        object_response = self._list(self.admin_one_access_token)

        self.assertEqual(object_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(object_response.data["results"]), self.view_owned_count)

    def test_view_with_view_all_permission(self):
        if self.disable_view_all_tests:
            return

        set_permissions(self.role, self._get_permission_key(), view=True)
        object_response = self._list(self.admin_one_access_token)

        self.assertEqual(object_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(object_response.data["results"]), self.view_all_count)


    def test_fail_delete_owned_with_no_delete_permissions(self):
        if self.disable_delete_owned_tests:
            return

        set_permissions(self.role, self._get_permission_key())
        object_response = self._delete(self.owned_object_id, self.admin_one_access_token)

        self.assertEqual(object_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_fail_delete_non_owned_with_no_delete_permissions(self):
        if self.disable_delete_owned_tests:
            return

        set_permissions(self.role, self._get_permission_key())
        object_response = self._delete(self.non_owned_object_id, self.admin_one_access_token)

        self.assertEqual(object_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_owned_with_delete_owned_permissions(self):
        if self.disable_delete_owned_tests:
            return

        set_permissions(self.role, self._get_permission_key(), delete=True)
        object_response = self._delete(self.owned_object_id, self.admin_one_access_token)

        self.assertEqual(object_response.status_code, status.HTTP_204_NO_CONTENT)

    def test_delete_non_owned_with_delete_all_permissions(self):
        if self.disable_delete_all_tests:
            return

        set_permissions(self.role, self._get_permission_key(), delete=True)
        object_response = self._delete(self.non_owned_object_id, self.admin_one_access_token)

        self.assertEqual(object_response.status_code, status.HTTP_204_NO_CONTENT)

  
    def test_fail_edit_owned_with_no_edit_permissions(self):
        if self.disable_edit_owned_tests:
            return

        set_permissions(self.role, self._get_permission_key())
        object_response = self._patch(self.owned_object_id, self._edit_data(), self.admin_one_access_token)

        self.assertEqual(object_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_fail_edit_non_owned_with_no_edit_permissions(self):
        if self.disable_edit_owned_tests:
            return

        set_permissions(self.role, self._get_permission_key())
        object_response = self._patch(self.non_owned_object_id, self._edit_data(), self.admin_one_access_token)

        self.assertEqual(object_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_edit_owned_with_edit_owned_permissions(self):
        if self.disable_edit_owned_tests:
            return

        set_permissions(self.role, self._get_permission_key(), edit=True)
        object_response = self._patch(self.owned_object_id, self._edit_data(), self.admin_one_access_token)

        self.assertEqual(object_response.status_code, status.HTTP_200_OK)

    def test_edit_non_owned_with_edit_all_permissions(self):
        if self.disable_edit_all_tests:
            return

        set_permissions(self.role, self._get_permission_key(), edit=True)
        object_response = self._patch(self.non_owned_object_id, self._edit_data(), self.admin_one_access_token)

        self.assertEqual(object_response.status_code, status.HTTP_200_OK)


    def test_fail_create_with_no_create_permission(self):
        if self.disable_create_tests:
            return

        set_permissions(self.role, self._get_permission_key())
        object_response = self._post(self._create_data(), self.admin_one_access_token)

        self.assertEqual(object_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_with_create_permission(self):
        if self.disable_create_tests:
            return

        set_permissions(self.role, self._get_permission_key(), create=True)
        object_response = self._post(self._create_data(), self.admin_one_access_token)

        self.assertEqual(object_response.status_code, status.HTTP_201_CREATED)


    @abstractmethod
    def _make_owned_object(self):
        """Create an object owned by admin1"""
        pass

    @abstractmethod
    def _make_non_owned_object(self):
        """Create an object owned by admin2 or consumer"""
        pass

    @abstractmethod
    def _get_permission_key(self):
        """Return the permission key for this resource"""
        pass

    @abstractmethod
    def _get_endpoint(self):
        """Return the API endpoint for this resource"""
        pass

    def _get_object_id(self, object):
        """Get the ID of the object"""
        return object.id

    def _edit_data(self):
        """Return data for editing the object"""
        return {}

    def _create_data(self):
        """Return data for creating a new object"""
        return {}


    def _list(self, access_token="", query_params_dict=None):
        response = super()._get(
            f"/{self._get_endpoint()}",
            access_token=access_token,
            query_params_dict=query_params_dict
        )
        return response

    def _get(self, object_id, access_token="", query_params_dict=None):
        response = super()._get(
            f"/{self._get_endpoint()}/{object_id}",
            access_token=access_token,
            query_params_dict=query_params_dict
        )
        return response

    def _post(self, data, access_token="", query_params_dict=None):
        response = super()._post(
            f"/{self._get_endpoint()}",
            data,
            access_token=access_token,
            query_params_dict=query_params_dict
        )
        return response

    def _patch(self, id, data, access_token="", multipart=False):
        response = super()._patch(
            f"/{self._get_endpoint()}/{id}",
            data,
            access_token=access_token,
            multipart=multipart
        )
        return response

    def _delete(self, object_id, access_token="", data=None):
        response = super()._delete(
            f"/{self._get_endpoint()}/{object_id}",
            access_token=access_token,
            data=data
        )
        return response
