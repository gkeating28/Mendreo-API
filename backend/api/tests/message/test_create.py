from freezegun import freeze_time

from ..utils import Data
from ..utils.BaseTest import ResponseError
from ..utils.CreateTest import CreateData, BaseCreateTest
from ..utils.manager import General, Auth
from ...utils import DateUtils


class CreateTest(BaseCreateTest):
    
    def setUp(self):
        super(CreateTest, self).setUp()
        self.session_one = General.create_session(consumer=self.consumer_one)
    
    def get_valid_create_data_variations_for_consumer(self, consumer) -> list[CreateData]:
        return [
            CreateData(
                request_data=Data.valid_message_data(
                    text='Hi',
                    consumer=consumer
                )
            ),
            CreateData(
                request_data=Data.valid_message_data(
                    text='Hi, I’ve been really stressed.',
                    consumer=consumer
                )
            ),
        ]
    
    def get_invalid_create_data_variations_for_consumer(self, consumer) -> list[CreateData]:
        
        # mock date to send message for past session
        with freeze_time(DateUtils.yesterday().date()):
            yesterday_session = General.create_session(consumer=consumer)
            yesterday_session.completed = True
            yesterday_session.save()
            
        message_data = Data.valid_message_data(
            text='Hi I am feeling sad today.',
            session=yesterday_session)
        
        # make use of today's session with different consumer
        different_consumer = Auth.create_consumer()
        
        return [
            CreateData(
                request_data=Data.valid_message_data(text=None, session=self.session_one),
                response_error=ResponseError(
                    key="text",
                    value="This field may not be null."
                )
            ),
            CreateData(
                request_data=Data.valid_message_data(
                    text='',
                    session=self.session_one
                ),
                response_error=ResponseError(
                    key="text",
                    value="This field may not be blank."
                )
            ),
            CreateData(
                request_data=message_data,
                response_error=ResponseError(
                    key="session",
                    value="Not allowed to send messages for past sessions."
                )
            ),
            CreateData(
                request_data=Data.valid_message_data(
                    text='Hi I am feeling sad today.',
                    consumer=different_consumer
                ),
                response_error=ResponseError(
                    key="consumer",
                    value="You are not a participant in this session."
                )
            )
        ]
    
    def get_valid_create_data_variations_for_admin(self, admin) -> list[CreateData]:
        return []
    
    def get_invalid_create_data_variations_for_admin(self, admin) -> list[CreateData]:
        return []
    
    
    def validate_create_response_data(self, create_data, response_json):
        self.assertEqual(self.consumer_one.agent.id, response_json['sender']['agent']['id'])
        self.assertIsNone( response_json['sender']['consumer'])
        
        # Check session update
        self.session_one.refresh_from_db()
        self.assertEqual(create_data['session'], response_json["session"])
        self.assertGreater(self.session_one.agent_messages_no, 0)
        self.assertGreater(self.session_one.messages_no, 0)
        self.assertEqual(self.session_one.last_message.text, response_json["text"])
        

    def endpoint(self):
        return "messages"
    
del BaseCreateTest