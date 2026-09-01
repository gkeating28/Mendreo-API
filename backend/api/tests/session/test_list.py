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

    def test_consumer_general_false_returns_active_exercise_sessions(self):
        exercise = General.create_exercise()
        finished = General.create_session(consumer=self.consumer_one, exercise=exercise)
        finished.completed = True
        finished.save(update_fields=["completed"])
        abandoned = General.create_session(consumer=self.consumer_one, exercise=exercise)
        abandoned.abandoned = True
        abandoned.save(update_fields=["abandoned"])
        active = General.create_session(consumer=self.consumer_one, exercise=exercise)

        self.valid_list(
            query_params_data={"general": "false"},
            access_token=self.consumer_one_access_token,
            results_no=1,
            results_match_data=[{"id": active.id}],
            user=self.consumer_one.user,
        )

    def test_consumer_general_filter_excludes_exercise_sessions(self):
        exercise = General.create_exercise()
        General.create_session(consumer=self.consumer_one, exercise=exercise)

        older = self.objects[0]
        newer = self.objects[2]
        with freeze_time("2026-08-21 10:00:00"):
            older.save()
        with freeze_time("2026-08-21 12:00:00"):
            newer.save()

        self.valid_list(
            query_params_data={"general": "true"},
            access_token=self.consumer_one_access_token,
            results_no=2,
            results_match_data=[{"id": newer.id}, {"id": older.id}],
            user=self.consumer_one.user,
        )

    def endpoint(self):
        return "sessions"


del BaseListTest
