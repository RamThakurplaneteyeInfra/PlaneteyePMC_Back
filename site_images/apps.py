import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class SiteImagesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "site_images"
    verbose_name = "Site Progress Images"

    def ready(self):
        from django.conf import settings

        if not getattr(settings, "CLOUDINARY_AVAILABLE", False):
            logger.warning(
                "Site Images: cloudinary package missing — "
                "add 'cloudinary' to requirements.txt and redeploy."
            )
        elif not getattr(settings, "CLOUDINARY_CONFIGURED", False):
            logger.warning(
                "Site Images: Cloudinary configuration missing — "
                "set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, "
                "and CLOUDINARY_API_SECRET in the environment."
            )
        else:
            logger.info(
                "Site Images: Cloudinary configured (cloud=%s).",
                settings.CLOUDINARY_CLOUD_NAME,
            )
