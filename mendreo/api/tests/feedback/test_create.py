from ..utils.manager import General
from ..utils.CreateTest import BaseCreateTest, CreateData
from ..utils.BaseTest import ResponseError

from rest_framework import status


class CreateTest(BaseCreateTest):

    def get_valid_create_data_variations_for_consumer(self, consumer) -> [CreateData]:
        return [
            CreateData(
                request_data={
                    "value": "I really like the app and feel its helping me overcome a really tough situation, thank you"
                },
            ),
        ]

    def get_invalid_create_data_variations_for_consumer(self, consumer) -> [CreateData]:
        session = General.start_session(consumer=consumer)
        message = General.create_message(
            consumer=consumer,
            data={
                "text": "Hello",
                "session": session.id
            }
        )

        data = {
            "message": message.id,
            "positive": True,
            "reason": "Very helpful response!"
        }

        return [
            CreateData(
                request_data=data,
                response_error=ResponseError(
                    key="value",
                    value="This field is required.",
                )
            ),
        ]

    def get_valid_create_data_variations_for_admin(self, admin) -> [CreateData]:
        consumer = self.get_consumer()
        session = General.start_session(consumer=consumer)
        message = General.create_message(
            consumer=consumer,
            data={
                "text": "Hello",
                "session": session.id
            }
        )

        data_with_reason = {
            "message": message.id,
            "positive": True,
            "reason": "Very helpful response!"
        }

        message_2 = General.create_message(
            consumer=consumer,
            data={
                "text": "Hello again",
                "session": session.id
            }
        )

        data_without_reason = {
            "message": message_2.id,
            "positive": False,
        }

        return [
            CreateData(
                request_data=data_with_reason,
            ),
            CreateData(
                request_data=data_without_reason,
            ),
        ]

    def get_invalid_create_data_variations_for_admin(self, admin) -> [CreateData]:
        consumer = self.get_consumer()
        session = General.start_session(consumer=consumer)
        message = General.create_message(
            consumer=consumer,
            data={
                "text": "Hello",
                "session": session.id
            }
        )

        return [
            CreateData(
                request_data={
                    "message": "invalid_id",
                    "positive": True,
                    "reason": "Test"
                },
                response_error=ResponseError(
                    key="message",
                    value="Invalid pk \"invalid_id\" - object does not exist.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            ),
            CreateData(
                request_data={
                    "message": message.id
                },
                response_error=ResponseError(
                    key="positive",
                    value="This field is required.",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            ),
        ]

    def validate_create_response_data(self, create_data, response_json):
        self.assertTrue(response_json["id"].startswith("fdbk_"))

        if "value" in create_data:
            self.assertEqual(create_data["value"], response_json["value"])

        if "message" in create_data:
            self.assertEqual(create_data["message"], response_json["message"])
            self.assertEqual(create_data["positive"], response_json["positive"])

        if "reason" in create_data:
            self.assertEqual(create_data["reason"], response_json["reason"])

    def endpoint(self):
        return "feedback"


del BaseCreateTest
