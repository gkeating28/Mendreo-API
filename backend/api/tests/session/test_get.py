from rest_framework import status

from ..utils.manager import Auth
from ...tests.TestCase import TestCase


class GetTest(TestCase):

    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.consumer_access_token = Auth.get_consumer_access_token(self.consumer)
        self.consumer.user.email_verified = True
        self.consumer.user.save()
        self.assertFalse(self.consumer.onboarded)

    def _get(self, id_, access_token="", **kwargs):
        response = super()._get(f"/sessions/{id_}", access_token=access_token)
        return response
    
    def _get_session(self) -> dict:
        """Helper method to get today's session with valid token."""
        session_response = self._get(id_='today',access_token=self.consumer_access_token)
        self.assertEqual(session_response.status_code, status.HTTP_200_OK)
        return session_response.json

    def test_single_session_per_date(self):
        """Ensure that each subsequent API call on the same date returns the same session"""
        # Get session for Today (creates new session)
        session_response_json = self._get_session()
        session_id = session_response_json['id']
        
        # Again get session for today, must receive the same session
        session_response_json = self._get_session()
        self.assertEqual(session_response_json['id'], session_id)
        
        # Again get session for today, must receive the same session
        session_response_json = self._get_session()
        self.assertEqual(session_response_json['id'], session_id)
    
    def test_get_session_by_valid_id(self):
        """Should return session details for a valid session ID."""
        session = self._get_session()
        session_id = session.get('id')
        
        session_response = self._get(id_=session_id, access_token=self.consumer_access_token)
        session_response_json = session_response.json
        
        self.assertEqual(session_response.status_code, status.HTTP_200_OK)
        self.assertEqual(session_response_json["id"], session_id)
    
    def test_get_session_by_invalid_id(self):
        """Should return session details for a valid session ID."""
        session_id = 'invalid_session_id'
        
        session_response = self._get(id_=session_id, access_token=self.consumer_access_token)
        
        self.assertEqual(session_response.status_code, status.HTTP_404_NOT_FOUND)