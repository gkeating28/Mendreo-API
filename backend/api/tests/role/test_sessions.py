from .base_test import RolePermissionsTests


class SessionTest(RolePermissionsTests):
    """Test role-based permissions for Session resource"""


    disable_view_owned_tests = True
    disable_delete_owned_tests = True
    disable_delete_all_tests = True 
    disable_edit_owned_tests = True
    disable_edit_all_tests = True 
    disable_create_tests = True  

    view_all_count = 2

    def _make_owned_object(self):
        """Create a session for consumer 1"""
        from ...session.models import Session
        from ..utils.manager.Auth import get_or_create_consumer

        consumer1 = get_or_create_consumer()

        session = Session.objects.create(
            consumer=consumer1,
            subject="Test Session 1",
            messages_no=5,
            consumer_messages_no=3,
            agent_messages_no=2,
            completed=False
        )
        return session

    def _make_non_owned_object(self):
        """Create a session for consumer 2"""
        from ...session.models import Session
        from ..utils.manager.Auth import create_consumer

        consumer2 = create_consumer()

        session = Session.objects.create(
            consumer=consumer2,
            subject="Test Session 2",
            messages_no=10,
            consumer_messages_no=6,
            agent_messages_no=4,
            completed=True
        )
        return session

    def _get_permission_key(self):
        return "sessions"

    def _get_endpoint(self):
        return "sessions"

    def _create_data(self):
        from ..utils.manager.Auth import get_or_create_consumer

        consumer = get_or_create_consumer()

        return {
            "consumer": consumer.user.id,
            "subject": "New Session",
            "completed": False
        }

    def _edit_data(self):
        return {
            "subject": "Updated Session Subject",
            "completed": True
        }


del RolePermissionsTests
