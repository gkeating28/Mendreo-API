import uuid

from rest_framework import status
from rest_framework.response import Response

from .Auth import get_access_token, get_consumer_access_token, get_platform_admin_access_token, get_or_create_admin
from .Request import post, patch, get

from ....tag.models import Tag
from ....admin.models import Admin
from ....agent.models import Agent
from ....attribute.models import Attribute
from ....consumer.models import Consumer
from ....currency.models import Currency
from ....event.models import Event
from ....file.models import File
from ....image.models import Image
from ....message.models import Message
from ....package.models import Package
from ....participant.models import Participant
from ....post.models import Post
from ....question.models import Question
from ....session.models import Session
from ....exercise.models import Exercise
from ....user.models import User

from ...utils import Data
from ....utils.Agent import GeneralResponse, ExerciseResponse


def setup_db():
    from ....role.models import Role
    from ....setting.models import Setting

    Setting.create_all()
    Role.create_defaults()

    if Agent.objects.first() is None:
        create_initial_agent()

    if Currency.objects.first() is None:
        create_currency()

    if Package.objects.first() is None:
        create_packages()


def create_initial_agent():
    if Agent.objects.exists():
        return

    return create_agent()


def create_currency(name="EURO", symbol="€", iso_code="4317", code="eur"):

    currency, created = Currency.objects.get_or_create(
        name=name,
        symbol=symbol,
        iso_code=iso_code,
        code=code
    )

    return currency


def create_packages():
    default_package = create_package(data=Data.valid_package_data(title="Free"))

    default_package.price.amount = 0
    default_package.price.save()

    default_package.default = True
    default_package.save()

    paid_package = create_package(data=Data.valid_package_data(title="Paid"))

    paid_package.price.apple_id = "test2"
    paid_package.price.google_id = "test2"
    paid_package.price.save()


def create_package(data: dict = None):
    if not data:
        data = Data.valid_package_data()

    return Package.objects.create(**data)


def create_agent(data: dict = None, admin: Admin = None, object_response: bool = True) -> Agent | Response:

    if not data:
        data = Data.valid_agent_data()

    response = post(
        "/agents",
        data,
        access_token=get_platform_admin_access_token(admin)
    )

    if not object_response:
        return response

    return Agent.objects.get(id=response.json["id"])


def create_image(access_token: str = None, data: dict = None, object_response: bool = True, mock: bool = False,
                 set_as_uploaded: bool = True) -> Image | Response:
    if mock is False:
        if not access_token:
            access_token = get_platform_admin_access_token()

        if not data:
            data = Data.valid_image_data()

        response = post("/images", data, access_token)
        
        response_json = response.json

        if not object_response:
            return response_json

        image = Image.objects.get(id=response_json["image"]["id"])
        upload_to_s3(response_json["pre_signed_url"], data["name"])
        image.uploaded = set_as_uploaded
        image.name = f"{str(uuid.uuid4())[:2]}{image.name}"
        image.save()
    else:
        name = "mock.jpg"

        if data and data["name"]:
            name = data["name"]

        image = Image.objects.create(
            name=name,
            original="mock-image-url.ie",
            width=200,
            height=200,
            user=get_or_create_admin().user,
            uploaded=set_as_uploaded
        )

    return image


def create_session(consumer: Consumer = None, exercise: Exercise = None, object_response: bool = True) -> Session | Response:

    url = f"/sessions/start"
    if exercise:
        url += f"?exercise_id={exercise.id}"

    response = get(
        url,
        access_token=get_consumer_access_token(consumer=consumer)
    )

    if not object_response:
        return response

    return Session.objects.get(id=response.json["id"])


def start_session(consumer: Consumer = None, exercise: Exercise | None = None, object_response: bool = True) -> Session | Response:

    endpoint = f"/sessions/start"
    if exercise:
        endpoint += f"?exercise_id={exercise.id}"

    response = get(
        endpoint,
        access_token=get_consumer_access_token(consumer=consumer)
    )

    if not object_response:
        return response

    return Session.objects.get(id=response.json["id"])


def create_message(data: dict = None, consumer: Consumer = None, object_response: bool = True) -> Message | Response:

    if data is None:
        data = Data.valid_message_data()
    
    response = post(
        "/messages",
        data,
        access_token=get_consumer_access_token(consumer)
    )

    if not object_response:
        return response

    return Message.objects.get(id=response.json["id"])


