"""API tests for optional historical correspondence comments."""

from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from core.test_auth import authenticate_client

from .controllers.comment_serializer import COMMENT_MAX_LENGTH
from .models.comment import CorrespondenceComment
from .models.correspondence import CorrespondenceDocument

User = get_user_model()


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "correspondence-comments-tests",
        }
    }
)
class CorrespondenceCommentAPITest(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = authenticate_client(
            self.client,
            username="comment_user",
            password="testpass123",
        )
        self.user.first_name = "Test"
        self.user.last_name = "Commenter"
        self.user.save(update_fields=["first_name", "last_name"])
        self.client_doc = self._create_document(
            "Comments Client Project",
            CorrespondenceDocument.TYPE_CLIENT,
        )
        self.contractor_doc = self._create_document(
            "Comments Contractor Project",
            CorrespondenceDocument.TYPE_CONTRACTOR,
        )

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _create_document(
        self,
        project_name,
        correspondence_type,
        *,
        flow_direction=CorrespondenceDocument.FLOW_INBOUND,
        recipient_type=None,
    ):
        return CorrespondenceDocument.objects.create(
            project_name=project_name,
            month=8,
            year=2026,
            correspondence_type=correspondence_type,
            sr_no=1,
            description="Comment test document",
            received_date=date(2026, 8, 1),
            flow_direction=flow_direction,
            recipient_type=recipient_type,
        )

    @staticmethod
    def _canonical_url(document):
        return f"/api/correspondence-documents/{document.id}/comments/"

    @staticmethod
    def _legacy_url(document):
        return f"/api/correspondence/{document.id}/comments/"

    @patch(
        "correspondence.controllers.correspondence_controller."
        "schedule_billing_update_notification_for_instance"
    )
    def test_client_and_contractor_creation_remains_optional(self, mock_schedule):
        for index, correspondence_type in enumerate(
            (
                CorrespondenceDocument.TYPE_CLIENT,
                CorrespondenceDocument.TYPE_CONTRACTOR,
            ),
            start=1,
        ):
            with self.subTest(correspondence_type=correspondence_type):
                response = self.client.post(
                    "/api/correspondence-documents/",
                    {
                        "project_name": f"Optional Comments {index}",
                        "month": 8,
                        "year": 2026,
                        "correspondence_type": correspondence_type,
                        "description": "Created without comments",
                        "received_date": "2026-08-02",
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                self.assertNotIn("comments", response.data["data"])
                self.assertNotIn("comments_count", response.data["data"])

    def test_create_one_comment_uses_authenticated_user_and_trimmed_text(self):
        response = self.client.post(
            self._canonical_url(self.client_doc),
            {"comment": "  First historical note.  "},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["message"], "Comment added successfully.")
        self.assertEqual(
            set(response.data["data"]),
            {"id", "comment", "commented_by", "created_at"},
        )
        self.assertEqual(response.data["data"]["comment"], "First historical note.")
        self.assertEqual(
            response.data["data"]["commented_by"],
            {"id": self.user.id, "name": "Test Commenter"},
        )

        comment = CorrespondenceComment.objects.get()
        self.assertEqual(comment.correspondence, self.client_doc)
        self.assertEqual(comment.commented_by, self.user)

    def test_multiple_comments_are_returned_chronologically(self):
        later = CorrespondenceComment.objects.create(
            correspondence=self.client_doc,
            comment="Later",
            commented_by=self.user,
        )
        earlier = CorrespondenceComment.objects.create(
            correspondence=self.client_doc,
            comment="Earlier",
            commented_by=self.user,
        )
        now = timezone.now()
        CorrespondenceComment.objects.filter(pk=earlier.pk).update(
            created_at=now - timedelta(days=1)
        )
        CorrespondenceComment.objects.filter(pk=later.pk).update(created_at=now)
        CorrespondenceComment.objects.create(
            correspondence=self.client_doc,
            comment="Inactive",
            commented_by=self.user,
            is_active=False,
        )

        response = self.client.get(self._canonical_url(self.client_doc))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Comments retrieved successfully.")
        self.assertEqual(
            [item["comment"] for item in response.data["data"]],
            ["Earlier", "Later"],
        )

    def test_contractor_comments_are_allowed(self):
        response = self.client.post(
            self._canonical_url(self.contractor_doc),
            {"comment": "Contractor note"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_whitespace_comment_returns_exact_error_payload(self):
        response = self.client.post(
            self._canonical_url(self.client_doc),
            {"comment": " \t\n "},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "success": False,
                "message": "Comment cannot be empty.",
                "errors": [
                    {
                        "field": "comment",
                        "message": "Comment cannot be empty.",
                    }
                ],
            },
        )

    def test_unknown_write_fields_are_rejected(self):
        for field in ("user_id", "commented_by", "status", "is_active"):
            with self.subTest(field=field):
                response = self.client.post(
                    self._canonical_url(self.client_doc),
                    {"comment": "Valid note", field: "forged"},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data["errors"][0]["field"], field)
        self.assertEqual(CorrespondenceComment.objects.count(), 0)

    def test_comment_length_is_validated_by_serializer(self):
        response = self.client.post(
            self._canonical_url(self.client_doc),
            {"comment": "x" * (COMMENT_MAX_LENGTH + 1)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(CorrespondenceComment.objects.exists())

    def test_authenticated_user_without_role_can_get_and_post(self):
        roleless = User.objects.create_user(
            username="roleless_commenter",
            password="testpass123",
        )
        authenticate_client(
            self.client,
            username=roleless.username,
            password="testpass123",
        )

        post_response = self.client.post(
            self._canonical_url(self.client_doc),
            {"comment": "Roleless user note"},
            format="json",
        )
        get_response = self.client.get(self._canonical_url(self.client_doc))

        self.assertEqual(post_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)

    def test_unauthenticated_post_is_denied(self):
        response = APIClient().post(
            self._canonical_url(self.client_doc),
            {"comment": "Anonymous note"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(CorrespondenceComment.objects.exists())

    def test_scl_outbound_get_and_post_return_exact_guard(self):
        scl_document = self._create_document(
            "SCL Delivered Comments Project",
            CorrespondenceDocument.TYPE_CLIENT,
            flow_direction=CorrespondenceDocument.FLOW_OUTBOUND_SCL,
            recipient_type=CorrespondenceDocument.RECIPIENT_CLIENT,
        )
        expected = {
            "success": False,
            "message": "Comments are not available for SCL Delivered correspondence.",
        }

        get_response = self.client.get(self._canonical_url(scl_document))
        post_response = self.client.post(
            self._canonical_url(scl_document),
            {"comment": "Must be rejected"},
            format="json",
        )

        self.assertEqual(get_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(post_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(get_response.data, expected)
        self.assertEqual(post_response.data, expected)

    def test_other_agency_style_document_is_rejected(self):
        other_agency = self._create_document(
            "Other Agency Comments Project",
            CorrespondenceDocument.TYPE_CLIENT,
        )
        CorrespondenceDocument.objects.filter(pk=other_agency.pk).update(
            correspondence_type=CorrespondenceDocument.TYPE_OTHER_AGENCY
        )

        for method in ("get", "post"):
            with self.subTest(method=method):
                call = getattr(self.client, method)
                kwargs = (
                    {"data": {"comment": "Must be rejected"}, "format": "json"}
                    if method == "post"
                    else {}
                )
                response = call(self._canonical_url(other_agency), **kwargs)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn(
                    "only available for inbound CLIENT and CONTRACTOR",
                    response.data["message"],
                )

    def test_legacy_and_canonical_routes_share_comment_history(self):
        created = self.client.post(
            self._legacy_url(self.client_doc),
            {"comment": "Created through legacy route"},
            format="json",
        )
        listed = self.client.get(self._canonical_url(self.client_doc))

        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(
            listed.data["data"][0]["comment"],
            "Created through legacy route",
        )

        canonical_create = self.client.post(
            self._canonical_url(self.client_doc),
            {"comment": "Created through canonical route"},
            format="json",
        )
        legacy_list = self.client.get(self._legacy_url(self.client_doc))
        self.assertEqual(canonical_create.status_code, status.HTTP_201_CREATED)
        self.assertEqual(legacy_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(legacy_list.data["data"]), 2)

    def test_list_and_detail_contracts_do_not_include_comments(self):
        CorrespondenceComment.objects.create(
            correspondence=self.client_doc,
            comment="Hidden from existing serializers",
            commented_by=self.user,
        )
        cache.clear()

        list_response = self.client.get("/api/correspondence-documents/")
        detail_response = self.client.get(
            f"/api/correspondence-documents/{self.client_doc.id}/"
        )

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        for item in list_response.data["data"]["results"]:
            self.assertNotIn("comments", item)
            self.assertNotIn("comments_count", item)
        self.assertNotIn("comments", detail_response.data["data"])
        self.assertNotIn("comments_count", detail_response.data["data"])

    def test_list_query_count_is_unaffected_by_comment_volume(self):
        cache.clear()
        with CaptureQueriesContext(connection) as baseline_queries:
            baseline = self.client.get("/api/correspondence-documents/")
        self.assertEqual(baseline.status_code, status.HTTP_200_OK)
        baseline_count = len(baseline_queries)

        CorrespondenceComment.objects.bulk_create(
            [
                CorrespondenceComment(
                    correspondence=self.client_doc,
                    comment=f"Volume comment {index}",
                    commented_by=self.user,
                )
                for index in range(50)
            ]
        )
        cache.clear()
        with CaptureQueriesContext(connection) as volume_queries:
            with_comments = self.client.get("/api/correspondence-documents/")

        self.assertEqual(with_comments.status_code, status.HTTP_200_OK)
        self.assertEqual(len(volume_queries), baseline_count)
