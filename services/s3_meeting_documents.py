from __future__ import annotations

import logging
import mimetypes
import os
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.text import get_valid_filename

from core.s3_config import (
    DEFAULT_OBJECT_CACHE_CONTROL,
    get_s3_client,
    is_boto3_available,
    is_s3_configured,
)

logger = logging.getLogger(__name__)

MAX_UPLOAD_SIZE = 100 * 1024 * 1024
PRESIGNED_EXPIRY_SECONDS = 10 * 60
MEETING_DOCUMENTS_ROOT = "MOM&EDL"

ALLOWED_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

BLOCKED_EXTENSIONS = {
    ".exe",
    ".bat",
    ".cmd",
    ".com",
    ".msi",
    ".scr",
    ".ps1",
    ".sh",
    ".dll",
    ".js",
    ".vbs",
    ".jar",
}


@dataclass
class CompressedDocument:
    file_obj: object
    file_name: str
    content_type: str
    original_size: int
    compressed_size: int
    compression_percentage: Decimal


def check_s3_ready() -> tuple[bool, str | None]:
    if not is_boto3_available():
        return False, "boto3 is not installed. Run: pip install boto3"
    if not is_s3_configured():
        return False, "AWS S3 configuration missing"
    return True, None


def sanitize_filename(filename: str) -> str:
    safe = get_valid_filename(Path(filename or "document").name)
    return safe or "document"


def sanitize_key_segment(value: str, *, default: str = "untitled") -> str:
    segment = str(value or "").replace("\\", " ").replace("/", " ").strip()
    segment = " ".join(segment.split())
    return segment or default


