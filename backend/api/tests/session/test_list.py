from freezegun import freeze_time

from ..utils.ListTest import BaseListTest, QueryParamsData
from ..utils.manager import General, Auth
from ...utils import DateUtils


class ListTest(BaseListTest):
    
    def setUp(self):
        self.consumer_two = Auth.create_consumer()
        super(ListTest, self).setUp()
    
    def get_objects(self):
        # mock date for past session
        with freeze_time(DateUtils.yesterday().date()):
            session_one = General.create_session(consumer=self.consumer_one)
            session_two = General.create_session(consumer=self.consumer_two)
        
        session_three = General.create_session(consumer=self.consumer_one)
        session_four = General.create_session(consumer=self.consumer_two)
        
        return [session_one, session_two, session_three, session_four]
    
    def get_valid_query_param_variations_for_consumer(self, consumer_one, objects) -> list[QueryParamsData]:
        expected_data = [{'id': objects[0].id}, {'id': objects[2].id}]
        
        return [
            QueryParamsData(query_params=None, results_no=2, results_match_data=[]),
            QueryParamsData(query_params={'order_by': 'created_at'}, results_no=2, results_match_data=expected_data),
        ]
    
    def get_valid_query_param_variations_for_admin(self, admin, objects) -> list[QueryParamsData]:
        expected_data = [{'id': obj.id} for obj in objects]
        
        return [
            QueryParamsData(
                query_params={'order_by': 'created_at'},
                results_no=self.get_objects_no(),
                results_match_data=expected_data
            ),
        ]
    
    def test_consumer_no_filters(self):
        self.valid_list(
            query_params_data=None,
            access_token=self.consumer_one_access_token,
            results_no=2,
            user=self.consumer_one.user
        )

    def endpoint(self):
        return "sessions"


del BaseListTest
