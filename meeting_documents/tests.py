"""Tests for Meeting Documents (MoM & EDL) S3 integration."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from core.test_auth import authenticate_client
from meeting_documents.models import MeetingDocument
from projects.models import Project
from services import s3_meeting_documents as s3_service


def _minimal_pdf_bytes() -> bytes:
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
        b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
    )


def _minimal_zip_bytes(inner_name: str = "word/document.xml") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(inner_name, "<xml/>")
    return buffer.getvalue()


def _minimal_jpeg_bytes() -> bytes:
    try:
        from PIL import Image

        image = Image.new("RGB", (32, 32), color=(120, 80, 40))
        output = io.BytesIO()
        image.save(output, format="JPEG")
        return output.getvalue()
    except ImportError:
        return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


def _minimal_png_bytes() -> bytes:
    try:
        from PIL import Image

        image = Image.new("RGBA", (16, 16), color=(10, 20, 30, 255))
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    except ImportError:
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )


def _uploaded_file(name: str, content: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="application/octet-stream")


S3_SETTINGS = {
    "AWS_ACCESS_KEY_ID": "test-key",
    "AWS_SECRET_ACCESS_KEY": "test-secret",
    "AWS_STORAGE_BUCKET_NAME": "pmcproject",
    "AWS_S3_REGION_NAME": "ap-south-1",
    "AWS_S3_CUSTOM_DOMAIN": "",
}


@override_settings(**S3_SETTINGS)
class S3MeetingDocumentsServiceTest(TestCase):
    def test_build_s3_key_structure(self):
        key = s3_service.build_s3_key(
            project_name="Thane Project",
            meeting_type="MOM",
            meeting_date=date(2026, 7, 15),
            filename="Weekly_Meeting.pdf",
            version=1,
        )
        self.assertEqual(
            key,
            "MOM&EDL/Thane Project/MOM/2026/07/Weekly_Meeting_v1.pdf",
        )

    def test_s3_meeting_document_url_encodes_special_characters(self):
        key = "MOM&EDL/Thane Project/MOM/2026/07/Weekly_Meeting.pdf"
        url = s3_service.s3_meeting_document_url(key)
        self.assertEqual(
            url,
            "https://pmcproject.s3.ap-south-1.amazonaws.com/"
            "MOM%26EDL/Thane%20Project/MOM/2026/07/Weekly_Meeting.pdf",
        )

    def test_duplicate_s3_key_gets_suffix(self):
        project = Project.objects.create(name="Thane Project", status="active")
        existing_key = s3_service.build_s3_key(
            project_name=project.name,
            meeting_type="MOM",
            meeting_date=date(2026, 7, 1),
            filename="Weekly_Meeting.pdf",
            version=1,
        )
        MeetingDocument.objects.create(
            project=project,
            meeting_type="MOM",
            title="Weekly",
            meeting_date=date(2026, 7, 1),
            file_name="Weekly_Meeting.pdf",
            content_type="application/pdf",
            s3_key=existing_key,
            s3_url=s3_service.s3_meeting_document_url(existing_key),
        )
        duplicate_key = s3_service.build_s3_key(
            project_name=project.name,
            meeting_type="MOM",
            meeting_date=date(2026, 7, 1),
            filename="Weekly_Meeting.pdf",
            version=1,
        )
        self.assertTrue(duplicate_key.endswith("_1.pdf"))
        self.assertNotEqual(duplicate_key, existing_key)

    def test_version_suffix_increments(self):
        key_v2 = s3_service.build_s3_key(
            project_name="Thane Project",
            meeting_type="EDL",
            meeting_date=date(2026, 7, 1),
            filename="EDL_Week_01.xlsx",
            version=2,
        )
        self.assertIn("EDL_Week_01_v2.xlsx", key_v2)

    def test_reject_executable_extension(self):
        uploaded = _uploaded_file("malware.exe", b"MZ\x90\x00")
        with self.assertRaises(ValidationError):
            s3_service.validate_upload_file(uploaded)

    def test_reject_unsupported_mime_type(self):
        uploaded = _uploaded_file("notes.txt", b"plain text")
        with self.assertRaises(ValidationError):
            s3_service.validate_upload_file(uploaded)

    def test_reject_corrupted_pdf(self):
        uploaded = _uploaded_file("broken.pdf", b"not-a-pdf")
        with self.assertRaises(ValidationError):
            s3_service.validate_upload_file(uploaded)

    def test_compress_pdf(self):
        uploaded = _uploaded_file("Weekly_Meeting.pdf", _minimal_pdf_bytes())
        compressed = s3_service.compress_document(uploaded)
        self.assertEqual(compressed.file_name, "Weekly_Meeting.pdf")
        self.assertEqual(compressed.content_type, "application/pdf")
        self.assertGreater(compressed.original_size, 0)
        self.assertGreater(compressed.compressed_size, 0)
        compressed.file_obj.close()

    def test_compress_docx(self):
        uploaded = _uploaded_file("Minutes.docx", _minimal_zip_bytes("word/document.xml"))
        compressed = s3_service.compress_document(uploaded)
        self.assertEqual(compressed.content_type, s3_service.ALLOWED_CONTENT_TYPES[".docx"])
        compressed.file_obj.close()

    def test_compress_xlsx(self):
        uploaded = _uploaded_file("EDL.xlsx", _minimal_zip_bytes("xl/workbook.xml"))
        compressed = s3_service.compress_document(uploaded)
        self.assertEqual(compressed.content_type, s3_service.ALLOWED_CONTENT_TYPES[".xlsx"])
        compressed.file_obj.close()

    def test_compress_jpeg(self):
        uploaded = _uploaded_file("site.jpg", _minimal_jpeg_bytes())
        compressed = s3_service.compress_document(uploaded)
        self.assertEqual(compressed.content_type, "image/jpeg")
        compressed.file_obj.close()

    def test_compress_png(self):
        uploaded = _uploaded_file("diagram.png", _minimal_png_bytes())
        compressed = s3_service.compress_document(uploaded)
        self.assertEqual(compressed.content_type, "image/png")
        compressed.file_obj.close()

    @patch("services.s3_meeting_documents.get_s3_client")
    def test_upload_meeting_document_success(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        uploaded = _uploaded_file("Weekly_Meeting.pdf", _minimal_pdf_bytes())
        compressed = s3_service.compress_document(uploaded)
        key = "MOM&EDL/Thane Project/MOM/2026/07/Weekly_Meeting_v1.pdf"

        result = s3_service.upload_meeting_document(compressed, object_key=key)

        self.assertEqual(result["s3_key"], key)
        self.assertIn("MOM%26EDL", result["s3_url"])
        mock_client.upload_fileobj.assert_called_once()
        compressed.file_obj.close()

    @patch("services.s3_meeting_documents.get_s3_client")
    def test_upload_meeting_document_failure(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.upload_fileobj.side_effect = RuntimeError("S3 unavailable")
        mock_get_client.return_value = mock_client
        uploaded = _uploaded_file("Weekly_Meeting.pdf", _minimal_pdf_bytes())
        compressed = s3_service.compress_document(uploaded)

        with self.assertRaises(RuntimeError):
            s3_service.upload_meeting_document(
                compressed,
                s3_key="MOM&EDL/Thane Project/MOM/2026/07/Weekly_Meeting_v1.pdf",
            )
        compressed.file_obj.close()

    @patch("services.s3_meeting_documents.get_s3_client")
    def test_delete_meeting_document(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        key = "MOM&EDL/Thane Project/MOM/2026/07/Weekly_Meeting_v1.pdf"

        s3_service.delete_meeting_document(key)

        mock_client.delete_object.assert_called_once_with(
            Bucket="pmcproject",
            Key=key,
        )

    @patch("services.s3_meeting_documents.get_s3_client")
    def test_generate_presigned_url(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.generate_presigned_url.return_value = "https://signed.example.com/file"
        mock_get_client.return_value = mock_client
        key = "MOM&EDL/Thane Project/MOM/2026/07/Weekly_Meeting_v1.pdf"

        url = s3_service.generate_presigned_url(key)

        self.assertEqual(url, "https://signed.example.com/file")
        mock_client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={
                "Bucket": "pmcproject",
                "Key": key,
                "ResponseContentDisposition": "inline",
            },
            ExpiresIn=s3_service.PRESIGNED_EXPIRY_SECONDS,
        )


@override_settings(**S3_SETTINGS)
class MeetingDocumentAPITest(APITestCase):
    UPLOAD_URL = "/api/meeting-documents/"

    def setUp(self):
        self.project = Project.objects.create(name="Thane Project", status="active")
        tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.user = User.objects.create_user("mom_tl", password="testpass123")
        self.user.groups.add(tl_group)
        self.project.team_lead = self.user
        self.project.save()
        authenticate_client(self.client, username="mom_tl", password="testpass123")

    def _mock_s3(self):
        patcher = patch("services.s3_meeting_documents.get_s3_client")
        self.addCleanup(patcher.stop)
        mock_client = MagicMock()
        patcher.start().return_value = mock_client
        mock_client.generate_presigned_url.return_value = "https://signed.example.com/download"
        return mock_client

    def _upload_payload(self, meeting_type: str, filename: str, content: bytes, **extra):
        data = {
            "project_name": self.project.name,
            "meeting_type": meeting_type,
            "title": extra.pop("title", "Weekly Meeting"),
            "meeting_date": extra.pop("meeting_date", "2026-07-07"),
            "file": _uploaded_file(filename, content),
            **extra,
        }
        return self.client.post(self.UPLOAD_URL, data, format="multipart")

    def test_mom_upload(self):
        mock_client = self._mock_s3()
        response = self._upload_payload("MOM", "Weekly_Meeting.pdf", _minimal_pdf_bytes())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["meeting_type"], "MOM")
        self.assertIn("MOM&EDL/", response.data["data"]["s3_key"])
        mock_client.upload_fileobj.assert_called_once()

    def test_edl_upload(self):
        mock_client = self._mock_s3()
        response = self._upload_payload("EDL", "EDL_Week_01.xlsx", _minimal_zip_bytes("xl/workbook.xml"))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["meeting_type"], "EDL")
        self.assertIn("/EDL/", response.data["data"]["s3_key"])
        mock_client.upload_fileobj.assert_called_once()

    def test_invalid_file_rejection(self):
        self._mock_s3()
        response = self._upload_payload("MOM", "notes.txt", b"plain text")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])

    def test_s3_upload_failure_rolls_back_object(self):
        mock_client = self._mock_s3()
        mock_client.upload_fileobj.side_effect = RuntimeError("upload failed")
        response = self._upload_payload("MOM", "Weekly_Meeting.pdf", _minimal_pdf_bytes())
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(MeetingDocument.objects.count(), 0)

    def test_version_upload_via_patch(self):
        mock_client = self._mock_s3()
        first = self._upload_payload("MOM", "Weekly_Meeting.pdf", _minimal_pdf_bytes())
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        doc_id = first.data["data"]["id"]

        second = self.client.patch(
            f"{self.UPLOAD_URL}{doc_id}/",
            {
                "file": _uploaded_file("Weekly_Meeting.pdf", _minimal_pdf_bytes()),
            },
            format="multipart",
        )
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.data["data"]["document_version"], 2)
        self.assertIn("_v2.pdf", second.data["data"]["s3_key"])
        self.assertEqual(mock_client.upload_fileobj.call_count, 2)

    def test_download_presigned_url(self):
        mock_client = self._mock_s3()
        created = self._upload_payload("MOM", "Weekly_Meeting.pdf", _minimal_pdf_bytes())
        doc_id = created.data["data"]["id"]

        response = self.client.get(f"{self.UPLOAD_URL}{doc_id}/download/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["download_url"], "https://signed.example.com/download")
        self.assertEqual(response.data["data"]["expires_in_seconds"], 600)
        mock_client.generate_presigned_url.assert_called()

    def test_soft_delete_keeps_s3_object(self):
        mock_client = self._mock_s3()
        created = self._upload_payload("MOM", "Weekly_Meeting.pdf", _minimal_pdf_bytes())
        doc_id = created.data["data"]["id"]

        response = self.client.delete(f"{self.UPLOAD_URL}{doc_id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        doc = MeetingDocument.objects.get(pk=doc_id)
        self.assertFalse(doc.is_active)
        mock_client.delete_object.assert_not_called()


class SanitizeFilenameTest(SimpleTestCase):
    def test_sanitize_filename_blocks_path_traversal(self):
        self.assertEqual(
            s3_service.sanitize_filename("../../etc/passwd.pdf"),
            "passwd.pdf",
        )
