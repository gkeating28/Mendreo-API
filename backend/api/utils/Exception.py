from rest_framework.exceptions import APIException
from rest_framework import status


class CustomValidation(APIException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = {"detail": 'A server error occurred.'}

    def __init__(self, data, status_code):
        if status_code is not None:
            self.status_code = status_code

        if data is not None:
            self.detail = data


class SCAChallengeException(CustomValidation):

    def __init__(self, data):
        super(SCAChallengeException, self).__init__(data, status.HTTP_200_OK)


def raise_error(data, status_code=400):
    raise CustomValidation(data, status_code)


def raise_sca_error(data):
    raise SCAChallengeException(data)


class ShopifyException(CustomValidation):
    key: str
    error: str

    def __init__(self, key, error):
        self.key = key
        self.error = error

        super().__init__({key: error}, status.HTTP_400_BAD_REQUEST)

