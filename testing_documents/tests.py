"""Tests for testing_documents API (S3 upload mocked)."""

from datetime import date
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserProfile
from projects.models import Project
from testing_documents.models import TestingDocument, TestingDocumentAuditLog

User = get_user_model()


def _pdf_file(name="cube_test.pdf"):
    return SimpleUploadedFile(
        name,
        b"%PDF-1.4\n%fake pdf content\n",
        content_type="application/pdf",
    )


def _fake_upload(**kwargs):
    uploaded_file = kwargs["uploaded_file"]
    name = getattr(uploaded_file, "name", "cube_test.pdf")
    return {
        "s3_key": f"testing/{kwargs['project_id']}/{kwargs['year']}/{kwargs['month']:02d}/abcd1234.pdf",
        "file_url": "https://pmcproject.s3.ap-south-1.amazonaws.com/testing/key.pdf",
        "file_name": name.split("/")[-1],
        "file_size": int(getattr(uploaded_file, "size", 20) or 20),
        "mime_type": "application/pdf",
        "document_type": "pdf",
    }


class TestingDocumentsAPITest(APITestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Satis Thane Test Docs", status="active")
        self.other = Project.objects.create(name="Other Project Docs", status="active")

        self.qaqc = User.objects.create_user(username="qaqc_test_docs", password="testpass123")
        g_qaqc, _ = Group.objects.get_or_create(name="QAQC Site Engineer")
        self.qaqc.groups.add(g_qaqc)
        UserProfile.objects.get_or_create(user=self.qaqc)
        self.project.qaqc_site_engineer = self.qaqc
        self.project.save(update_fields=["qaqc_site_engineer", "updated_at"])

        self.tl = User.objects.create_user(username="tl_test_docs", password="testpass123")
        g_tl, _ = Group.objects.get_or_create(name="Team Leader")
        self.tl.groups.add(g_tl)
        UserProfile.objects.get_or_create(user=self.tl)
        self.project.team_lead = self.tl
        self.project.save(update_fields=["team_lead", "updated_at"])

        self.outsider = User.objects.create_user(username="outsider_docs", password="testpass123")
        self.outsider.groups.add(g_qaqc)
        UserProfile.objects.get_or_create(user=self.outsider)

        self._login(self.qaqc)

    def _login(self, user):
        login = self.client.post(
            "/api/token/",
            {"username": user.username, "password": "testpass123"},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

    @patch("testing_documents.views.upload_testing_document", side_effect=_fake_upload)
    @patch("testing_documents.views.delete_testing_document")
    def test_upload_retrieve_list(self, _mock_del, _mock_up):
        response = self.client.post(
            "/api/testing-documents/",
            {
                "project": self.project.id,
                "title": "Concrete Cube Test",
                "remarks": "28-day strength",
                "test_date": "2026-07-20",
                "file": _pdf_file(),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(response.data["success"])
        data = response.data["data"]
        self.assertEqual(data["title"], "Concrete Cube Test")
        self.assertEqual(data["document_type"], "pdf")
        self.assertEqual(data["month"], 7)
        self.assertEqual(data["year"], 2026)
        self.assertEqual(data["project"]["id"], self.project.id)
        self.assertEqual(data["uploaded_by"]["username"], "qaqc_test_docs")
        doc_id = data["id"]

        self.assertTrue(
            TestingDocumentAuditLog.objects.filter(
                action="created", document_id_snapshot=doc_id
            ).exists()
        )

        detail = self.client.get(f"/api/testing-documents/{doc_id}/")
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data["data"]["id"], doc_id)

        listing = self.client.get(
            f"/api/testing-documents/?project={self.project.id}&year=2026&month=7"
        )
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        payload = listing.data["data"]
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertGreaterEqual(len(results), 1)

        search = self.client.get("/api/testing-documents/?search=Concrete")
        self.assertEqual(search.status_code, status.HTTP_200_OK)

        ordered = self.client.get("/api/testing-documents/?ordering=title")
        self.assertEqual(ordered.status_code, status.HTTP_200_OK)

    @patch("testing_documents.views.upload_testing_document", side_effect=_fake_upload)
    @patch("testing_documents.views.delete_testing_document")
    def test_update_and_delete_permissions(self, mock_del, _mock_up):
        create = self.client.post(
            "/api/testing-documents/",
            {
                "project": self.project.id,
                "title": "Steel Test",
                "test_date": "2026-07-01",
                "file": _pdf_file("steel.pdf"),
            },
            format="multipart",
        )
        doc_id = create.data["data"]["id"]

        # Uploader can patch
        patch = self.client.patch(
            f"/api/testing-documents/{doc_id}/",
            {"remarks": "updated"},
            format="multipart",
        )
        self.assertEqual(patch.status_code, status.HTTP_200_OK, patch.data)
        self.assertEqual(patch.data["data"]["remarks"], "updated")

        # QAQC cannot delete
        delete_qaqc = self.client.delete(f"/api/testing-documents/{doc_id}/")
        self.assertEqual(delete_qaqc.status_code, status.HTTP_403_FORBIDDEN)

        # TL can delete
        self._login(self.tl)
        delete_tl = self.client.delete(f"/api/testing-documents/{doc_id}/")
        self.assertEqual(delete_tl.status_code, status.HTTP_200_OK, delete_tl.data)
        self.assertFalse(TestingDocument.objects.get(pk=doc_id).is_active)
        mock_del.assert_called()

    @patch("testing_documents.views.upload_testing_document", side_effect=_fake_upload)
    def test_rbac_outsider_cannot_create_or_list(self, _mock_up):
        self._login(self.outsider)
        create = self.client.post(
            "/api/testing-documents/",
            {
                "project": self.project.id,
                "title": "Blocked",
                "test_date": "2026-07-01",
                "file": _pdf_file(),
            },
            format="multipart",
        )
        self.assertEqual(create.status_code, status.HTTP_403_FORBIDDEN)

        listing = self.client.get(f"/api/testing-documents/?project={self.project.id}")
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        payload = listing.data["data"]
        results = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        self.assertEqual(len(results), 0)

    def test_invalid_file_rejected(self):
        from django.core.exceptions import ValidationError
        from services.s3_testing_documents import build_s3_key, validate_upload_file

        bad = SimpleUploadedFile("virus.exe", b"MZ\x90", content_type="application/octet-stream")
        with self.assertRaises(ValidationError):
            validate_upload_file(bad)

        key = build_s3_key(project_id=12, year=2026, month=7, filename="cube.pdf")
        self.assertTrue(key.startswith("testing/12/2026/07/"))
        self.assertTrue(key.endswith(".pdf"))

        rejected = self.client.post(
            "/api/testing-documents/",
            {
                "project": self.project.id,
                "title": "Bad file",
                "test_date": "2026-07-01",
                "file": bad,
            },
            format="multipart",
        )
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(rejected.data["success"])

    def test_unauthorized(self):
        self.client.credentials()
        response = self.client.get("/api/testing-documents/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("testing_documents.views.upload_testing_document", side_effect=_fake_upload)
    @patch(
        "testing_documents.views.generate_presigned_url",
        return_value="https://signed.example/test.pdf",
    )
    def test_download(self, _mock_sign, _mock_up):
        create = self.client.post(
            "/api/testing-documents/",
            {
                "project": self.project.id,
                "title": "NDT",
                "test_date": "2026-07-15",
                "file": _pdf_file("ndt.pdf"),
            },
            format="multipart",
        )
        doc_id = create.data["data"]["id"]
        download = self.client.get(f"/api/testing-documents/{doc_id}/download/")
        self.assertEqual(download.status_code, status.HTTP_200_OK)
        self.assertEqual(
            download.data["data"]["download_url"],
            "https://signed.example/test.pdf",
        )
        self.assertTrue(download.data["data"]["preview"])
