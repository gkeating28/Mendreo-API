from ...tests.TestCase import TestCase
from rest_framework import status

from ...role.models import Role
from ...utils import Constants


class PIIObscuringTests(TestCase):

    def _assert_pii_data(self, data, obscured=False):
        """Helper method to check if PII data is obscured or not

        Args:
            data: Dictionary containing user data to check
            obscured: If True, expects obscured values; if False, expects real values
        """
        if obscured:

            self.assertEqual(data["user"]["first_name"], Constants.ANON_FIRST_NAME)
            self.assertEqual(data["user"]["last_name"], Constants.ANON_LAST_NAME)
            self.assertEqual(data["user"]["full_name"], f"{Constants.ANON_FIRST_NAME} {Constants.ANON_LAST_NAME}")
            self.assertEqual(data["user"]["email"], Constants.ANON_EMAIL)
            if "date_of_birth" in data:
                self.assertEqual(data["date_of_birth"], Constants.ANON_DATE_OF_BIRTH)
        else:

            self.assertEqual(data["user"]["first_name"], "John")
            self.assertEqual(data["user"]["last_name"], "Doe")
            self.assertEqual(data["user"]["full_name"], "John Doe")
            self.assertEqual(data["user"]["email"], "john.doe@example.com")
            if "date_of_birth" in data:
                self.assertEqual(data["date_of_birth"], "1990-05-15")

    def setUp(self):
        from ..utils.manager.Auth import get_access_token, get_or_create_consumer, create_admin


        self.consumer = get_or_create_consumer()
        self.consumer.user.first_name = "John"
        self.consumer.user.last_name = "Doe"
        self.consumer.user.email = "john.doe@example.com"
        self.consumer.user.save()

        self.consumer.date_of_birth = "1990-05-15"
        self.consumer.save()

 
        self.admin_with_pii = create_admin()
        self.admin_with_pii.role.name = "Admin with PII"
        self.admin_with_pii.role.save()


        permissions_with_pii = self.admin_with_pii.role.permissions
        permissions_with_pii.users = [Constants.PERMISSION_VIEW]
        permissions_with_pii.sessions = [Constants.PERMISSION_VIEW]
        permissions_with_pii.pii = [Constants.PERMISSION_VIEW]
        permissions_with_pii.save()

        self.admin_with_pii_token = get_access_token(self.admin_with_pii.user)


        self.admin_without_pii = create_admin()
        self.admin_without_pii.role.name = "Admin without PII"
        self.admin_without_pii.role.save()


        permissions_without_pii = self.admin_without_pii.role.permissions
        permissions_without_pii.users = [Constants.PERMISSION_VIEW]
        permissions_without_pii.sessions = [Constants.PERMISSION_VIEW]
        permissions_without_pii.pii = []
        permissions_without_pii.save()

        self.admin_without_pii_token = get_access_token(self.admin_without_pii.user)

    def test_admin_with_pii_permission_sees_real_data(self):
        from ...consumer.models import Consumer

        response = self._get(
            "/consumers",
            access_token=self.admin_with_pii_token
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json

        for result in response_data["results"]:
            consumer_from_db = Consumer.objects.get(user_id=result["user"]["id"])

 
            self.assertEqual(result["user"]["first_name"], consumer_from_db.user.first_name)
            self.assertEqual(result["user"]["last_name"], consumer_from_db.user.last_name)
            self.assertEqual(result["user"]["email"], consumer_from_db.user.email)


            if consumer_from_db.user_id == self.consumer.user_id:
                self._assert_pii_data(result, obscured=False)

    def test_admin_without_pii_permission_sees_obscured_data(self):
        from ...consumer.models import Consumer

        response = self._get(
            "/consumers",
            access_token=self.admin_without_pii_token
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json

       
        for result in response_data["results"]:
            consumer_from_db = Consumer.objects.get(user_id=result["user"]["id"])

          
            self.assertNotEqual(result["user"]["first_name"], consumer_from_db.user.first_name)
            self.assertNotEqual(result["user"]["last_name"], consumer_from_db.user.last_name)
            self.assertNotEqual(result["user"]["email"], consumer_from_db.user.email)


            if consumer_from_db.user_id == self.consumer.user_id:
                self._assert_pii_data(result, obscured=True)

    def test_consumer_detail_pii_with_permission(self):
        from ...consumer.models import Consumer

        response = self._get(
            f"/consumers/{self.consumer.user_id}",
            access_token=self.admin_with_pii_token
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json


        consumer_from_db = Consumer.objects.get(user_id=self.consumer.user_id)
        self.assertEqual(response_data["user"]["first_name"], consumer_from_db.user.first_name)
        self.assertEqual(response_data["user"]["last_name"], consumer_from_db.user.last_name)
        self.assertEqual(response_data["user"]["email"], consumer_from_db.user.email)

        self._assert_pii_data(response_data, obscured=False)

    def test_consumer_detail_pii_without_permission(self):
        from ...consumer.models import Consumer

        response = self._get(
            f"/consumers/{self.consumer.user_id}",
            access_token=self.admin_without_pii_token
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json

      
        consumer_from_db = Consumer.objects.get(user_id=self.consumer.user_id)
        self.assertNotEqual(response_data["user"]["first_name"], consumer_from_db.user.first_name)
        self.assertNotEqual(response_data["user"]["last_name"], consumer_from_db.user.last_name)
        self.assertNotEqual(response_data["user"]["email"], consumer_from_db.user.email)

        self._assert_pii_data(response_data, obscured=True)

    def test_sessions_list_pii_obscuring(self):
        from ...session.models import Session
        from ...consumer.models import Consumer
        from ..utils.manager.General import create_exercise, create_session


        exercise = create_exercise()
        session = create_session(consumer=self.consumer, exercise=exercise)


        response = self._get(
            "/sessions",
            access_token=self.admin_with_pii_token
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json

        for result in response_data["results"]:
            session_from_db = Session.objects.get(id=result["id"])
            consumer_from_db = Consumer.objects.get(user_id=result["consumer"]["user"]["id"])


            self.assertEqual(result["consumer"]["user"]["first_name"], consumer_from_db.user.first_name)
            self.assertEqual(result["consumer"]["user"]["last_name"], consumer_from_db.user.last_name)


            if session_from_db.id == session.id:
                self._assert_pii_data(result["consumer"], obscured=False)


        response = self._get(
            "/sessions",
            access_token=self.admin_without_pii_token
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json

        for result in response_data["results"]:
            session_from_db = Session.objects.get(id=result["id"])
            consumer_from_db = Consumer.objects.get(user_id=session_from_db.consumer.user_id)

            
            self.assertNotEqual(result["consumer"]["user"]["first_name"], consumer_from_db.user.first_name)
            self.assertNotEqual(result["consumer"]["user"]["last_name"], consumer_from_db.user.last_name)


            if session_from_db.id == session.id:
                self._assert_pii_data(result["consumer"], obscured=True)
