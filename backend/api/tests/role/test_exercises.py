from .base_test import RolePermissionsTests


class ExerciseTest(RolePermissionsTests):
    """Test role-based permissions for Exercise resource"""


    disable_view_owned_tests = True
    disable_delete_owned_tests = True
    disable_edit_owned_tests = True

  
    disable_create_tests = True
    disable_edit_all_tests = True

    view_all_count = 2

    def _make_owned_object(self):
        """Create an exercise"""
        from ..utils.manager.General import create_exercise
        from ..utils import Data

        data = Data.valid_exercise_flexible_thinking()
        data["title"] = "Test Exercise 1"
        return create_exercise(data=data)

    def _make_non_owned_object(self):
        """Create another exercise"""
        from ..utils.manager.General import create_exercise
        from ..utils import Data

        data = Data.valid_exercise_flexible_thinking()
        data["title"] = "Test Exercise 2"
        return create_exercise(data=data)

    def _get_permission_key(self):
        return "exercises"

    def _get_endpoint(self):
        return "exercises"

    def _create_data(self):
        from ..utils import Data

        data = Data.valid_exercise_flexible_thinking()
        data["title"] = "New Exercise"
        return data

    def _edit_data(self):
        return {
            "title": "Updated Exercise Title",
            "subtitle": "Updated Subtitle"
        }


del RolePermissionsTests
