"""Tests for correspondence document attachments and S3 integration."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Notification
from core.test_auth import authenticate_client
from correspondence.models.attachment import CorrespondenceDocumentAttachment
from correspondence.models.correspondence import CorrespondenceDocument
from projects.models import Project
from services import s3_correspondence_documents as s3_service


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


def _uploaded_file(name: str, content: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="application/octet-stream")


S3_SETTINGS = {
    "AWS_ACCESS_KEY_ID": "test-key",
    "AWS_SECRET_ACCESS_KEY": "test-secret",
    "AWS_STORAGE_BUCKET_NAME": "pmcproject",
    "AWS_S3_REGION_NAME": "ap-south-1",
    "AWS_S3_CUSTOM_DOMAIN": "",
}


def _create_correspondence(
    project_name: str,
    *,
    correspondence_type: str = "CLIENT",
    flow_direction: str = CorrespondenceDocument.FLOW_INBOUND,
    recipient_type: str | None = None,
) -> CorrespondenceDocument:
    kwargs = {
        "project_name": project_name,
        "month": 7,
        "year": 2026,
        "correspondence_type": correspondence_type,
        "description": "Test correspondence",
        "received_date": date(2026, 7, 7),
        "flow_direction": flow_direction,
    }
    if recipient_type:
        kwargs["recipient_type"] = recipient_type
    flow = kwargs.get("flow_direction", CorrespondenceDocument.FLOW_INBOUND)
    kwargs["sr_no"] = CorrespondenceDocument.next_sr_no(
        kwargs["project_name"],
        kwargs["month"],
        kwargs["year"],
        kwargs["correspondence_type"],
        flow_direction=flow,
    )
    return CorrespondenceDocument.objects.create(**kwargs)


@override_settings(**S3_SETTINGS)
class CorrespondenceAttachmentServiceTest(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Thane Project", status="active")
        self.correspondence = _create_correspondence(self.project.name)

    def test_build_s3_key_client_folder(self):
        key = s3_service.build_s3_key(
            project_name=self.project.name,
            correspondence=self.correspondence,
            filename="Client_Letter.pdf",
            version=1,
        )
        self.assertEqual(
            key,
            "Correspondence/Thane Project/CLIENT/2026/07/Client_Letter_v1.pdf",
        )

    def test_build_s3_key_scl_folder(self):
        scl = _create_correspondence(
            self.project.name,
            correspondence_type="CLIENT",
            flow_direction=CorrespondenceDocument.FLOW_OUTBOUND_SCL,
            recipient_type="CLIENT",
        )
        key = s3_service.build_s3_key(
            project_name=self.project.name,
            correspondence=scl,
            filename="Official_Letter.pdf",
            version=1,
        )
        self.assertIn("/SCL/", key)

    def test_s3_url_encoding(self):
        key = "Correspondence/Thane Project/CLIENT/2026/07/Client_Letter_v1.pdf"
        url = s3_service.s3_correspondence_document_url(key)
        self.assertIn("Thane%20Project", url)
        self.assertTrue(url.startswith("https://pmcproject.s3.ap-south-1.amazonaws.com/"))


@override_settings(**S3_SETTINGS)
class CorrespondenceAttachmentAPITest(APITestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Thane Project", status="active")
        self.pmc_head = User.objects.create_user("corr_pmc", password="testpass123")
        pmc_group, _ = Group.objects.get_or_create(name="PMC Head")
        self.pmc_head.groups.add(pmc_group)
        authenticate_client(self.client, username="corr_pmc", password="testpass123")

    def _mock_s3(self):
        patcher = patch("services.s3_correspondence_documents.get_s3_client")
        self.addCleanup(patcher.stop)
        mock_client = MagicMock()
        patcher.start().return_value = mock_client
        mock_client.generate_presigned_url.return_value = "https://signed.example.com/download"
        return mock_client

    def _create_doc(self, **kwargs):
        return _create_correspondence(self.project.name, **kwargs)

    def _upload(self, correspondence_id, filename, content, **extra):
        data = {
            "file": _uploaded_file(filename, content),
            **extra,
        }
        return self.client.post(
            f"/api/correspondence-documents/{correspondence_id}/attachments/",
            data,
            format="multipart",
        )

    def test_client_attachment_upload(self):
        mock_client = self._mock_s3()
        doc = self._create_doc(correspondence_type="CLIENT")
        response = self._upload(doc.id, "Client_Letter.pdf", _minimal_pdf_bytes())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        attachment = CorrespondenceDocumentAttachment.objects.get(pk=response.data["data"]["id"])
        self.assertIn("/CLIENT/", attachment.s3_key)
        self.assertIn("download_url", response.data["data"])
        mock_client.upload_fileobj.assert_called_once()

    def test_contractor_attachment_upload(self):
        self._mock_s3()
        doc = self._create_doc(correspondence_type="CONTRACTOR")
        response = self._upload(doc.id, "Approval.pdf", _minimal_pdf_bytes())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        attachment = CorrespondenceDocumentAttachment.objects.get(pk=response.data["data"]["id"])
        self.assertIn("/CONTRACTOR/", attachment.s3_key)

    def test_scl_attachment_upload(self):
        self._mock_s3()
        doc = self._create_doc(
            correspondence_type="CLIENT",
            flow_direction=CorrespondenceDocument.FLOW_OUTBOUND_SCL,
            recipient_type="CLIENT",
        )
        response = self._upload(doc.id, "Circular.pdf", _minimal_pdf_bytes())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        attachment = CorrespondenceDocumentAttachment.objects.get(pk=response.data["data"]["id"])
        self.assertIn("/SCL/", attachment.s3_key)

    def test_multiple_attachments(self):
        self._mock_s3()
        doc = self._create_doc()
        first = self._upload(doc.id, "Letter1.pdf", _minimal_pdf_bytes())
        second = self._upload(doc.id, "Letter2.pdf", _minimal_pdf_bytes())
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        listing = self.client.get(f"/api/correspondence-documents/{doc.id}/attachments/")
        self.assertEqual(len(listing.data["data"]), 2)

    def test_docx_upload(self):
        self._mock_s3()
        doc = self._create_doc()
        response = self._upload(
            doc.id,
            "Notice.docx",
            _minimal_zip_bytes("word/document.xml"),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_xlsx_upload(self):
        self._mock_s3()
        doc = self._create_doc()
        response = self._upload(
            doc.id,
            "Report.xlsx",
            _minimal_zip_bytes("xl/workbook.xml"),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_image_upload(self):
        self._mock_s3()
        doc = self._create_doc()
        response = self._upload(doc.id, "scan.jpg", _minimal_jpeg_bytes())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_invalid_file_rejection(self):
        self._mock_s3()
        doc = self._create_doc()
        response = self._upload(doc.id, "notes.txt", b"plain text")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_oversized_file_rejection(self):
        self._mock_s3()
        doc = self._create_doc()
        huge = _minimal_pdf_bytes() + (b"0" * (101 * 1024 * 1024))
        response = self._upload(doc.id, "Huge.pdf", huge)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_and_detail_include_attachment_metadata(self):
        self._mock_s3()
        doc = self._create_doc()
        self._upload(doc.id, "Client_Letter.pdf", _minimal_pdf_bytes())

        listing = self.client.get("/api/correspondence-documents/")
        result = listing.data["data"]["results"][0]
        self.assertEqual(result["attachment_count"], 1)
        self.assertEqual(result["latest_attachment"]["file_name"], "Client_Letter.pdf")

        detail = self.client.get(f"/api/correspondence-documents/{doc.id}/")
        self.assertEqual(len(detail.data["data"]["attachments"]), 1)
        self.assertIn("download_url", detail.data["data"]["attachments"][0])

    def test_download_attachment(self):
        mock_client = self._mock_s3()
        doc = self._create_doc()
        uploaded = self._upload(doc.id, "Client_Letter.pdf", _minimal_pdf_bytes())
        attachment_id = uploaded.data["data"]["id"]

        response = self.client.get(
            f"/api/correspondence-documents/attachments/{attachment_id}/download/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["download_url"], "https://signed.example.com/download")
        mock_client.generate_presigned_url.assert_called()

    def test_delete_attachment(self):
        mock_client = self._mock_s3()
        doc = self._create_doc()
        uploaded = self._upload(doc.id, "Client_Letter.pdf", _minimal_pdf_bytes())
        attachment_id = uploaded.data["data"]["id"]

        response = self.client.delete(
            f"/api/correspondence-documents/attachments/{attachment_id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(
            CorrespondenceDocumentAttachment.objects.filter(pk=attachment_id).exists()
        )
        mock_client.delete_object.assert_called_once()

    def test_version_upload(self):
        mock_client = self._mock_s3()
        doc = self._create_doc()
        first = self._upload(doc.id, "Client_Letter.pdf", _minimal_pdf_bytes())
        attachment_id = first.data["data"]["id"]

        second = self.client.patch(
            f"/api/correspondence-documents/attachments/{attachment_id}/",
            {"file": _uploaded_file("Client_Letter.pdf", _minimal_pdf_bytes())},
            format="multipart",
        )
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.data["data"]["document_version"], 2)
        new_attachment = CorrespondenceDocumentAttachment.objects.get(
            pk=second.data["data"]["id"]
        )
        self.assertIn("_v2.pdf", new_attachment.s3_key)
        self.assertEqual(mock_client.upload_fileobj.call_count, 2)

    def test_permission_denied_for_unassigned_user(self):
        self._mock_s3()
        doc = self._create_doc()
        outsider = User.objects.create_user("corr_outsider", password="testpass123")
        se_group, _ = Group.objects.get_or_create(name="Site Engineer")
        outsider.groups.add(se_group)
        authenticate_client(self.client, username="corr_outsider", password="testpass123")

        response = self._upload(doc.id, "Client_Letter.pdf", _minimal_pdf_bytes())
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("correspondence.services.notifications.send_websocket_notification")
    def test_notification_generation(self, mock_ws):
        self._mock_s3()
        self.project.team_lead = User.objects.create_user("corr_tl", password="testpass123")
        self.project.save()
        doc = self._create_doc()
        with self.captureOnCommitCallbacks(execute=True):
            response = self._upload(doc.id, "Client_Letter.pdf", _minimal_pdf_bytes())
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            Notification.objects.filter(
                notification_type="CORRESPONDENCE_ATTACHMENT",
                user=self.project.team_lead,
            ).exists()
        )
        mock_ws.assert_called()
