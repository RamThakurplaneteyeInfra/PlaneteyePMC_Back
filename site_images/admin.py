from django.contrib import admin

from .models import SiteProgressImage


@admin.register(SiteProgressImage)
class SiteProgressImageAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "project_name",
        "month",
        "year",
        "cloudinary_public_id",
        "uploaded_by",
        "created_at",
    ]
    list_filter = ["year", "month", "created_at"]
    search_fields = ["project_name", "cloudinary_public_id"]
    readonly_fields = ["image_url", "cloudinary_public_id", "created_at", "updated_at"]
