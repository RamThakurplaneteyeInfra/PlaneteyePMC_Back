"""Tests for feedback_management API (S3 upload mocked)."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import UserProfile
from feedback_management.models import FeedbackAuditLog, ProjectFeedback
from projects.models import Project

User = get_user_model()


def _png(name="error.png"):
    return SimpleUploadedFile(
        name,
        b"\x89PNG\r\n\x1a\n" + b"0" * 32,
        content_type="image/png",
    )


def _fake_upload(**kwargs):
    return {
        "s3_key": f"feedback/{kwargs['project_id']}/{kwargs['year']}/{kwargs['month']:02d}/abcd.png",
        "attachment_url": "https://pmcproject.s3.ap-south-1.amazonaws.com/feedback/x.png",
        "attachment_name": "error.png",
        "attachment_size": 40,
        "attachment_type": "image/png",
    }


class FeedbackAPITest(APITestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Satis Thane FB", status="active")
        self.other = Project.objects.create(name="Other FB Project", status="active")

        g_tl, _ = Group.objects.get_or_create(name="Team Leader")
        g_se, _ = Group.objects.get_or_create(name="Site Engineer")
        g_head, _ = Group.objects.get_or_create(name="PMC Head")

        self.tl = User.objects.create_user(username="fb_tl", password="testpass123")
        self.tl.groups.add(g_tl)
        UserProfile.objects.get_or_create(user=self.tl)
        self.project.team_lead = self.tl
        self.project.save(update_fields=["team_lead", "updated_at"])

        self.se = User.objects.create_user(username="fb_se", password="testpass123")
        self.se.groups.add(g_se)
        UserProfile.objects.get_or_create(user=self.se)
        self.project.site_engineer = self.se
        self.project.save(update_fields=["site_engineer", "updated_at"])

        self.head = User.objects.create_user(username="fb_head", password="testpass123")
        self.head.groups.add(g_head)
        UserProfile.objects.get_or_create(user=self.head)

        self.outsider = User.objects.create_user(username="fb_outsider", password="testpass123")
        self.outsider.groups.add(g_tl)
        UserProfile.objects.get_or_create(user=self.outsider)

        self._login(self.tl)

    def _login(self, user):
        resp = self.client.post(
            "/api/token/",
            {"username": user.username, "password": "testpass123"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK, resp.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def _create(self, **overrides):
        payload = {
            "project": self.project.id,
            "issue_title": "Dashboard loading issue",
            "issue_description": "Progress graph is not loading.",
            "priority": "High",
        }
        payload.update(overrides)
        return self.client.post("/api/project-feedback/", payload, format="multipart")

    @patch("feedback_management.views.notify_feedback_created")
    def test_team_leader_create_retrieve_list(self, mock_notify):
        resp = self._create()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        data = resp.data["data"]
        self.assertEqual(data["project"]["id"], self.project.id)
        self.assertEqual(data["priority"], "High")
        self.assertEqual(data["status"], "Open")
        self.assertEqual(data["reported_by"]["username"], "fb_tl")
        self.assertIsNone(data["attachment"])
        fid = data["id"]
        mock_notify.assert_called_once()

        self.assertTrue(
            FeedbackAuditLog.objects.filter(action="created", feedback_id_snapshot=fid).exists()
        )

        detail = self.client.get(f"/api/project-feedback/{fid}/")
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data["data"]["id"], fid)

        listing = self.client.get("/api/project-feedback/")
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        results = listing.data["data"]["results"]
        self.assertGreaterEqual(len(results), 1)

    @patch("feedback_management.views.notify_feedback_created")
    def test_site_engineer_readonly(self, _mock_notify):
        created = self._create()
        fid = created.data["data"]["id"]

        self._login(self.se)
        # Can view
        listing = self.client.get(f"/api/project-feedback/?project={self.project.id}")
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(listing.data["data"]["results"]), 1)

        # Cannot create
        blocked = self._create()
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)

        # Cannot update
        upd = self.client.patch(
            f"/api/project-feedback/{fid}/", {"remarks": "x"}, format="multipart"
        )
        self.assertEqual(upd.status_code, status.HTTP_403_FORBIDDEN)

        # Cannot delete
        dele = self.client.delete(f"/api/project-feedback/{fid}/")
        self.assertEqual(dele.status_code, status.HTTP_403_FORBIDDEN)

    @patch("feedback_management.views.notify_feedback_created")
    def test_update_priority_and_status_audit(self, _mock_notify):
        fid = self._create().data["data"]["id"]

        upd = self.client.patch(
            f"/api/project-feedback/{fid}/",
            {"priority": "Critical", "status": "In Progress"},
            format="multipart",
        )
        self.assertEqual(upd.status_code, status.HTTP_200_OK, upd.data)
        self.assertEqual(upd.data["data"]["priority"], "Critical")
        self.assertEqual(upd.data["data"]["status"], "In Progress")
        self.assertTrue(
            FeedbackAuditLog.objects.filter(action="priority_changed", feedback_id_snapshot=fid).exists()
        )
        self.assertTrue(
            FeedbackAuditLog.objects.filter(action="status_changed", feedback_id_snapshot=fid).exists()
        )

    @patch("feedback_management.views.notify_feedback_created")
    def test_pmc_head_status_endpoint_and_view_all(self, _mock_notify):
        fid = self._create().data["data"]["id"]

        self._login(self.head)
        # PMC Head sees all projects
        listing = self.client.get("/api/project-feedback/")
        self.assertEqual(listing.status_code, status.HTTP_200_OK)

        resolved = self.client.patch(
            f"/api/project-feedback/{fid}/status/",
            {"status": "Resolved"},
            format="json",
        )
        self.assertEqual(resolved.status_code, status.HTTP_200_OK, resolved.data)
        self.assertEqual(resolved.data["data"]["status"], "Resolved")
        self.assertIsNotNone(resolved.data["data"]["resolved_at"])

    @patch("feedback_management.views.notify_feedback_created")
    def test_delete_by_team_leader(self, _mock_notify):
        fid = self._create().data["data"]["id"]
        dele = self.client.delete(f"/api/project-feedback/{fid}/")
        self.assertEqual(dele.status_code, status.HTTP_200_OK, dele.data)
        self.assertFalse(ProjectFeedback.objects.get(pk=fid).is_active)
        # Soft-deleted rows disappear from list
        listing = self.client.get("/api/project-feedback/")
        ids = [r["id"] for r in listing.data["data"]["results"]]
        self.assertNotIn(fid, ids)

    @patch("feedback_management.views.notify_feedback_created")
    def test_filter_search_order(self, _mock_notify):
        self._create(issue_title="Alpha issue", priority="Low")
        self._create(issue_title="Beta issue", priority="Critical")

        by_priority = self.client.get("/api/project-feedback/?priority=Critical")
        self.assertEqual(by_priority.status_code, status.HTTP_200_OK)
        self.assertTrue(all(r["priority"] == "Critical" for r in by_priority.data["data"]["results"]))

        search = self.client.get("/api/project-feedback/?search=Alpha")
        titles = [r["issue_title"] for r in search.data["data"]["results"]]
        self.assertIn("Alpha issue", titles)

        ordered = self.client.get("/api/project-feedback/?ordering=-priority_rank")
        results = ordered.data["data"]["results"]
        self.assertEqual(results[0]["priority"], "Critical")

        by_project = self.client.get(f"/api/project-feedback/?project={self.project.id}")
        self.assertEqual(by_project.status_code, status.HTTP_200_OK)

    @patch("feedback_management.views.upload_feedback_attachment", side_effect=_fake_upload)
    @patch("feedback_management.views.notify_feedback_created")
    def test_attachment_upload(self, _mock_notify, _mock_up):
        resp = self._create(attachment=_png())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        attachment = resp.data["data"]["attachment"]
        self.assertIsNotNone(attachment)
        self.assertEqual(attachment["type"], "image/png")
        self.assertTrue(attachment["url"])

    def test_invalid_attachment_rejected(self):
        bad = SimpleUploadedFile("bad.txt", b"hello", content_type="text/plain")
        resp = self._create(attachment=bad)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(resp.data["success"])

    def test_missing_required_fields(self):
        resp = self.client.post(
            "/api/project-feedback/",
            {"project": self.project.id},
            format="multipart",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("feedback_management.views.notify_feedback_created")
    def test_missing_attachment_is_allowed(self, _mock_notify):
        # Attachment is optional — create must succeed without a file.
        resp = self._create()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)
        self.assertIsNone(resp.data["data"]["attachment"])

    def test_large_file_rejected(self):
        from django.core.exceptions import ValidationError
        from services.s3_feedback_attachments import MAX_UPLOAD_SIZE, validate_attachment

        big = SimpleUploadedFile(
            "huge.png",
            b"\x89PNG\r\n\x1a\n" + b"0" * 32,
            content_type="image/png",
        )
        # Report an oversized file without allocating the bytes. (A multipart
        # round-trip would recompute the real size, so assert at the validator.)
        big.size = MAX_UPLOAD_SIZE + 1
        with self.assertRaises(ValidationError):
            validate_attachment(big)

    @patch("feedback_management.views.delete_feedback_attachment")
    @patch("feedback_management.views.upload_feedback_attachment")
    @patch("feedback_management.views.notify_feedback_created")
    def test_update_replaces_attachment_and_deletes_old(self, _mock_notify, mock_up, mock_del):
        mock_up.side_effect = [
            {
                "s3_key": "feedback/1/2026/07/OLDKEY.png",
                "attachment_url": "https://pmcproject.s3.ap-south-1.amazonaws.com/feedback/1/2026/07/OLDKEY.png",
                "attachment_name": "old.png",
                "attachment_size": 40,
                "attachment_type": "image/png",
            },
            {
                "s3_key": "feedback/1/2026/07/NEWKEY.png",
                "attachment_url": "https://pmcproject.s3.ap-south-1.amazonaws.com/feedback/1/2026/07/NEWKEY.png",
                "attachment_name": "new.png",
                "attachment_size": 55,
                "attachment_type": "image/png",
            },
        ]

        fid = self._create(attachment=_png("old.png")).data["data"]["id"]

        upd = self.client.patch(
            f"/api/project-feedback/{fid}/",
            {"attachment": _png("new.png")},
            format="multipart",
        )
        self.assertEqual(upd.status_code, status.HTTP_200_OK, upd.data)
        self.assertEqual(upd.data["data"]["attachment"]["name"], "new.png")
        # Old S3 object removed, mirroring Testing Documents behaviour.
        mock_del.assert_called_once_with("feedback/1/2026/07/OLDKEY.png")
        self.assertTrue(
            FeedbackAuditLog.objects.filter(
                action="attachment_updated", feedback_id_snapshot=fid
            ).exists()
        )

    @patch("feedback_management.views.delete_feedback_attachment")
    @patch("feedback_management.views.upload_feedback_attachment", side_effect=_fake_upload)
    @patch("feedback_management.views.notify_feedback_created")
    def test_delete_removes_s3_attachment(self, _mock_notify, _mock_up, mock_del):
        fid = self._create(attachment=_png()).data["data"]["id"]
        dele = self.client.delete(f"/api/project-feedback/{fid}/")
        self.assertEqual(dele.status_code, status.HTTP_200_OK, dele.data)
        mock_del.assert_called_once()
        called_key = mock_del.call_args.args[0]
        self.assertTrue(called_key.startswith("feedback/"))

    @patch(
        "feedback_management.views.upload_feedback_attachment",
        side_effect=Exception("AWS connection failure"),
    )
    @patch("feedback_management.views.notify_feedback_created")
    def test_s3_upload_failure_rolls_back(self, mock_notify, _mock_up):
        resp = self._create(attachment=_png())
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(resp.data["success"])
        # No feedback row persisted, and no notification sent.
        self.assertEqual(ProjectFeedback.objects.count(), 0)
        mock_notify.assert_not_called()

    @patch("feedback_management.views.upload_feedback_attachment", side_effect=_fake_upload)
    @patch("feedback_management.views.notify_feedback_created")
    def test_attachment_permission_denied_for_site_engineer(self, _mock_notify, _mock_up):
        self._login(self.se)
        resp = self._create(attachment=_png())
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthorized(self):
        self.client.credentials()
        resp = self.client.get("/api/project-feedback/")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
