from freezegun import freeze_time
from rest_framework import status

from ..utils.ListTest import BaseListTest, QueryParamsData
from ..utils.manager import General, Auth
from ...consumer.models import Consumer
from ...message.models import Message
from ...participant.models import Participant
from ...session.models import Session
from ...utils import DateUtils


class ListTest(BaseListTest):
    
    def setUp(self):
        self.admin_one = Auth.create_admin()
        self.admin_one_access_token = Auth.get_access_token(self.admin_one.user)
        
        # consumer one session one
        self.consumer_one = Auth.create_consumer()
        self.consumer_one_access_token = Auth.get_access_token(self.consumer_one.user)
        self.session = General.create_session(consumer=self.consumer_one)
        
        self.objects = self.get_objects()
        self.consumer_one_msg_ids = [{'id': obj.id} for obj in self.objects]
        
        # consumer one yesterday's session
        with freeze_time(DateUtils.yesterday(), tick=True):
            self.yesterday_session = General.create_session(consumer=self.consumer_one)
            yesterday_messages = self.create_messages(message_data=self.get_sample_data()[:2],
                                                      session=self.yesterday_session, consumer=self.consumer_one)
            self.yesterday_msg_ids = [{'id': obj.id} for obj in yesterday_messages]
        
        self.consumer_two = Auth.create_consumer()
        self.session_two = General.create_session(consumer=self.consumer_two)
        consumer_two_msgs = self.create_messages(message_data=self.get_sample_data()[:1], session=self.session_two,
                                                 consumer=self.consumer_two)
        self.consumer_two_msg_ids = [{'id': obj.id} for obj in consumer_two_msgs]

    def get_sample_data(self):
        # [{consumer_msg: ai_response}, ...]
        return [{"Hi": {"text":"Hi, How are you doing today?",
                        "suggested_responses":["I'm okay.", "I'm doing well.", "Not so good."]}},
                
                {"Not so good.": {"text":"I hear that, It sounds like you're having a difficult day. Would you like to tell me more about what's on your mind?",
                                "suggested_responses":[ "I'm feeling down.", "I'm overwhelmed.", "I don't know."]}},
                
                {"Thank you!": {"text": "You're very welcome, I'm glad I could support you. Remember all the amazing progress you've made and the strength you've shown. Keep using those tools. I have every confidence in your continued journey",
                                "suggested_responses":None}}
            ]
    
    def create_messages(self,consumer: Consumer, session: Session, message_data: list = None) -> list[Message]:
        if not message_data:
            message_data = self.get_sample_data()
        
        consumer_participant = Participant.objects.filter(session=session, consumer=consumer,
                                                          agent__isnull=True).first()
        
        agent_participant = Participant.objects.filter(session=session, consumer__isnull=True,
                                                       agent=consumer.agent).first()
        
        messages = []
        for message in message_data:
            consumer_msg, agent_msg_dct = message.popitem()
            
            messages.extend([Message(session=session, sender=consumer_participant, text=consumer_msg),
                             Message(session=session, sender=agent_participant, text=agent_msg_dct['text'],
                                     suggested_responses=agent_msg_dct['suggested_responses'])])
        
        messages = Message.objects.bulk_create(messages)
        return messages
    
    def get_objects(self):
        return self.create_messages(session=self.session, consumer=self.consumer_one)
    
    def get_valid_query_param_variations_for_consumer(self, consumer, objects) -> list[QueryParamsData]:
        return [
            # Using own session_id and consumer_id – expect full matching results
            QueryParamsData(query_params={"session_id": self.session.id, 'consumer_id': consumer.user.id,
                                          'order_by': 'created_at'},
                            results_no=self.get_objects_no(), response_code=status.HTTP_200_OK,
                            results_match_data=self.consumer_one_msg_ids),
            
            # Using own session_id only – still expect full matching results
            QueryParamsData(query_params={"session_id": self.session.id,
                                          'order_by': 'created_at'},
                            results_no=self.get_objects_no(), response_code=status.HTTP_200_OK,
                            results_match_data=self.consumer_one_msg_ids),
            
            # Using own session_id but another user's consumer_id – should still return own results
            QueryParamsData(query_params={"session_id": self.session.id, 'consumer_id': self.consumer_two.user.id,
                                          'order_by': 'created_at'},
                            results_no=self.get_objects_no(), response_code=status.HTTP_200_OK,
                            results_match_data=self.consumer_one_msg_ids),
            
            # Using another session_id with own consumer_id – should return no results due to auth context
            QueryParamsData(query_params={"session_id": self.session_two.id, 'consumer_id': self.consumer_one.user.id},
                            results_no=0, response_code=status.HTTP_200_OK,
                            results_match_data=[]),
            
            # Using another session_id and another consumer_id – should return no results due to auth context
            QueryParamsData(query_params={"session_id": self.session_two.id, 'consumer_id': self.consumer_two.user.id},
                            results_no=0, response_code=status.HTTP_200_OK,
                            results_match_data=[]),
        ]
    
    def get_valid_query_param_variations_for_admin(self, admin, objects) -> list[QueryParamsData]:
        return [
            # Using consumer_one's session_id to get messages specific to the session
            QueryParamsData(query_params={"session_id": self.session.id,
                                          'order_by': 'created_at'},
                            results_no=self.get_objects_no(), response_code=status.HTTP_200_OK,
                            results_match_data=self.consumer_one_msg_ids),
            
            # Using consumer_one's consumer_id to get all messages for consumer_one
            QueryParamsData(query_params={"consumer_id": self.consumer_one.user.id,
                                          'order_by': 'created_at'},
                            results_no=self.get_objects_no() + len(self.yesterday_msg_ids),
                            response_code=status.HTTP_200_OK,
                            results_match_data=self.yesterday_msg_ids + self.consumer_one_msg_ids),
            
            # Using consumer_two's session_id to get messages specific to the session
            QueryParamsData(query_params={"session_id": self.session_two.id, 'order_by': 'created_at'},
                            results_no=len(self.consumer_two_msg_ids), response_code=status.HTTP_200_OK,
                            results_match_data=self.consumer_two_msg_ids),
            
            # Using consumer_two's consumer_id to get all messages for consumer_two
            QueryParamsData(query_params={"consumer_id": self.consumer_two.user.id, 'order_by': 'created_at'},
                            results_no=len(self.consumer_two_msg_ids), response_code=status.HTTP_200_OK,
                            results_match_data=self.consumer_two_msg_ids),
        ]
    
    def test_admin_no_filters(self):
        total_messages = len(self.consumer_one_msg_ids) + len(self.yesterday_msg_ids) + len(self.consumer_two_msg_ids)
        self.valid_list({}, self.admin_one_access_token, total_messages, user=self.admin_one.user)
    
    def test_consumer_no_filters(self):
        total_messages = len(self.consumer_one_msg_ids) + len(self.yesterday_msg_ids)
        self.valid_list({}, self.consumer_one_access_token, total_messages, user=self.consumer_one.user)
    
    def endpoint(self):
        return "messages"


del BaseListTest
