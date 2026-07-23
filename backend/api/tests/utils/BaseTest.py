from ...tests.TestCase import TestCase

from abc import ABC, abstractmethod

from types import SimpleNamespace

from rest_framework.test import APIClient
from rest_framework import status

from .manager import Auth

DEFAULT_ID_FIELD_NAME = "id"


class BaseTest(TestCase, ABC):

    client = APIClient()
    log_errors = False

    def setUp(self):
        self.admin_one = Auth.create_admin()
        self.admin_one_access_token = Auth.get_access_token(self.admin_one.user)

        self.consumer_one = Auth.create_consumer()
        self.consumer_one_access_token = Auth.get_access_token(self.consumer_one.user)

    @abstractmethod
    def endpoint(self):
        pass

    def get_id_field_name(self):
        return DEFAULT_ID_FIELD_NAME

    def get_id_for_object(self, object):
        id_field_name = self.get_id_field_name()
        return getattr(object, id_field_name)

    def get_object_id_from_data(self, object_data):
        id_field_name = self.get_id_field_name()

        _list = id_field_name.split("_")

        for item in _list:
            if item in object_data:
                object_data = object_data[item]

        return object_data

    def get_consumer(self):
        return None

    def get_consumer_access_token(self):
        consumer = self.get_consumer()

        if not consumer:
            return None

        return Auth.get_access_token(consumer.user)

    def get_permission_key(self):
        return None

    def get_object_with_invalid_id(self):
        return SimpleNamespace(**{self.get_id_field_name(): "999"})

    def get_endpoint_for_object(self, object):
        return f"/{self.endpoint()}/{self.get_id_for_object(object)}"

    def _list(self, access_token="", query_params_dict={}):
        response = super()._get(f"/{self.endpoint()}", access_token=access_token, query_params_dict=query_params_dict)

        if response.status_code != status.HTTP_200_OK and self.log_errors:
            print(response.json)

        return response

    def _create(self, data, access_token=""):
        response = super()._post(f"/{self.endpoint()}", data, access_token=access_token)

        if response.status_code != status.HTTP_201_CREATED and self.log_errors:
            print(response.json)

        return response

    def _bulk_create(self, data, access_token=""):
        response = super()._put(f"/{self.endpoint()}", data, access_token=access_token)

        if response.status_code != status.HTTP_200_OK and self.log_errors:
            print(response.json)

        return response

    def _get(self, object, access_token=""):
        response = super()._get(self.get_endpoint_for_object(object), access_token=access_token)

        if response.status_code != status.HTTP_200_OK and self.log_errors:
            print(response.json)

        return response

    def _update(self, object, data, access_token=""):
        response = super()._patch(self.get_endpoint_for_object(object), data, access_token=access_token)

        if response.status_code != status.HTTP_200_OK and self.log_errors:
            print(response.json)

        return response

    def _delete(self, object, access_token=""):
        response = super()._delete(self.get_endpoint_for_object(object), access_token=access_token)

        if response.status_code != status.HTTP_204_NO_CONTENT and self.log_errors:
            print(response.json)

        return response

    def warn(self, error):
        print(self._testMethodName, f"\033[93m{error}\x1b[0m")


class ResponseError:
    def __init__(self, key: str | None, value: str | None, status_code: int = 400):
        self.key = key
        self.value = value
        self.status_code = status_code


class CreateData:
    def __init__(self, request_data: dict, response_code: int = status.HTTP_201_CREATED, response_error: ResponseError = None):
        self.request_data = request_data
        self.response_code = response_code
        self.response_error = response_error
        if response_error:
            self.response_code = response_error.status_code


class BulkCreateData:
    def __init__(self, request_data: [], response_code: int = status.HTTP_201_CREATED, response_error: ResponseError = None):
        self.request_data = request_data
        self.response_code = response_code
        self.response_error = response_error
        if response_error:
            self.response_code = response_error.status_code


class EditData:
    def __init__(self, request_data: dict, response_code: int = status.HTTP_200_OK, response_error: ResponseError = None, request_object: object = None):
        self.request_data = request_data
        self.response_code = response_code
        self.response_error = response_error
        self.request_object = request_object
        if response_error:
            self.response_code = response_error.status_code


class QueryParamsData:
    def __init__(self, query_params: dict, results_no=0, results_match_data=[], response_code: int = status.HTTP_200_OK, response_error: ResponseError = None):
        self.query_params = query_params
        self.results_no = results_no
        self.results_match_data = results_match_data
        self.response_code = response_code
        self.response_error = response_error
        if response_error:
            self.response_code = response_error.status_code