def create_message_with_mock_ai(consumer: Consumer, data: dict = None, mocked_bot_response = None) -> list[Message]:
    from unittest import mock
    from unittest.mock import MagicMock
    
    if data is None:
        data = Data.valid_message_data()
    
    with mock.patch('api.utils.Agent.get_response') as get_agent_response:
        get_agent_response.return_value = mocked_bot_response, {}, None, None

        response = post(
            "/messages",
            data,
            access_token=get_consumer_access_token(consumer)
        )
        
        consumer_participant = Participant.objects.filter(
            session__id=data['session'],
            agent__isnull=True,
            consumer=consumer
        ).first()

        consumer_message = Message.objects.filter(sender=consumer_participant, session__id=data['session']).last()
        agent_message = Message.objects.get(id=response.json["id"])

    return [consumer_message, agent_message]


def create_exercise(data: dict = None, object_response: bool = True) -> Exercise | Response:

    if not data:
        data = Data.valid_exercise_flexible_thinking()

    response = post(
        "/exercises",
        data,
        access_token=get_platform_admin_access_token()
    )

    if not object_response:
        return response

    return Exercise.objects.get(id=response.json["id"])


def create_post(data: dict = None, admin: Admin = None, object_response: bool = True) -> Post | Response:

    if not data:
        data = Data.valid_post_data()

    response = post(
        "/posts",
        data,
        access_token=get_platform_admin_access_token(admin)
    )

    if not object_response:
        return response

    return Post.objects.get(id=response.json["id"])


def create_tag(name: str = "Tag", admin: Admin = None, object_response: bool = True) -> Post | Response:

    response = post(
        "/tags",
        data={"name": name},
        access_token=get_platform_admin_access_token(admin)
    )

    if not object_response:
        return response

    return Tag.objects.get(id=response.json["id"])


def create_view_event(consumer: Consumer) -> Event | Response:

    post = create_post()

    event = Event.create_view(
            consumer=consumer,
            post=post
        )

    return event


def get_unuploaded_image():
    image = create_image(mock=True)
    image.uploaded = False
    image.save()

    return image


def create_file(name: str = None, set_as_uploaded: bool = True, object_response: bool = True, mock: bool = False,
                user: User = None) -> File | Response:

    if not user:
        user = get_or_create_admin().user

    access_token = get_access_token(user)

    if not mock:
        data = Data.valid_file_data(name)

        response = post(
            '/files',
            data=data,
            access_token=access_token
        )

        if response.status_code != status.HTTP_201_CREATED:
            raise Exception(f"Unexpected Error: {response.content}")

        if object_response:
            file = File.objects.get(id=response.json["file"]["id"])
            file.uploaded = set_as_uploaded
            file.save()

            return file

        return response

    if not name:
        name = "mock.pdf"

    file = File.objects.create(
        name=name,
        extension="pdf",
        content_type="pdf",
        url="mock-pdf-url.ie",
        size="1mb",
        duration=100,
        uploaded=set_as_uploaded,
        created_by=user
    )

    return file


def upload_file(file_name: str) -> File:
    response = create_file(file_name, object_response=False)

    pre_signed_url = response.json["pre_signed_url"]

    upload_to_s3(pre_signed_url, file_name)

    return File.objects.get(id=response.json["file"]["id"])


def upload_to_s3(pre_signed_url, file_name) -> Response:
    file = open(f"api/tests/utils/files/{file_name}", 'rb')

    import requests

    response = requests.put(pre_signed_url, file)

    return response


def create_question(data: dict = None, admin: Admin = None, object_response: bool = True) -> Question | Response:

    if not data:
        data = Data.valid_question_data()

    response = post(
        "/questions",
        data,
        access_token=get_platform_admin_access_token(admin)
    )

    if not object_response:
        return response

    return Question.objects.get(id=response.json["id"])


def create_attribute(question: Question = None, value: str = "1", consumer: Consumer = None, object_response: bool = True) -> Attribute | Response:

    if not question:
        question = create_question()

    data = {
        "question": question.id,
        "value": value,
    }

    response = post(
        "/attributes",
        data,
        access_token=get_consumer_access_token(consumer)
    )

    if not object_response:
        return response

    return Attribute.objects.get(id=response.json["id"])


def subscribe_to_paid_package(consumer: Consumer, method: str = "in_app_apple"):
    paid_package = Package.objects.get(title="Paid")

    return subscribe_to_package(consumer, paid_package, method)


def subscribe_to_package(consumer: Consumer, package: Package, method: str = "in_app_apple"):

    data = Data.valid_subscription_data(package, method=method)

    return patch(
        f"/subscriptions/{consumer.user_id}",
        data,
        access_token=get_access_token(consumer.user)
    )
