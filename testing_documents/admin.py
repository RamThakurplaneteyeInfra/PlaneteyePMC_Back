from django.contrib import admin

from .models import TestingDocument, TestingDocumentAuditLog


@admin.register(TestingDocument)
class TestingDocumentAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "title",
        "project",
        "document_type",
        "test_date",
        "uploaded_by",
        "is_active",
        "created_at",
    ]
    list_filter = ["document_type", "year", "month", "is_active"]
    search_fields = ["title", "remarks", "file_name", "project__name"]
    readonly_fields = [
        "file",
        "file_url",
        "file_name",
        "file_size",
        "mime_type",
        "document_type",
        "month",
        "year",
        "created_at",
        "updated_at",
    ]
    raw_id_fields = ["project", "uploaded_by"]


@admin.register(TestingDocumentAuditLog)
class TestingDocumentAuditLogAdmin(admin.ModelAdmin):
    list_display = ["id", "action", "project", "document_id_snapshot", "actor", "created_at"]
    list_filter = ["action", "created_at"]
    search_fields = ["detail", "project__name"]
    readonly_fields = [f.name for f in TestingDocumentAuditLog._meta.fields]
