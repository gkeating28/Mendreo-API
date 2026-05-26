from typing import List

from ..utils.ListTest import BaseListTest, QueryParamsData

from ..utils import Data
from ..utils.manager import General

from ...question.models import Question


class ListTest(BaseListTest):
    def setUp(self):
        super(ListTest, self).setUp()
        self.exercise = General.create_exercise()
        self.session = General.start_session(consumer=self.consumer_one, exercise=self.exercise)

    def get_objects_no(self):
        # 3 New question + 4 Question from exercise + 4 Copied question for session
        return len(self.objects) + (self.exercise.questions.count() * 2)
    
    def get_objects(self):

        question_one = General.create_question(Data.valid_question_data(title="Q1", attribute_key="q1"))
        question_two = General.create_question(Data.valid_question_data(title="Q2", attribute_key="q2"))
        question_three = General.create_question(Data.valid_question_data(title="Q3", attribute_key="q3"))

        return [question_one, question_two, question_three]

    def get_valid_query_param_variations_for_admin(self, admin, objects) -> List[QueryParamsData]:
        return [
            QueryParamsData(
                query_params={"search_term": "Q1"},
                results_no=1,
                results_match_data=[{"id": objects[0].id}]
            ),
            QueryParamsData(
                query_params={"session_id": self.session.id, "survey": None},
                results_no=len(self.exercise.questions.all())
            ),
        ]

    def endpoint(self):
        return "questions"


del BaseListTest
