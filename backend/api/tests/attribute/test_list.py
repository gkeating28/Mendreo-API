from ..utils.ListTest import BaseListTest, QueryParamsData

from ..utils import Data
from ..utils.manager import General, Auth

from ...question.models import Question


class ListTest(BaseListTest):

    def get_objects(self):

        attribute_one = General.create_attribute(consumer=self.consumer_one)

        attribute_two = General.create_attribute(
            consumer=Auth.create_consumer(),
            question=General.create_question(data=Data.valid_question_data(attribute_key="text_2"))
        )

        return [attribute_one, attribute_two]

    def test_consumer_no_filters(self):
        self.valid_list({}, self.consumer_one_access_token, 1)

    def get_valid_query_param_variations_for_consumer(self, consumer, objects) -> [QueryParamsData]:
        return [
            QueryParamsData(query_params={}, results_no=1, results_match_data=[{"id": objects[0].id}]),
        ]

    def get_valid_query_param_variations_for_admin(self, admin, objects) -> [QueryParamsData]:
        return [
            QueryParamsData(query_params={"search_term": "INVALID"}, results_no=2, results_match_data=[{"id": objects[1].id}]),
        ]

    def endpoint(self):
        return "attributes"


del BaseListTest
