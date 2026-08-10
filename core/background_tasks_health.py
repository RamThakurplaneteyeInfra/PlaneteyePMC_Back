"""Background task / email thread-pool health API."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.rbac import can_manage_users


class BackgroundTasksHealthAPIView(APIView):
    """
    GET /api/system/background-tasks/

    ThreadPoolExecutor metrics for in-process DPR email jobs.
    Restricted to Admin / Head Office / CEO / PMC Head.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_manage_users(request.user):
            return Response(
                {"success": False, "message": "Admin access required."},
                status=403,
            )

        from dpr.email_executor import get_email_pool_snapshot
        from tutorial_videos.video_executor import get_video_pool_snapshot

        data = get_email_pool_snapshot()
        pool = data.get("thread_pool") or {}
        video_pool = (get_video_pool_snapshot() or {}).get("thread_pool") or {}
        # Shape matches the deliverable contract (plus extra metrics)
        return Response(
            {
                "success": True,
                "message": "Background task health retrieved successfully.",
                "data": {
                    "thread_pool": {
                        "max_workers": pool.get("max_workers"),
                        "active_workers": pool.get("active_workers"),
                        "queued_tasks": pool.get("queued_tasks"),
                        "completed_tasks": pool.get("completed_tasks"),
                        "failed_tasks": pool.get("failed_tasks"),
                        "emails_queued": pool.get("emails_queued"),
                        "emails_running": pool.get("emails_running"),
                        "skipped_duplicate": pool.get("skipped_duplicate"),
                        "max_queue_depth": pool.get("max_queue_depth"),
                        "slow_emails": pool.get("slow_emails"),
                        "avg_send_ms": pool.get("avg_send_ms"),
                        "avg_total_processing_ms": pool.get("avg_total_processing_ms"),
                        "avg_queue_wait_ms": pool.get("avg_queue_wait_ms"),
                    },
                    "tutorial_video_pool": video_pool,
                },
            }
        )
