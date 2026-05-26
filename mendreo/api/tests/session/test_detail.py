from ..utils.DetailTest import BaseDetailTest

from ..utils import Data
from ..utils.manager import General
from ...utils.Agent import GeneralResponse


class DetailTest(BaseDetailTest):
    
    def setUp(self):
        super().setUp()
        
        mocked_bot_response = GeneralResponse(
            reasoning="Acknowledging the client's positive state and then gently inviting further conversation",
            text="Hi, How are you doing today?",
            suggested_responses=[
                "I'm okay.",
                "I'm doing well.",
                "Not so good."
            ],
            asset_id=None
        )
        
        self.session = General.create_session(consumer=self.consumer_one)
        message_one = General.create_message_with_mock_ai(
            data=Data.valid_message_data(
                text='Thank you!',
                session=self.session
            ),
            mocked_bot_response=mocked_bot_response,
            consumer=self.consumer_one
        )
        message_two = General.create_message_with_mock_ai(
            data=Data.valid_message_data(
                text='Your welcome.',
                session=self.session
            ),
            mocked_bot_response=mocked_bot_response,
            consumer=self.consumer_one
        )
        self.messages = message_one + message_two
    
    def get_object(self):
        return self.session
    
    def validate_detail_response_data(self, obj, user, response_json):
        self.assertEqual(response_json['last_message']['text'], self.messages[-1].text)
        self.assertEqual(response_json['last_message']['id'], self.messages[-1].id)
        self.assertEqual(response_json['messages_no'], len(self.messages))
        self.assertEqual(response_json['consumer_messages_no'], len(self.messages)/2)
        self.assertEqual(response_json['agent_messages_no'], len(self.messages)/2)

    def endpoint(self):
        return "sessions"


del BaseDetailTest
