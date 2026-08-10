"""Tests for Tutorial Video Management API."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import BusinessAuditLog
from core.test_auth import authenticate_client
from tutorial_videos.ffmpeg_service import OptimizeResult, VideoProcessingError
from tutorial_videos.models import TutorialVideo
from tutorial_videos.processing import process_tutorial_video, soft_delete_tutorial_video
from tutorial_videos.video_executor import reset_metrics_for_tests


def _minimal_mp4_bytes() -> bytes:
    # ISO BMFF: size(4) + 'ftyp' + brand — enough for sniff_looks_like_video.
    return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + (b"\x00" * 64)


def _uploaded_video(name: str = "demo.mp4", content: bytes | None = None) -> SimpleUploadedFile:
    return SimpleUploadedFile(
        name,
        content if content is not None else _minimal_mp4_bytes(),
        content_type="video/mp4",
    )


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
        self.assertTrue(build_optimized_key().endswith(".mp4"))


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

    def test_valid_upload_returns_202(self):
        with self._mock_s3_ready(), self._mock_s3_upload(), self._mock_process_noop():
            resp = self.client.post(
                self.url,
                {
                    "title": "How to Create a DPR",
                    "description": "Tutorial for Site Engineers",
                    "upload": _uploaded_video(),
                },
                format="multipart",
            )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertTrue(resp.data["success"])
        self.assertEqual(resp.data["data"]["status"], "processing")
        self.assertEqual(resp.data["data"]["title"], "How to Create a DPR")
        self.assertNotIn("video_url", resp.data["data"])
        video = TutorialVideo.objects.get(pk=resp.data["data"]["id"])
        self.assertEqual(video.status, TutorialVideo.STATUS_PROCESSING)
        self.assertTrue(
            BusinessAuditLog.objects.filter(
                entity_type=BusinessAuditLog.ENTITY_TUTORIAL_VIDEO,
                action=BusinessAuditLog.ACTION_UPLOADED,
                entity_id=str(video.pk),
            ).exists()
        )

    def test_missing_title(self):
        with self._mock_s3_ready():
            resp = self.client.post(
                self.url,
                {"description": "x", "upload": _uploaded_video()},
                format="multipart",
            )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        errors = resp.data.get("errors", {})
        if isinstance(errors, list):
            fields = {e.get("field") for e in errors if isinstance(e, dict)}
            self.assertIn("title", fields)
        else:
            self.assertIn("title", errors)

    def test_missing_upload(self):
        with self._mock_s3_ready():
            resp = self.client.post(
                self.url,
                {"title": "No file"},
                format="multipart",
            )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        errors = resp.data.get("errors", {})
        if isinstance(errors, list):
            fields = {e.get("field") for e in errors if isinstance(e, dict)}
            self.assertIn("upload", fields)
        else:
            self.assertIn("upload", errors)

    def test_invalid_file_type(self):
        with self._mock_s3_ready():
            bad = SimpleUploadedFile("hack.exe", b"MZ\x90\x00" + b"\x00" * 40)
            resp = self.client.post(
                self.url,
                {"title": "Bad", "upload": bad},
                format="multipart",
            )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_oversized_video(self):
        with self._mock_s3_ready():
            # Bypass sniff by patching size on a valid-looking file via mock validate
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
                    {"title": "Big", "upload": big},
                    format="multipart",
                )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_pagination_no_presign(self):
        TutorialVideo.objects.create(
            title="A",
            description="",
            status=TutorialVideo.STATUS_READY,
            optimized_s3_key="tutorial/optimized/a.mp4",
            video_url="https://example.com/a.mp4",
            created_by=self.user,
        )
        TutorialVideo.objects.create(
            title="B",
            description="",
            status=TutorialVideo.STATUS_READY,
            optimized_s3_key="tutorial/optimized/b.mp4",
            video_url="https://example.com/b.mp4",
            created_by=self.user,
        )
        resp = self.client.get(self.url + "?page=1&page_size=1")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["count"], 2)
        self.assertEqual(len(resp.data["data"]), 1)
        row = resp.data["data"][0]
        self.assertIn("title", row)
        self.assertNotIn("video_url", row)

    def test_detail_and_update(self):
        video = TutorialVideo.objects.create(
            title="Old",
            description="d",
            status=TutorialVideo.STATUS_READY,
            optimized_s3_key="tutorial/optimized/x.mp4",
            video_url="https://example.com/x.mp4",
            created_by=self.user,
        )
        detail = self.client.get(f"{self.url}{video.pk}/")
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data["data"]["title"], "Old")
        self.assertNotIn("video_url", detail.data["data"])

        patch = self.client.patch(
            f"{self.url}{video.pk}/",
            {"title": "Updated DPR Tutorial", "description": "Updated description"},
            format="json",
        )
        self.assertEqual(patch.status_code, status.HTTP_200_OK)
        video.refresh_from_db()
        self.assertEqual(video.title, "Updated DPR Tutorial")
        # Cannot change status via patch
        blocked = self.client.patch(
            f"{self.url}{video.pk}/",
            {"status": "failed", "video_url": "https://evil"},
            format="json",
        )
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)
        video.refresh_from_db()
        self.assertEqual(video.status, TutorialVideo.STATUS_READY)
        self.assertEqual(video.video_url, "https://example.com/x.mp4")

    def test_delete_soft_and_s3_cleanup(self):
        video = TutorialVideo.objects.create(
            title="Del",
            status=TutorialVideo.STATUS_READY,
            optimized_s3_key="tutorial/optimized/del.mp4",
            video_url="https://example.com/del.mp4",
            created_by=self.user,
        )
        with patch("services.s3_tutorial_videos.delete_object") as delete_mock:
            resp = self.client.delete(f"{self.url}{video.pk}/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        video.refresh_from_db()
        self.assertFalse(video.is_active)
        self.assertEqual(video.status, TutorialVideo.STATUS_DELETED)
        delete_mock.assert_called()

    def test_view_processing_conflict(self):
        video = TutorialVideo.objects.create(
            title="P",
            status=TutorialVideo.STATUS_PROCESSING,
            temp_s3_key="tutorial/temporary/x.mp4",
            created_by=self.user,
        )
        resp = self.client.get(f"{self.url}{video.pk}/view/")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.data["data"]["status"], "processing")

    def test_view_failed_conflict(self):
        video = TutorialVideo.objects.create(
            title="F",
            status=TutorialVideo.STATUS_FAILED,
            created_by=self.user,
        )
        resp = self.client.get(f"{self.url}{video.pk}/view/")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_view_ready_returns_url(self):
        video = TutorialVideo.objects.create(
            title="Ready",
            status=TutorialVideo.STATUS_READY,
            optimized_s3_key="tutorial/optimized/r.mp4",
            video_url="https://pmcproject.s3.ap-south-1.amazonaws.com/tutorial/optimized/r.mp4",
            created_by=self.user,
        )
        resp = self.client.get(f"{self.url}{video.pk}/view/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            resp.data["data"]["video_url"],
            video.video_url,
        )

    def test_rbac_site_engineer_cannot_upload(self):
        se = User.objects.create_user("tv_se", password="x")
        se.groups.add(self.se_group)
        self.client.force_authenticate(user=se)
        with self._mock_s3_ready():
            resp = self.client.post(
                self.url,
                {"title": "Nope", "upload": _uploaded_video()},
                format="multipart",
            )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_rbac_site_engineer_can_list(self):
        TutorialVideo.objects.create(
            title="Visible",
            status=TutorialVideo.STATUS_READY,
            optimized_s3_key="tutorial/optimized/v.mp4",
            video_url="https://example.com/v.mp4",
        )
        se = User.objects.create_user("tv_se2", password="x")
        se.groups.add(self.se_group)
        self.client.force_authenticate(user=se)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_cache_invalidation_on_create(self):
        cache_key_prefix = "tutorial_videos_list"
        cache.set(f"{cache_key_prefix}:seed", {"stale": True}, 300)
        with self._mock_s3_ready(), self._mock_s3_upload(), self._mock_process_noop():
            self.client.post(
                self.url,
                {"title": "Cache", "upload": _uploaded_video()},
                format="multipart",
            )
        # Version bump should make prior keyed entries obsolete; list still works.
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_duplicate_uploads_create_distinct_records(self):
        with self._mock_s3_ready(), self._mock_s3_upload(), self._mock_process_noop():
            r1 = self.client.post(
                self.url,
                {"title": "Same", "upload": _uploaded_video()},
                format="multipart",
            )
            r2 = self.client.post(
                self.url,
                {"title": "Same", "upload": _uploaded_video()},
                format="multipart",
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
                {"title": "Q", "upload": _uploaded_video()},
                format="multipart",
            )
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)


@override_settings(**S3_SETTINGS)
class TutorialVideoProcessingTests(TestCase):
    def setUp(self):
        reset_metrics_for_tests()
        self.user = User.objects.create_user("tv_proc", password="x")

    def test_successful_processing(self):
        video = TutorialVideo.objects.create(
            title="Proc",
            status=TutorialVideo.STATUS_PROCESSING,
            temp_s3_key="tutorial/temporary/src.mp4",
            original_file_size=1000,
            created_by=self.user,
        )

        def fake_download(key, dest):
            Path(dest).write_bytes(_minimal_mp4_bytes())

        opt = OptimizeResult(
            output_path=Path("optimized.mp4"),
            width=1280,
            height=720,
            duration=12.5,
            output_size=400,
            processing_ms=50,
        )

        with (
            patch("services.s3_tutorial_videos.download_to_path", side_effect=fake_download),
            patch(
                "tutorial_videos.processing.optimize_video",
                return_value=opt,
            ) as opt_mock,
            patch(
                "services.s3_tutorial_videos.upload_local_file",
                return_value=400,
            ),
            patch("services.s3_tutorial_videos.delete_object") as del_mock,
            patch(
                "services.s3_tutorial_videos.build_optimized_key",
                return_value="tutorial/optimized/abc.mp4",
            ),
            patch(
                "services.s3_tutorial_videos.object_url",
                return_value="https://pmcproject.s3.ap-south-1.amazonaws.com/tutorial/optimized/abc.mp4",
            ),
        ):
            # Write real output file because upload_local_file is mocked but
            # optimize_video returns a path — create it in the mock side effect.
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
        self.assertEqual(video.file_size, 400)
        self.assertAlmostEqual(video.compression_ratio, 2.5)
        self.assertEqual(video.temp_s3_key, "")
        self.assertTrue(video.optimized_s3_key.startswith("tutorial/optimized/"))
        del_mock.assert_called()
        self.assertTrue(
            BusinessAuditLog.objects.filter(
                entity_type=BusinessAuditLog.ENTITY_TUTORIAL_VIDEO,
                action=BusinessAuditLog.ACTION_COMPLETED,
                entity_id=str(video.pk),
            ).exists()
        )

    def test_failed_processing_cleans_temp(self):
        video = TutorialVideo.objects.create(
            title="Fail",
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
        self.assertEqual(video.temp_s3_key, "")
        self.assertIn("failed", video.processing_error.lower())
        del_mock.assert_called_with("tutorial/temporary/bad.mp4")
        self.assertTrue(
            BusinessAuditLog.objects.filter(
                action=BusinessAuditLog.ACTION_FAILED,
                entity_id=str(video.pk),
            ).exists()
        )

    def test_s3_failure_marks_failed(self):
        video = TutorialVideo.objects.create(
            title="S3Fail",
            status=TutorialVideo.STATUS_PROCESSING,
            temp_s3_key="tutorial/temporary/s3.mp4",
            original_file_size=1000,
            created_by=self.user,
        )

        def fake_download(key, dest):
            Path(dest).write_bytes(_minimal_mp4_bytes())

        with (
            patch("services.s3_tutorial_videos.download_to_path", side_effect=fake_download),
            patch(
                "tutorial_videos.processing.optimize_video",
                side_effect=lambda src, out: (
                    Path(out).write_bytes(b"x"),
                    OptimizeResult(Path(out), 640, 360, 1.0, 1, 10),
                )[1],
            ),
            patch(
                "services.s3_tutorial_videos.upload_local_file",
                side_effect=RuntimeError("S3 down"),
            ),
            patch("services.s3_tutorial_videos.delete_object"),
            patch(
                "services.s3_tutorial_videos.build_optimized_key",
                return_value="tutorial/optimized/z.mp4",
            ),
        ):
            process_tutorial_video(video_id=video.pk)

        video.refresh_from_db()
        self.assertEqual(video.status, TutorialVideo.STATUS_FAILED)

    def test_soft_delete_removes_keys(self):
        video = TutorialVideo.objects.create(
            title="SD",
            status=TutorialVideo.STATUS_READY,
            optimized_s3_key="tutorial/optimized/sd.mp4",
            temp_s3_key="tutorial/temporary/sd.mp4",
            video_url="https://example.com/sd.mp4",
        )
        with patch("services.s3_tutorial_videos.delete_object") as del_mock:
            soft_delete_tutorial_video(video)
        video.refresh_from_db()
        self.assertFalse(video.is_active)
        self.assertEqual(video.status, TutorialVideo.STATUS_DELETED)
        self.assertEqual(del_mock.call_count, 2)

    def test_concurrent_queue_limit(self):
        from tutorial_videos.exceptions import TutorialVideoQueueFull
        from tutorial_videos.video_executor import METRICS, submit_video_job

        reset_metrics_for_tests()
        with METRICS.lock:
            METRICS.pending = 5  # == MAX_PENDING in settings
        with self.assertRaises(TutorialVideoQueueFull):
            submit_video_job(lambda video_id: None, video_id=1)
