"""Tests for Tutorial Video Management API (section-aware)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from core.cache_keys import build_rbac_list_cache_key, get_list_cache_version
from core.models import BusinessAuditLog
from core.test_auth import authenticate_client
from tutorial_videos.ffmpeg_service import OptimizeResult, VideoProcessingError
from tutorial_videos.models import TutorialVideo
from tutorial_videos.processing import (
    CACHE_PREFIX,
    process_tutorial_video,
    soft_delete_tutorial_video,
)
from tutorial_videos.sections import TUTORIAL_SECTIONS
from tutorial_videos.video_executor import reset_metrics_for_tests


def _minimal_mp4_bytes() -> bytes:
    return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + (b"\x00" * 64)


def _uploaded_video(name: str = "demo.mp4", content: bytes | None = None) -> SimpleUploadedFile:
    return SimpleUploadedFile(
        name,
        content if content is not None else _minimal_mp4_bytes(),
        content_type="video/mp4",
    )


def _make_video(**kwargs):
    defaults = {
        "title": "Video",
        "description": "",
        "section": "overview",
        "status": TutorialVideo.STATUS_READY,
        "optimized_s3_key": "tutorial/optimized/x.mp4",
        "video_url": "https://example.com/x.mp4",
    }
    defaults.update(kwargs)
    return TutorialVideo.objects.create(**defaults)


S3_SETTINGS = {
    "AWS_ACCESS_KEY_ID": "test-key",
    "AWS_SECRET_ACCESS_KEY": "test-secret",
    "AWS_STORAGE_BUCKET_NAME": "pmcproject",
    "AWS_S3_REGION_NAME": "ap-south-1",
    "AWS_S3_CUSTOM_DOMAIN": "",
    "TUTORIAL_VIDEOS_S3_PREFIX": "tutorial",
    "TUTORIAL_VIDEO_INLINE": True,
    "TUTORIAL_VIDEO_MAX_UPLOAD_MB": 10,
    "TUTORIAL_VIDEO_MAX_WORKERS": 1,
    "TUTORIAL_VIDEO_MAX_PENDING": 5,
    "TUTORIAL_VIDEO_USE_PRESIGNED": False,
}


@override_settings(**S3_SETTINGS)
class TutorialVideoValidationUnitTests(SimpleTestCase):
    def test_sniff_mp4(self):
        from services.s3_tutorial_videos import sniff_looks_like_video

        self.assertTrue(sniff_looks_like_video(_minimal_mp4_bytes(), filename="a.mp4"))
        self.assertFalse(sniff_looks_like_video(b"not-a-video", filename="a.mp4"))

    def test_keys_under_tutorial_prefix(self):
        from services.s3_tutorial_videos import build_optimized_key, build_temp_key

        self.assertTrue(build_temp_key(filename="x.mp4").startswith("tutorial/temporary/"))
        self.assertTrue(build_optimized_key().startswith("tutorial/optimized/"))

    def test_sections_catalog(self):
        self.assertIn("meeting_documents", TUTORIAL_SECTIONS)
        self.assertEqual(TUTORIAL_SECTIONS["dpr_review"], "DPR Review")


@override_settings(**S3_SETTINGS)
class TutorialVideoAPITests(APITestCase):
    def setUp(self):
        cache.clear()
        reset_metrics_for_tests()
        self.pmc_group, _ = Group.objects.get_or_create(name="PMC Head")
        self.se_group, _ = Group.objects.get_or_create(name="Site Engineer")
        self.user = authenticate_client(self.client, username="tv_admin", password="x")
        self.user.groups.add(self.pmc_group)
        self.url = "/api/tutorial-videos/"

    def _mock_s3_upload(self):
        return patch(
            "services.s3_tutorial_videos.upload_bytes_or_fileobj",
            return_value=128,
        )

    def _mock_s3_ready(self):
        return patch(
            "services.s3_tutorial_videos.check_s3_ready",
            return_value=(True, None),
        )

    def _mock_process_noop(self):
        return patch(
            "tutorial_videos.processing.process_tutorial_video",
            return_value=None,
        )

    def _upload_payload(self, **overrides):
        data = {
            "title": "How to Upload Meeting Documents",
            "description": "Tutorial explaining meeting documents.",
            "section": "meeting_documents",
            "upload": _uploaded_video(),
        }
        data.update(overrides)
        return data

    def test_valid_upload_with_section_returns_202(self):
        with self._mock_s3_ready(), self._mock_s3_upload(), self._mock_process_noop():
            resp = self.client.post(self.url, self._upload_payload(), format="multipart")
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        data = resp.data["data"]
        self.assertEqual(data["status"], "processing")
        self.assertEqual(data["section"], "meeting_documents")
        self.assertEqual(data["section_name"], "Meeting Documents")
        self.assertNotIn("video_url", data)
        video = TutorialVideo.objects.get(pk=data["id"])
        self.assertEqual(video.section, "meeting_documents")
        self.assertTrue(
            BusinessAuditLog.objects.filter(
                entity_type=BusinessAuditLog.ENTITY_TUTORIAL_VIDEO,
                action=BusinessAuditLog.ACTION_UPLOADED,
                entity_id=str(video.pk),
            ).exists()
        )

    def test_create_invalid_section(self):
        with self._mock_s3_ready():
            resp = self.client.post(
                self.url,
                self._upload_payload(section="not_a_real_section"),
                format="multipart",
            )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_missing_section(self):
        with self._mock_s3_ready():
            resp = self.client.post(
                self.url,
                {
                    "title": "No section",
                    "description": "x",
                    "upload": _uploaded_video(),
                },
                format="multipart",
            )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        errors = resp.data.get("errors", {})
        if isinstance(errors, list):
            fields = {e.get("field") for e in errors if isinstance(e, dict)}
            self.assertIn("section", fields)
        else:
            self.assertIn("section", errors)

    def test_missing_title(self):
        with self._mock_s3_ready():
            resp = self.client.post(
                self.url,
                self._upload_payload(title=""),
                format="multipart",
            )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_upload(self):
        with self._mock_s3_ready():
            resp = self.client.post(
                self.url,
                {
                    "title": "No file",
                    "section": "overview",
                },
                format="multipart",
            )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_file_type(self):
        with self._mock_s3_ready():
            bad = SimpleUploadedFile("hack.exe", b"MZ\x90\x00" + b"\x00" * 40)
            resp = self.client.post(
                self.url,
                self._upload_payload(title="Bad", upload=bad, section="overview"),
                format="multipart",
            )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_oversized_video(self):
        with self._mock_s3_ready():
            with patch(
                "services.s3_tutorial_videos.max_upload_bytes",
                return_value=100,
            ):
                big = SimpleUploadedFile(
                    "big.mp4",
                    _minimal_mp4_bytes() + (b"\x00" * 200),
                    content_type="video/mp4",
                )
                resp = self.client.post(
                    self.url,
                    self._upload_payload(title="Big", upload=big, section="overview"),
                    format="multipart",
                )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_without_section_returns_all(self):
        _make_video(title="A", section="meeting_documents", created_by=self.user)
        _make_video(title="B", section="dpr_review", created_by=self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 2)

    def test_list_with_section_filters(self):
        _make_video(title="MD1", section="meeting_documents", created_by=self.user)
        _make_video(title="MD2", section="meeting_documents", created_by=self.user)
        _make_video(title="DPR", section="dpr_review", created_by=self.user)
        resp = self.client.get(self.url + "?section=meeting_documents")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 2)
        sections = {row["section"] for row in resp.data["data"]}
        self.assertEqual(sections, {"meeting_documents"})
        self.assertTrue(all(row["section_name"] == "Meeting Documents" for row in resp.data["data"]))
        titles = {row["title"] for row in resp.data["data"]}
        self.assertNotIn("DPR", titles)

    def test_list_invalid_section_returns_400(self):
        resp = self.client.get(self.url + "?section=invalid_section")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["message"], "Invalid tutorial section.")

    def test_list_pagination_with_section(self):
        for i in range(3):
            _make_video(
                title=f"MD{i}",
                section="meeting_documents",
                created_by=self.user,
            )
        _make_video(title="Other", section="alerts", created_by=self.user)
        resp = self.client.get(self.url + "?section=meeting_documents&page=1&page_size=2")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 3)
        self.assertEqual(len(resp.data["data"]), 2)
        self.assertNotIn("video_url", resp.data["data"][0])

    def test_search_and_ordering_with_section(self):
        _make_video(title="Alpha Meet", section="meeting_documents", created_by=self.user)
        _make_video(title="Beta Meet", section="meeting_documents", created_by=self.user)
        _make_video(title="Alpha DPR", section="dpr_review", created_by=self.user)
        resp = self.client.get(
            self.url + "?section=meeting_documents&search=Alpha&ordering=title"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["data"][0]["title"], "Alpha Meet")

    def test_detail_includes_section(self):
        video = _make_video(
            title="Old",
            description="d",
            section="site_photos",
            created_by=self.user,
        )
        detail = self.client.get(f"{self.url}{video.pk}/")
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data["data"]["section"], "site_photos")
        self.assertEqual(detail.data["data"]["section_name"], "Site Photos")
        self.assertNotIn("video_url", detail.data["data"])

    def test_update_section(self):
        video = _make_video(title="Old", section="meeting_documents", created_by=self.user)
        version_before = get_list_cache_version(CACHE_PREFIX)
        patch = self.client.patch(
            f"{self.url}{video.pk}/",
            {
                "title": "Updated Tutorial",
                "description": "Updated description.",
                "section": "dpr_review",
            },
            format="json",
        )
        self.assertEqual(patch.status_code, status.HTTP_200_OK)
        video.refresh_from_db()
        self.assertEqual(video.section, "dpr_review")
        self.assertEqual(patch.data["data"]["section_name"], "DPR Review")
        self.assertGreaterEqual(get_list_cache_version(CACHE_PREFIX), version_before)
        audit = BusinessAuditLog.objects.filter(
            entity_id=str(video.pk),
            action=BusinessAuditLog.ACTION_UPDATED,
        ).latest("created_at")
        self.assertIn("old_section=meeting_documents", audit.detail)
        self.assertIn("new_section=dpr_review", audit.detail)

    def test_update_invalid_section(self):
        video = _make_video(section="overview", created_by=self.user)
        resp = self.client.patch(
            f"{self.url}{video.pk}/",
            {"section": "nope"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_soft_and_s3_cleanup(self):
        video = _make_video(
            title="Del",
            section="alerts",
            created_by=self.user,
        )
        with patch("services.s3_tutorial_videos.delete_object") as delete_mock:
            resp = self.client.delete(f"{self.url}{video.pk}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        video.refresh_from_db()
        self.assertFalse(video.is_active)
        self.assertEqual(video.status, TutorialVideo.STATUS_DELETED)
        delete_mock.assert_called()

    def test_view_without_section_param(self):
        video = _make_video(
            title="Ready",
            section="portfolio",
            status=TutorialVideo.STATUS_READY,
            optimized_s3_key="tutorial/optimized/r.mp4",
            video_url="https://pmcproject.s3.ap-south-1.amazonaws.com/tutorial/optimized/r.mp4",
            created_by=self.user,
        )
        resp = self.client.get(f"{self.url}{video.pk}/view/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["data"]["video_url"], video.video_url)

    def test_view_processing_conflict(self):
        video = _make_video(
            title="P",
            section="overview",
            status=TutorialVideo.STATUS_PROCESSING,
            optimized_s3_key="",
            video_url="",
            temp_s3_key="tutorial/temporary/x.mp4",
            created_by=self.user,
        )
        resp = self.client.get(f"{self.url}{video.pk}/view/")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_rbac_site_engineer_cannot_upload(self):
        se = User.objects.create_user("tv_se", password="x")
        se.groups.add(self.se_group)
        self.client.force_authenticate(user=se)
        with self._mock_s3_ready():
            resp = self.client.post(
                self.url,
                self._upload_payload(title="Nope", section="overview"),
                format="multipart",
            )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_rbac_site_engineer_can_list_section(self):
        _make_video(title="Visible", section="alerts")
        se = User.objects.create_user("tv_se2", password="x")
        se.groups.add(self.se_group)
        self.client.force_authenticate(user=se)
        resp = self.client.get(self.url + "?section=alerts")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 1)

    def test_rbac_site_engineer_and_manager_can_view_playback(self):
        video = _make_video(
            title="Play",
            section="overview",
            status=TutorialVideo.STATUS_READY,
            created_by=self.user,
        )
        se = User.objects.create_user("tv_se_view", password="x")
        se.groups.add(self.se_group)
        self.client.force_authenticate(user=se)
        resp = self.client.get(f"{self.url}{video.pk}/view/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("video_url", resp.data["data"])

        mgr_group, _ = Group.objects.get_or_create(name="PMC Manager")
        mgr = User.objects.create_user("tv_mgr_view", password="x")
        mgr.groups.add(mgr_group)
        self.client.force_authenticate(user=mgr)
        resp2 = self.client.get(f"{self.url}{video.pk}/")
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        list_resp = self.client.get(self.url + "?section=overview")
        self.assertEqual(list_resp.status_code, status.HTTP_200_OK)

    def test_cache_isolation_between_sections(self):
        _make_video(title="MD", section="meeting_documents", created_by=self.user)
        _make_video(title="DPR", section="dpr_review", created_by=self.user)

        # Warm both caches
        r1 = self.client.get(self.url + "?section=meeting_documents")
        r2 = self.client.get(self.url + "?section=dpr_review")
        self.assertEqual(r1.data["count"], 1)
        self.assertEqual(r2.data["count"], 1)
        self.assertEqual(r1.data["data"][0]["section"], "meeting_documents")
        self.assertEqual(r2.data["data"][0]["section"], "dpr_review")

        # Keys must differ (query string included)
        from rest_framework.test import APIRequestFactory
        from rest_framework.request import Request

        factory = APIRequestFactory()
        req_md = Request(factory.get(self.url + "?section=meeting_documents"))
        req_md.user = self.user
        req_dpr = Request(factory.get(self.url + "?section=dpr_review"))
        req_dpr.user = self.user
        key_md = build_rbac_list_cache_key(CACHE_PREFIX, req_md)
        key_dpr = build_rbac_list_cache_key(CACHE_PREFIX, req_dpr)
        self.assertNotEqual(key_md, key_dpr)

    def test_cache_invalidation_on_create(self):
        version_before = get_list_cache_version(CACHE_PREFIX)
        with self._mock_s3_ready(), self._mock_s3_upload(), self._mock_process_noop():
            self.client.post(
                self.url,
                self._upload_payload(title="Cache", section="alerts"),
                format="multipart",
            )
        self.assertGreater(get_list_cache_version(CACHE_PREFIX), version_before)

    def test_duplicate_uploads_create_distinct_records(self):
        with self._mock_s3_ready(), self._mock_s3_upload(), self._mock_process_noop():
            r1 = self.client.post(
                self.url, self._upload_payload(title="Same"), format="multipart"
            )
            r2 = self.client.post(
                self.url, self._upload_payload(title="Same"), format="multipart"
            )
        self.assertEqual(r1.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(r2.status_code, status.HTTP_202_ACCEPTED)
        self.assertNotEqual(r1.data["data"]["id"], r2.data["data"]["id"])

    def test_queue_full_rejects_upload(self):
        with self._mock_s3_ready(), patch(
            "tutorial_videos.video_executor.queue_is_full", return_value=True
        ):
            resp = self.client.post(
                self.url,
                self._upload_payload(title="Q", section="overview"),
                format="multipart",
            )
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)


@override_settings(**S3_SETTINGS)
class TutorialVideoProcessingTests(TestCase):
    def setUp(self):
        reset_metrics_for_tests()
        self.user = User.objects.create_user("tv_proc", password="x")

    def test_successful_processing_invalidates_section_cache(self):
        video = TutorialVideo.objects.create(
            title="Proc",
            section="meeting_documents",
            status=TutorialVideo.STATUS_PROCESSING,
            temp_s3_key="tutorial/temporary/src.mp4",
            original_file_size=1000,
            created_by=self.user,
        )
        version_before = get_list_cache_version(CACHE_PREFIX)

        def fake_download(key, dest):
            Path(dest).write_bytes(_minimal_mp4_bytes())

        with (
            patch("services.s3_tutorial_videos.download_to_path", side_effect=fake_download),
            patch("tutorial_videos.processing.optimize_video") as opt_mock,
            patch("services.s3_tutorial_videos.upload_local_file", return_value=400),
            patch("services.s3_tutorial_videos.delete_object"),
            patch(
                "services.s3_tutorial_videos.build_optimized_key",
                return_value="tutorial/optimized/abc.mp4",
            ),
            patch(
                "services.s3_tutorial_videos.object_url",
                return_value="https://pmcproject.s3.ap-south-1.amazonaws.com/tutorial/optimized/abc.mp4",
            ),
        ):

            def _opt(src, out):
                Path(out).write_bytes(b"mp4data")
                return OptimizeResult(
                    output_path=Path(out),
                    width=1280,
                    height=720,
                    duration=12.5,
                    output_size=400,
                    processing_ms=50,
                )

            opt_mock.side_effect = _opt
            process_tutorial_video(video_id=video.pk)

        video.refresh_from_db()
        self.assertEqual(video.status, TutorialVideo.STATUS_READY)
        self.assertEqual(video.section, "meeting_documents")
        self.assertGreater(get_list_cache_version(CACHE_PREFIX), version_before)
        self.assertTrue(
            BusinessAuditLog.objects.filter(
                entity_type=BusinessAuditLog.ENTITY_TUTORIAL_VIDEO,
                action=BusinessAuditLog.ACTION_COMPLETED,
                entity_id=str(video.pk),
            )
            .filter(detail__contains="section=meeting_documents")
            .exists()
        )

    def test_failed_processing_cleans_temp(self):
        video = TutorialVideo.objects.create(
            title="Fail",
            section="overview",
            status=TutorialVideo.STATUS_PROCESSING,
            temp_s3_key="tutorial/temporary/bad.mp4",
            original_file_size=1000,
            created_by=self.user,
        )

        def fake_download(key, dest):
            Path(dest).write_bytes(_minimal_mp4_bytes())

        with (
            patch("services.s3_tutorial_videos.download_to_path", side_effect=fake_download),
            patch(
                "tutorial_videos.processing.optimize_video",
                side_effect=VideoProcessingError("Video processing failed."),
            ),
            patch("services.s3_tutorial_videos.delete_object") as del_mock,
        ):
            process_tutorial_video(video_id=video.pk)

        video.refresh_from_db()
        self.assertEqual(video.status, TutorialVideo.STATUS_FAILED)
        self.assertEqual(video.temp_s3_key, "tutorial/temporary/bad.mp4")
        self.assertIn("failed", video.processing_error.lower())
        del_mock.assert_not_called()

    def test_soft_delete_removes_keys(self):
        video = TutorialVideo.objects.create(
            title="SD",
            section="portfolio",
            status=TutorialVideo.STATUS_READY,
            optimized_s3_key="tutorial/optimized/sd.mp4",
            temp_s3_key="tutorial/temporary/sd.mp4",
            video_url="https://example.com/sd.mp4",
        )
        with patch("services.s3_tutorial_videos.delete_object") as del_mock:
            soft_delete_tutorial_video(video)
        video.refresh_from_db()
        self.assertFalse(video.is_active)
        self.assertEqual(del_mock.call_count, 2)

    def test_concurrent_queue_limit(self):
        from tutorial_videos.exceptions import TutorialVideoQueueFull
        from tutorial_videos.video_executor import METRICS, submit_video_job

        reset_metrics_for_tests()
        with METRICS.lock:
            METRICS.pending = 5
        with self.assertRaises(TutorialVideoQueueFull):
            submit_video_job(lambda video_id: None, video_id=1)
