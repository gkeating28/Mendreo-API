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

    @mock.patch.object(FileUtils, "_rest_enabled", return_value=True)
    @mock.patch("api.utils.File.requests.post")
    def test_knowledge_upload_link_uses_the_private_folder(self, mock_post, _rest):
        mock_post.return_value = mock.Mock(
            status_code=200,
            raise_for_status=mock.Mock(),
            json=mock.Mock(
                return_value={
                    "url": "/object/upload/sign/Mendreo_Space/knowledge/u/guide.md?token=abc",
                }
            ),
        )
        with mock.patch.object(Api, "SUPABASE_STORAGE_URL", "https://example.supabase.co"):
            with mock.patch.object(Api, "SUPABASE_STORAGE_BUCKET", "Mendreo_Space_Public"):
                with mock.patch.object(Api, "SUPABASE_STORAGE_PRIVATE_BUCKET", "Mendreo_Space"):
                    with mock.patch.object(Api, "SUPABASE_ANON_KEY", "anon"):
                        url, _content_type = FileUtils.get_upload_link(
                            "/knowledge/u/guide.md"
                        )

        self.assertIn(
            "/object/upload/sign/Mendreo_Space/knowledge/u/guide.md",
            mock_post.call_args.args[0],
        )
        self.assertIn("Mendreo_Space/knowledge/u/guide.md", url)

    @mock.patch.object(FileUtils, "_rest_enabled", return_value=True)
    @mock.patch("api.utils.File.requests.get")
    def test_download_text_reads_the_private_knowledge_folder(self, mock_get, _rest):
        mock_get.return_value = mock.Mock(
            status_code=200,
            content=b"# Avoidance\n",
            raise_for_status=mock.Mock(),
        )
        with mock.patch.object(Api, "SUPABASE_STORAGE_URL", "https://example.supabase.co"):
            with mock.patch.object(Api, "SUPABASE_STORAGE_BUCKET", "Mendreo_Space_Public"):
                with mock.patch.object(Api, "SUPABASE_STORAGE_PRIVATE_BUCKET", "Mendreo_Space"):
                    with mock.patch.object(Api, "SUPABASE_ANON_KEY", "anon"):
                        text = FileUtils.download_text("/knowledge/u/guide.md")

        self.assertEqual(text, "# Avoidance\n")
        url = mock_get.call_args.args[0]
        self.assertIn("/storage/v1/object/Mendreo_Space/knowledge/u/guide.md", url)


class RelocateKnowledgeFileTests(SimpleTestCase):
    def _file(self, url):
        uploaded = mock.Mock()
        uploaded.url = url
        uploaded.created_by_id = "usr_1"
        return uploaded

    @mock.patch.object(FileUtils, "delete")
    @mock.patch.object(FileUtils, "upload", return_value=None)
    @mock.patch.object(FileUtils, "_download_bytes", return_value=b"# Guide\n")
    def test_public_admin_upload_is_copied_into_the_private_folder(
        self, download, upload, delete
    ):
        uploaded = self._file("/admins/usr_1/files/abc.md")
        with mock.patch.object(Api, "SUPABASE_STORAGE_BUCKET", "Mendreo_Space_Public"):
            with mock.patch.object(Api, "SUPABASE_STORAGE_PRIVATE_BUCKET", "Mendreo_Space"):
                FileUtils.relocate_to_knowledge_folder(uploaded)

        download.assert_called_once_with("admins/usr_1/files/abc.md", "Mendreo_Space_Public")
        upload.assert_called_once_with(
            b"# Guide\n",
            "knowledge/usr_1/abc.md",
            content_type="text/markdown",
        )
        self.assertEqual(uploaded.url, "/knowledge/usr_1/abc.md")
        uploaded.save.assert_called_once_with(update_fields=["url", "updated_at"])
        delete.assert_called_once_with("/admins/usr_1/files/abc.md")

    @mock.patch.object(FileUtils, "_download_bytes")
    def test_knowledge_key_is_left_in_place(self, download):
        uploaded = self._file("/knowledge/usr_1/abc.md")
        FileUtils.relocate_to_knowledge_folder(uploaded)
        download.assert_not_called()
        uploaded.save.assert_not_called()
        self.assertEqual(uploaded.url, "/knowledge/usr_1/abc.md")

    @mock.patch.object(FileUtils, "delete")
    @mock.patch.object(FileUtils, "upload")
    @mock.patch.object(FileUtils, "_download_bytes", return_value=b"")
    def test_missing_bytes_do_not_rewrite_the_file(self, _download, upload, delete):
        uploaded = self._file("/admins/usr_1/files/abc.md")
        with self.assertRaises(FileUtils.KnowledgeFileMissing):
            FileUtils.relocate_to_knowledge_folder(uploaded)
        upload.assert_not_called()
        delete.assert_not_called()
        uploaded.save.assert_not_called()

    @mock.patch.object(FileUtils, "delete")
    @mock.patch.object(FileUtils, "upload", return_value="Upload error: denied")
    @mock.patch.object(FileUtils, "_download_bytes", return_value=b"# Guide\n")
    def test_failed_copy_keeps_the_public_object(self, _download, _upload, delete):
        uploaded = self._file("/admins/usr_1/files/abc.md")
        with self.assertRaises(FileUtils.KnowledgeFileMissing):
            FileUtils.relocate_to_knowledge_folder(uploaded)
        delete.assert_not_called()
        uploaded.save.assert_not_called()
        self.assertEqual(uploaded.url, "/admins/usr_1/files/abc.md")
