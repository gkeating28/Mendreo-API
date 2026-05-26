from rest_framework import status

from ...post.models import Post
from ...utils import Constants

from ..utils.manager import General, Auth

from ..TestCase import TestCase


class ArticleTest(TestCase):

    def setUp(self):
        self.consumer = Auth.create_consumer()
        self.exercise = General.create_exercise()
        self.session = General.start_session(consumer=self.consumer, exercise=self.exercise)

    def _create(self, data, access_token="", **kwargs):
        response = super()._post(f"/ai", data, access_token=access_token)

        return response

    def test_basic(self):
        """Test that AI can generate a basic article with images based on article content"""

        data = {
            "type": "article"
        }

        response = self._create(data, access_token=Auth.get_platform_admin_access_token())
        print("fff", response.content)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        article = Post.objects.get(id=response.data["id"])

        self.assertIsNotNone(article)
        self.assertIsNotNone(article.id)
        self.assertIsNotNone(article.title)
        self.assertIsNotNone(article.subtitle)
        self.assertIsNotNone(article.body)

        self.assertEqual(article.status, Constants.POST_STATUS_DRAFT)
        self.assertEqual(article.type, Constants.POST_TYPE_ARTICLE)

        self.assertGreater(len(article.title), 10, "Title should be substantial")
        self.assertGreater(len(article.body), 500, "Body should be at least 500 characters")

        self.assertIsNotNone(article.banner, "Banner image should be generated")
        self.assertIsNotNone(article.thumbnail, "Thumbnail image should be generated")

        self.assertEqual(article.thumbnail.width, 1920)
        self.assertEqual(article.thumbnail.height, 1080)
        
        self.assertTrue(article.banner.uploaded)
        self.assertTrue(article.thumbnail.uploaded)

        self.assertEqual(
            article.banner.id, 
            article.thumbnail.id,
            "Banner and thumbnail should use the same image"
        )
