from ..utils.ListTest import BaseListTest


class ListTest(BaseListTest):

    def get_objects(self):
        return []

    def test_admin_no_filters(self):
        self.method_not_allowed(self._list(self.admin_one_access_token))

    def test_consumer_no_filters(self):
        self.permission_denied_test(self._list(self.consumer_one_access_token))

    def endpoint(self):
        return "files"


del BaseListTest
