"""Tests for site image storage (S3 primary, Cloudinary fallback)."""

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from core.s3_config import s3_public_url
from site_images.services import image_storage


class S3PublicUrlTest(SimpleTestCase):
    @override_settings(
        AWS_STORAGE_BUCKET_NAME="pmcproject",
        AWS_S3_REGION_NAME="ap-south-1",
        AWS_S3_CUSTOM_DOMAIN="",
    )
    def test_public_url_format(self):
        url = s3_public_url("upload/thane-project/2026/03/abc.jpg")
        self.assertEqual(
            url,
            "https://pmcproject.s3.ap-south-1.amazonaws.com/upload/thane-project/2026/03/abc.jpg",
        )


class ImageStorageFallbackTest(SimpleTestCase):
    @override_settings(SITE_IMAGE_STORAGE_PRIMARY="s3")
    @patch("site_images.services.image_storage.s3_service.upload_image")
    @patch("site_images.services.image_storage.s3_service.check_s3_ready", return_value=(True, None))
    def test_upload_uses_s3_when_configured(self, _ready, mock_s3_upload):
        mock_s3_upload.return_value = {
            "secure_url": "https://example.com/a.jpg",
            "public_id": "upload/p/a.jpg",
            "storage_backend": "s3",
        }
        file_obj = type("F", (), {"name": "a.jpg", "size": 100, "seek": lambda self, n: None})()
        result = image_storage.upload_image(file_obj, folder="Thane/2026/03")
        self.assertEqual(result["storage_backend"], "s3")
        mock_s3_upload.assert_called_once()

    @override_settings(SITE_IMAGE_STORAGE_PRIMARY="s3", SITE_IMAGE_S3_ONLY=False)
    @patch("site_images.services.image_storage.cloudinary_service.upload_image")
    @patch(
        "site_images.services.image_storage.cloudinary_service.check_cloudinary_ready",
        return_value=(True, None),
    )
    @patch("site_images.services.image_storage.s3_service.upload_image", side_effect=RuntimeError("s3 down"))
    @patch("site_images.services.image_storage.s3_service.check_s3_ready", return_value=(True, None))
    def test_upload_falls_back_to_cloudinary(self, _s3_ready, _s3_upload, _cloud_ready, mock_cloud_upload):
        mock_cloud_upload.return_value = {
            "secure_url": "https://res.cloudinary.com/x.jpg",
            "public_id": "pmc/x",
        }
        file_obj = type("F", (), {"name": "a.jpg", "size": 100, "seek": lambda self, n: None})()
        result = image_storage.upload_image(file_obj, folder="Thane/2026/03")
        self.assertEqual(result["storage_backend"], "cloudinary")
        mock_cloud_upload.assert_called_once()

    @override_settings(SITE_IMAGE_STORAGE_PRIMARY="s3", SITE_IMAGE_S3_ONLY=True)
    @patch("site_images.services.image_storage.s3_service.upload_image", side_effect=RuntimeError("s3 down"))
    @patch("site_images.services.image_storage.s3_service.check_s3_ready", return_value=(True, None))
    def test_s3_only_skips_cloudinary_fallback(self, _s3_ready, _s3_upload):
        file_obj = type("F", (), {"name": "a.jpg", "size": 100, "seek": lambda self, n: None})()
        with self.assertRaises(RuntimeError):
            image_storage.upload_image(file_obj, folder="Thane/2026/03")
