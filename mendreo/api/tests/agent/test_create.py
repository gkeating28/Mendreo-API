from ..utils import Data
from ..utils.manager import General
from ..utils.CreateTest import BaseCreateTest, CreateData

from ..utils.BaseTest import ResponseError

from rest_framework import status


class CreateTest(BaseCreateTest):

    def get_valid_create_data_variations_for_consumer(self, consumer) -> [CreateData]:
        # consumer not allowed to create agents
        return []

    def get_invalid_create_data_variations_for_consumer(self,  consumer) -> [CreateData]:
        return [
            CreateData(
                request_data={},
                response_error=ResponseError(
                    key="detail",
                    value="You do not have permission to access this",
                    status_code=status.HTTP_403_FORBIDDEN
                )
            ),
        ]

    def get_valid_create_data_variations_for_admin(self, admin) -> [CreateData]:
        return [
            CreateData(
                request_data=Data.valid_agent_data(),
            ),
        ]

    def get_invalid_create_data_variations_for_admin(self,  admin) -> [CreateData]:
        return [
            CreateData(
                request_data={},
                response_error=ResponseError(key="name", value="This field is required.")
            ),
            CreateData(
                request_data={"name": "Name", "description": "description"},
                response_error=ResponseError(key="avatar", value="This field is required.")
            ),

            CreateData(
                request_data={"name": "Name", "avatar": General.create_image().id },
                response_error=ResponseError(key="description", value="This field is required.")
            ),
            CreateData(
                request_data=Data.valid_agent_data(name=""),
                response_error=ResponseError(key="name", value="This field may not be blank.")
            ),
        ]

    def endpoint(self):
        return "agents"


del BaseCreateTest
