"""Tests for site image storage and optional title support."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from core.cache_keys import get_list_cache_version
from core.s3_config import s3_public_url
from core.test_auth import authenticate_client
from projects.models import Project
from site_images.models import SiteProgressImage
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


def _jpeg(name="a.jpg") -> SimpleUploadedFile:
    # Minimal valid-enough JPEG bytes for multipart tests
    return SimpleUploadedFile(name, b"\xff\xd8\xff\xe0" + b"0" * 64, content_type="image/jpeg")


class SiteImageTitleAPITest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="si_admin",
            email="si@example.com",
            password="testpass123",
        )
        self.project = Project.objects.create(name="Title Test Project", status="active")
        self.client = APIClient()
        authenticate_client(self.client, username="si_admin", password="testpass123")
        self._upload_n = 0

    def _mock_upload(self, *_args, **_kwargs):
        self._upload_n += 1
        return {
            "secure_url": f"https://example.com/{self._upload_n}.jpg",
            "public_id": f"upload/title-test/{self._upload_n}.jpg",
            "storage_backend": "s3",
        }

    @patch("site_images.views.check_storage_ready", return_value=(True, None))
    @patch("site_images.views.upload_image")
    def test_upload_with_single_title(self, mock_upload, _ready):
        mock_upload.side_effect = self._mock_upload
        response = self.client.post(
            "/api/site-images/",
            {
                "project_name": self.project.name,
                "month": 8,
                "year": 2026,
                "title": "Foundation Progress - Block A",
                "images": _jpeg("one.jpg"),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        item = response.data["data"][0]
        self.assertEqual(item["title"], "Foundation Progress - Block A")
        row = SiteProgressImage.objects.get(pk=item["id"])
        self.assertEqual(row.title, "Foundation Progress - Block A")

    @patch("site_images.views.check_storage_ready", return_value=(True, None))
    @patch("site_images.views.upload_image")
    def test_upload_multiple_with_titles_list(self, mock_upload, _ready):
        mock_upload.side_effect = self._mock_upload
        response = self.client.post(
            "/api/site-images/",
            {
                "project_name": self.project.name,
                "month": 8,
                "year": 2026,
                "titles": ["Alpha", "Beta"],
                "images": [_jpeg("a.jpg"), _jpeg("b.jpg")],
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        titles = [row["title"] for row in response.data["data"]]
        self.assertEqual(titles, ["Alpha", "Beta"])

    @patch("site_images.views.check_storage_ready", return_value=(True, None))
    @patch("site_images.views.upload_image")
    def test_upload_multiple_with_single_title(self, mock_upload, _ready):
        mock_upload.side_effect = self._mock_upload
        response = self.client.post(
            "/api/site-images/",
            {
                "project_name": self.project.name,
                "month": 8,
                "year": 2026,
                "title": "Shared Title",
                "images": [_jpeg("a.jpg"), _jpeg("b.jpg")],
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        titles = [row["title"] for row in response.data["data"]]
        self.assertEqual(titles, ["Shared Title", "Shared Title"])

    @patch("site_images.views.check_storage_ready", return_value=(True, None))
    @patch("site_images.views.upload_image")
    def test_upload_without_title(self, mock_upload, _ready):
        mock_upload.side_effect = self._mock_upload
        response = self.client.post(
            "/api/site-images/",
            {
                "project_name": self.project.name,
                "month": 8,
                "year": 2026,
                "images": _jpeg("plain.jpg"),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertEqual(response.data["data"][0]["title"], "")

    def test_list_and_detail_return_title(self):
        row = SiteProgressImage.objects.create(
            project_name=self.project.name,
            month=7,
            year=2026,
            title="Legacy Compatible",
            image_url="https://example.com/l.jpg",
            cloudinary_public_id="upload/legacy-1.jpg",
            storage_backend=SiteProgressImage.STORAGE_S3,
            uploaded_by=self.user,
        )
        # Existing null-title row still works
        SiteProgressImage.objects.create(
            project_name=self.project.name,
            month=7,
            year=2026,
            title=None,
            image_url="https://example.com/n.jpg",
            cloudinary_public_id="upload/legacy-null.jpg",
            storage_backend=SiteProgressImage.STORAGE_S3,
        )

        list_resp = self.client.get("/api/site-images/", {"project_name": self.project.name})
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)
        results = list_resp.data["data"]["results"]
        by_id = {item["id"]: item for item in results}
        self.assertEqual(by_id[row.id]["title"], "Legacy Compatible")
        null_id = next(i for i in by_id if i != row.id)
        self.assertEqual(by_id[null_id]["title"], "")

        detail = self.client.get(f"/api/site-images/{row.id}/")
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data["data"]["title"], "Legacy Compatible")

    def test_patch_title_without_reupload(self):
        row = SiteProgressImage.objects.create(
            project_name=self.project.name,
            month=7,
            year=2026,
            title="Old",
            image_url="https://example.com/p.jpg",
            cloudinary_public_id="upload/patch-1.jpg",
            storage_backend=SiteProgressImage.STORAGE_S3,
        )
        before_url = row.image_url
        v_before = get_list_cache_version("site_images_list")
        response = self.client.patch(
            f"/api/site-images/{row.id}/",
            {"title": "Updated Foundation Progress"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.data["data"]["title"], "Updated Foundation Progress")
        row.refresh_from_db()
        self.assertEqual(row.title, "Updated Foundation Progress")
        self.assertEqual(row.image_url, before_url)
        self.assertGreater(get_list_cache_version("site_images_list"), v_before)

    def test_search_by_title(self):
        SiteProgressImage.objects.create(
            project_name=self.project.name,
            month=7,
            year=2026,
            title="Foundation Progress - Block A",
            image_url="https://example.com/s1.jpg",
            cloudinary_public_id="upload/search-1.jpg",
            storage_backend=SiteProgressImage.STORAGE_S3,
        )
        SiteProgressImage.objects.create(
            project_name=self.project.name,
            month=7,
            year=2026,
            title="Roofing Work",
            image_url="https://example.com/s2.jpg",
            cloudinary_public_id="upload/search-2.jpg",
            storage_backend=SiteProgressImage.STORAGE_S3,
        )
        response = self.client.get("/api/site-images/", {"search": "foundation"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["data"]["results"]
        self.assertEqual(len(results), 1)
        self.assertIn("Foundation", results[0]["title"])

    def test_ordering_by_title(self):
        SiteProgressImage.objects.create(
            project_name=self.project.name,
            month=7,
            year=2026,
            title="Zebra",
            image_url="https://example.com/z.jpg",
            cloudinary_public_id="upload/ord-z.jpg",
            storage_backend=SiteProgressImage.STORAGE_S3,
        )
        SiteProgressImage.objects.create(
            project_name=self.project.name,
            month=7,
            year=2026,
            title="Alpha",
            image_url="https://example.com/a.jpg",
            cloudinary_public_id="upload/ord-a.jpg",
            storage_backend=SiteProgressImage.STORAGE_S3,
        )
        response = self.client.get(
            "/api/site-images/",
            {"project_name": self.project.name, "ordering": "title"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = [r["title"] for r in response.data["data"]["results"]]
        self.assertEqual(titles, sorted(titles))

    @patch("site_images.views.delete_image")
    def test_delete_invalidates_cache(self, mock_delete):
        mock_delete.return_value = None
        row = SiteProgressImage.objects.create(
            project_name=self.project.name,
            month=7,
            year=2026,
            title="To Delete",
            image_url="https://example.com/d.jpg",
            cloudinary_public_id="upload/del-1.jpg",
            storage_backend=SiteProgressImage.STORAGE_S3,
        )
        v_before = get_list_cache_version("site_images_list")
        response = self.client.delete(f"/api/site-images/{row.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(SiteProgressImage.objects.filter(pk=row.id).exists())
        self.assertGreater(get_list_cache_version("site_images_list"), v_before)
        mock_delete.assert_called_once()