def extension_for(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def content_type_for(filename: str) -> str:
    ext = extension_for(filename)
    if ext in ALLOWED_CONTENT_TYPES:
        return ALLOWED_CONTENT_TYPES[ext]
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def s3_meeting_document_url(s3_key: str) -> str:
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    region = getattr(settings, "AWS_S3_REGION_NAME", "ap-south-1")
    custom_domain = getattr(settings, "AWS_S3_CUSTOM_DOMAIN", "").strip()
    encoded_key = quote(s3_key.lstrip("/"), safe="/")
    if custom_domain:
        return f"https://{custom_domain.rstrip('/')}/{encoded_key}"
    return f"https://{bucket}.s3.{region}.amazonaws.com/{encoded_key}"


def validate_upload_file(uploaded_file) -> tuple[str, str]:
    filename = sanitize_filename(getattr(uploaded_file, "name", "document"))
    ext = extension_for(filename)
    if ext in BLOCKED_EXTENSIONS:
        raise ValidationError("Executable files are not allowed.")
    if ext not in ALLOWED_CONTENT_TYPES:
        raise ValidationError("Unsupported file type.")

    size = int(getattr(uploaded_file, "size", 0) or 0)
    if size <= 0:
        raise ValidationError("Uploaded file is empty or unreadable.")
    if size > MAX_UPLOAD_SIZE:
        raise ValidationError("File exceeds the configured maximum upload size.")

    uploaded_file.seek(0)
    header = uploaded_file.read(8)
    uploaded_file.seek(0)

    if ext == ".pdf" and not header.startswith(b"%PDF"):
        raise ValidationError("Invalid or corrupted PDF file.")
    if ext in {".jpg", ".jpeg"} and not header.startswith(b"\xff\xd8"):
        raise ValidationError("Invalid or corrupted JPEG file.")
    if ext == ".png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValidationError("Invalid or corrupted PNG file.")
    if ext in {".docx", ".xlsx", ".pptx"}:
        try:
            with zipfile.ZipFile(uploaded_file) as archive:
                if archive.testzip() is not None:
                    raise ValidationError("Office document archive is corrupted.")
        except zipfile.BadZipFile as exc:
            raise ValidationError("Invalid or corrupted Office document.") from exc
        finally:
            uploaded_file.seek(0)

    return filename, ALLOWED_CONTENT_TYPES[ext]


def _copy_to_spooled_file(source) -> tempfile.SpooledTemporaryFile:
    from core.uploads import copy_file_obj_chunked

    target = tempfile.SpooledTemporaryFile(max_size=25 * 1024 * 1024, mode="w+b")
    copy_file_obj_chunked(source, target)
    return target


def _file_size(file_obj) -> int:
    pos = file_obj.tell()
    file_obj.seek(0, os.SEEK_END)
    size = file_obj.tell()
    file_obj.seek(pos)
    return size


def _optimize_image(uploaded_file, ext: str):
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None

    uploaded_file.seek(0)
    image = Image.open(uploaded_file)
    image = ImageOps.exif_transpose(image)
    max_dimension = 2400
    if max(image.size) > max_dimension:
        image.thumbnail((max_dimension, max_dimension))

    output = tempfile.SpooledTemporaryFile(max_size=25 * 1024 * 1024, mode="w+b")
    if ext in {".jpg", ".jpeg"}:
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        image.save(output, format="JPEG", quality=85, optimize=True, progressive=True)
    else:
        image.save(output, format="PNG", optimize=True)
    output.seek(0)
    uploaded_file.seek(0)
    return output


def _optimize_office_document(uploaded_file):
    uploaded_file.seek(0)
    output = tempfile.SpooledTemporaryFile(max_size=25 * 1024 * 1024, mode="w+b")
    skip_metadata = {"docProps/core.xml", "docProps/app.xml", "docProps/custom.xml"}
    with zipfile.ZipFile(uploaded_file, "r") as src, zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as dst:
        for info in src.infolist():
            if info.filename in skip_metadata:
                continue
            dst.writestr(info, src.read(info.filename))
    output.seek(0)
    uploaded_file.seek(0)
    return output


def _optimize_pdf(uploaded_file):
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        return None

    uploaded_file.seek(0)
    reader = PdfReader(uploaded_file)
    writer = PdfWriter()
    for page in reader.pages:
        try:
            page.compress_content_streams()
        except Exception:
            logger.debug("PDF page stream compression skipped", exc_info=True)
        writer.add_page(page)
    writer.add_metadata({})
    output = tempfile.SpooledTemporaryFile(max_size=25 * 1024 * 1024, mode="w+b")
    writer.write(output)
    output.seek(0)
    uploaded_file.seek(0)
    return output


def compress_document(uploaded_file) -> CompressedDocument:
    filename, content_type = validate_upload_file(uploaded_file)
    ext = extension_for(filename)
    original_size = int(getattr(uploaded_file, "size", 0) or 0)

    optimized = None
    try:
        if ext in {".jpg", ".jpeg", ".png"}:
            optimized = _optimize_image(uploaded_file, ext)
        elif ext in {".docx", ".xlsx", ".pptx"}:
            optimized = _optimize_office_document(uploaded_file)
        elif ext == ".pdf":
            optimized = _optimize_pdf(uploaded_file)
        logger.info("Meeting document compression attempted: %s", filename)
    except Exception:
        logger.exception("Meeting document compression failed: %s", filename)
        optimized = None

    if optimized is None:
        optimized = _copy_to_spooled_file(uploaded_file)

    optimized_size = _file_size(optimized)
    if optimized_size <= 0:
        raise ValidationError("Optimized upload is empty.")
    if optimized_size > original_size:
        optimized.close()
        optimized = _copy_to_spooled_file(uploaded_file)
        optimized_size = original_size

    saved = max(original_size - optimized_size, 0)
    percentage = Decimal("0.00")
    if original_size:
        percentage = (Decimal(saved) / Decimal(original_size) * Decimal("100")).quantize(Decimal("0.01"))

    return CompressedDocument(
        file_obj=optimized,
        file_name=filename,
        content_type=content_type,
        original_size=original_size,
        compressed_size=optimized_size,
        compression_percentage=percentage,
    )


def build_s3_key(
    *,
    project_name: str,
    meeting_type: str,
    meeting_date,
    filename: str,
    version: int | None = None,
) -> str:
    import re
    safe_project = sanitize_key_segment(project_name, default="Project")
    safe_type = sanitize_key_segment(meeting_type, default="MOM").upper()
    safe_name = sanitize_filename(filename)
    stem = Path(safe_name).stem
    # Strip any existing _v<N> suffix from stem to avoid duplicates like _v1_v2
    stem = re.sub(r'_v\d+$', '', stem)
    stem = stem[:90] or "document"
    ext = extension_for(safe_name) or ".bin"
    version_suffix = f"_v{version}" if version is not None else "_v1"
    
    base_key = (
        f"{MEETING_DOCUMENTS_ROOT}/{safe_project}/{safe_type}/"
        f"{meeting_date.year}/{meeting_date.month:02d}/{stem}{version_suffix}{ext}"
    )
    
    # Import locally to avoid circular dependencies
    try:
        from meeting_documents.models import MeetingDocument
        if MeetingDocument.objects.filter(s3_key=base_key).exists():
            counter = 1
            while True:
                candidate_key = (
                    f"{MEETING_DOCUMENTS_ROOT}/{safe_project}/{safe_type}/"
                    f"{meeting_date.year}/{meeting_date.month:02d}/{stem}{version_suffix}_{counter}{ext}"
                )
                if not MeetingDocument.objects.filter(s3_key=candidate_key).exists():
                    return candidate_key
                counter += 1
    except Exception:
        # Fallback to appending a unique token if DB check fails or before app is loaded
        unique = uuid.uuid4().hex[:8]
        return (
            f"{MEETING_DOCUMENTS_ROOT}/{safe_project}/{safe_type}/"
            f"{meeting_date.year}/{meeting_date.month:02d}/{stem}{version_suffix}_{unique}{ext}"
        )
        
    return base_key



def upload_meeting_document(
    compressed: CompressedDocument,
    *,
    s3_key: str | None = None,
    object_key: str | None = None,
) -> dict:
    key = s3_key or object_key
    if not key:
        raise ValueError("s3_key is required for upload.")
    ready, message = check_s3_ready()
    if not ready:
        raise RuntimeError(message)

    logger.info("Meeting document S3 upload start: key=%s", key)
    compressed.file_obj.seek(0)
    get_s3_client().upload_fileobj(
        compressed.file_obj,
        settings.AWS_STORAGE_BUCKET_NAME,
        key,
        ExtraArgs={
            "ContentType": compressed.content_type,
            "CacheControl": DEFAULT_OBJECT_CACHE_CONTROL,
            "Metadata": {"original-filename": compressed.file_name},
        },
    )
    logger.info("Meeting document S3 upload success: key=%s", key)
    return {"s3_key": key, "s3_url": s3_meeting_document_url(key)}


def delete_meeting_document(s3_key: str) -> None:
    if not s3_key:
        return
    ready, message = check_s3_ready()
    if not ready:
        logger.warning("Meeting document S3 delete skipped: %s", message)
        return
    logger.info("Meeting document S3 delete start: key=%s", s3_key)
    get_s3_client().delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=s3_key)
    logger.info("Meeting document S3 delete success: key=%s", s3_key)


def generate_presigned_url(s3_key: str, *, expires_in: int = PRESIGNED_EXPIRY_SECONDS) -> str:
    from services.presigned_url_cache import cached_presigned_url

    def _sign(key: str, *, expires_in: int) -> str:
        ready, message = check_s3_ready()
        if not ready:
            raise RuntimeError(message)
        logger.info("Meeting document presigned URL generated: key=%s", key)
        return get_s3_client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                "Key": key,
                "ResponseContentDisposition": "inline",
            },
            ExpiresIn=expires_in,
        )

    return cached_presigned_url(
        cache_namespace="meeting_docs",
        s3_key=s3_key,
        expires_in=expires_in,
        generator=_sign,
    )


# Backward-friendly aliases used by the meeting_documents app internals.
OptimizedUpload = CompressedDocument
optimize_upload = compress_document
build_object_key = build_s3_key
upload_document = upload_meeting_document
delete_document = delete_meeting_document
generate_presigned_download_url = generate_presigned_url
