import uuid

from rest_framework.response import Response
from rest_framework import status
from .views import get_detailed

from ..utils import Constants, Token, IP


# gets/creates a customer from the social details provided by the pipeline
def create_client(strategy, details, *args, **kwargs):

    details["ip_address"] = IP.get_client_ip(strategy.request)
    customer = get_or_create_customer(details)

    response = {
        "user": customer.user
    }

    print("Create Social Client: ", details, customer, kwargs)
    # weird instagram bug
    if kwargs["uid"] is None:
        response["uid"] = customer.user_id

    return response


# send back authentication details at end of pipeline to emulate
# traditional/standard login
def send_details(strategy, details, user, *args, **kwargs):
    data = get_detailed(user)
    data[Constants.USER_AUTH_TOKENS] = Token.create(user)

    return Response(data=data, status=status.HTTP_200_OK)


def get_or_create_customer(details):
    from ..consumer.serializers import ConsumerSocialCreateSerializer, Consumer
    email = details['email']

    consumer = Consumer.objects.filter(user__email__iexact=email).first()

    if consumer:
        return consumer

    details['password'] = str(uuid.uuid4())
    details["social_login"] = True

    # todo get actual DOB
    data = {
        "user": details,
        "date_of_birth": details.get("date_of_birth", "2000-01-01")
    }

    serializer = ConsumerSocialCreateSerializer(data=data)
    serializer.is_valid(raise_exception=True)

    try:
        customer = serializer.save()
    except Exception as e:
        raise e

    return customer
