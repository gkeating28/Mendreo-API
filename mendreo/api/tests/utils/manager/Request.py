from rest_framework.test import APIClient
from rest_framework.response import Response


client = APIClient()


def post(endpoint, data=None, access_token="", multipart=False) -> Response:
    if data is None:
        data = {}
    from ....tests.TestCase import TestCase
    response = TestCase._post(endpoint, data, access_token, multipart)
    return response


def put(endpoint, data=None, access_token="", multipart=False) -> Response:
    if data is None:
        data = {}
    from ....tests.TestCase import TestCase
    response = TestCase._put(endpoint, data, access_token, multipart)
    return response


def get(endpoint, access_token="") -> Response:
    from ....tests.TestCase import TestCase
    response = TestCase._get(endpoint, access_token=access_token)
    return response


def patch(endpoint, data=None, access_token="") -> Response:
    if data is None:
        data = {}

    from ....tests.TestCase import TestCase
    response = TestCase._patch(endpoint, data, access_token)
    return response


def delete(endpoint, access_token="") -> Response:
    from ....tests.TestCase import TestCase
    response = TestCase._delete(endpoint, access_token=access_token)
    return response


