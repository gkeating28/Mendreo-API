from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from rest_framework.test import APIClient
from rest_framework.response import Response


def multipart_patch(endpoint, data, **kwargs) -> Response:
    # multipart patch isn't supported yet
    encoded = encode_multipart(BOUNDARY, data)

    response = APIClient().patch(
        endpoint,
        encoded,
        content_type=MULTIPART_CONTENT,
        **kwargs)

    return response
