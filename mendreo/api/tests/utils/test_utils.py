from ...tests.TestCase import TestCase

from .manager.General import create_agent
from ..utils import Data


class UtilsTest(TestCase):

    # tests that get_or_create doesn't fail even if there are multiple existing objects
    # found for the same filter params
    def test_get_or_create(self):
        from ...agent.models import Agent

        create_agent()
        name = Agent.objects.first().name

        self.assertEqual(Agent.objects.filter(name=name).count(), 2)

        agent, created = Agent.objects.get_or_create(name=name)

        self.assertFalse(created)
        self.assertIsNotNone(agent)

