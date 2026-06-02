import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class SiteImagesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "site_images"
    verbose_name = "Site Progress Images"

    def ready(self):
        from core.cloudinary_config import (
            is_cloudinary_configured,
            is_cloudinary_package_available,
        )

        if not is_cloudinary_package_available():
            logger.warning(
                "Site Images: cloudinary package missing — "
                "add 'cloudinary' to requirements.txt and redeploy."
            )
        elif not is_cloudinary_configured():
            logger.warning(
                "Site Images: Cloudinary configuration missing — "
                "set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, "
                "and CLOUDINARY_API_SECRET in the environment."
            )
        else:
            from django.conf import settings

            logger.info(
                "Site Images: Cloudinary credentials present (cloud=%s).",
                settings.CLOUDINARY_CLOUD_NAME,
            )
