import logging
import sys

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class SiteImagesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "site_images"
    verbose_name = "Site Progress Images"

    def ready(self):
        from django.conf import settings

        from core.cloudinary_config import (
            is_cloudinary_configured,
            is_cloudinary_package_available,
        )
        from core.s3_config import is_boto3_available, is_s3_configured

        s3_ok = is_boto3_available() and is_s3_configured()
        s3_only = getattr(settings, "SITE_IMAGE_S3_ONLY", False)

        if s3_only:
            logger.info("Site Images: S3-only mode (Cloudinary disabled).")

        if s3_ok:
            logger.info(
                "Site Images: AWS S3 configured (bucket=%s, region=%s, prefix=%s).",
                settings.AWS_STORAGE_BUCKET_NAME,
                settings.AWS_S3_REGION_NAME,
                settings.AWS_S3_UPLOAD_PREFIX,
            )
        elif not is_boto3_available():
            logger.warning(
                "Site Images: boto3 missing on %s — run: %s -m pip install boto3",
                sys.executable,
                sys.executable,
            )
        else:
            logger.warning(
                "Site Images: AWS S3 not configured — set AWS_ACCESS_KEY_ID, "
                "AWS_SECRET_ACCESS_KEY, and AWS_STORAGE_BUCKET_NAME."
            )

        if s3_only:
            if not s3_ok:
                logger.error(
                    "Site Images: S3-only mode but AWS S3 is not configured — "
                    "uploads will return 503."
                )
            return

        cloud_pkg = is_cloudinary_package_available()
        cloud_ok = cloud_pkg and is_cloudinary_configured()

        if cloud_ok:
            logger.info(
                "Site Images: Cloudinary fallback available (cloud=%s).",
                settings.CLOUDINARY_CLOUD_NAME,
            )
        elif cloud_pkg and not is_cloudinary_configured():
            logger.warning(
                "Site Images: Cloudinary fallback unavailable — "
                "set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET."
            )
        elif not cloud_pkg:
            logger.warning(
                "Site Images: cloudinary package missing — "
                "Cloudinary fallback disabled until package is installed."
            )

        if not s3_ok and not cloud_ok:
            logger.error(
                "Site Images: no storage backend ready — uploads will return 503."
            )
