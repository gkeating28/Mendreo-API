from unittest import mock

from django.test import SimpleTestCase, override_settings

from ...utils import File as FileUtils
from ...utils import Api


class RestSignedUploadTests(SimpleTestCase):
    @override_settings()
    @mock.patch.object(FileUtils, "_rest_enabled", return_value=True)
    @mock.patch("api.utils.File.requests.post")
    def test_get_upload_link_uses_rest_signed_url(self, mock_post, _rest):
        mock_post.return_value = mock.Mock(
            status_code=200,
            raise_for_status=mock.Mock(),
            json=mock.Mock(
                return_value={
                    "url": "/object/upload/sign/Mendreo_Space_Public/admins/u/images/a.jpg?token=abc",
                    "token": "abc",
                }
            ),
        )

        with mock.patch.object(Api, "SUPABASE_STORAGE_URL", "https://example.supabase.co"):
            with mock.patch.object(Api, "SUPABASE_STORAGE_BUCKET", "Mendreo_Space_Public"):
                with mock.patch.object(Api, "SUPABASE_ANON_KEY", "anon"):
                    url, content_type = FileUtils.get_upload_link(
                        "/admins/u/images/a.jpg"
                    )

        self.assertEqual(content_type, "image/jpeg")
        self.assertEqual(
            url,
            "https://example.supabase.co/storage/v1/object/upload/sign/"
            "Mendreo_Space_Public/admins/u/images/a.jpg?token=abc",
        )
        mock_post.assert_called_once()

    @mock.patch.object(FileUtils, "_rest_enabled", return_value=True)
    @mock.patch("api.utils.File.requests.head")
    def test_exists_uses_rest_head(self, mock_head, _rest):
        mock_head.return_value = mock.Mock(status_code=200)
        with mock.patch.object(Api, "SUPABASE_STORAGE_URL", "https://example.supabase.co"):
            with mock.patch.object(Api, "SUPABASE_STORAGE_BUCKET", "Mendreo_Space_Public"):
                with mock.patch.object(Api, "SUPABASE_ANON_KEY", "anon"):
                    self.assertTrue(FileUtils.exists("/admins/u/images/a.jpg"))
