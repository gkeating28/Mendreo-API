from ..utils.DetailTest import BaseDetailTest

from ..utils import Data
from ..utils.manager import General

from ...utils import Constants
from ...event.models import Event


class DetailTest(BaseDetailTest):

    def validate_detail_response_data(self, post, user, response_json):

        if user.type != Constants.USER_TYPE_CONSUMER:
            return

        views_no = Event.objects.filter(consumer_id=user.id, post=post, type=Constants.EVENT_TYPE_VIEW).count()
        return self.assertEqual(views_no, 1)

    def get_object(self):
        return General.create_post()

    def endpoint(self):
        return "posts"


del BaseDetailTest
