from django.apps import AppConfig


class TutorialVideosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tutorial_videos"
    verbose_name = "Tutorial Videos"

    def ready(self):
        # Eager-init the processing pool (mirrors dpr.apps email executor).
        try:
            from tutorial_videos.video_executor import get_video_executor

            get_video_executor()
        except Exception:
            pass
