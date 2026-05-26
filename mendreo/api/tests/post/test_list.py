import datetime

from ..utils.ListTest import BaseListTest, QueryParamsData

from ..utils import Data
from ..utils.manager import General

from ...utils import Constants
from ...event.models import Event


class ListTest(BaseListTest):

    def get_objects(self):

        post_one = General.create_post(Data.valid_post_data(title="A1"))
        post_two = General.create_post(Data.valid_post_data(title="A2"))
        post_three = General.create_post(
            Data.valid_post_data(
                title="A3",
                status=Constants.POST_STATUS_PUBLISHED,
                published_at=datetime.datetime.now()
            )
        )

        return [post_one, post_two, post_three]

    def test_consumer_no_filters(self):
        self.valid_list({}, self.consumer_one_access_token, 1, user=self.consumer_one.user)

    def get_valid_query_param_variations_for_consumer(self, admin, objects) -> [QueryParamsData]:
        return [
            QueryParamsData(query_params={"search_term": "A1"}, results_no=0),
            QueryParamsData(query_params={}, results_no=1, results_match_data=[{"id": objects[2].id}]),
        ]

    def get_valid_query_param_variations_for_admin(self, admin, objects) -> [QueryParamsData]:
        return [
            QueryParamsData(query_params={"search_term": "A1"}, results_no=1, results_match_data=[{"id": objects[0].id}]),
        ]

    def validate_list_response_data(self, query_params_data, access_token, results_no, results_match_data, user):

        if not user or user.type != Constants.USER_TYPE_CONSUMER:
            return

        consumer = user.consumer

        impressions_no = Event.objects.filter(consumer=consumer, type=Constants.EVENT_TYPE_IMPRESSION).count()

        self.assertEqual(impressions_no, results_no)

    def endpoint(self):
        return "posts"


del BaseListTest
