from django.contrib import admin

from .models import MachineryItem, MachineryMaster, PlantMachineryReport


@admin.register(MachineryMaster)
class MachineryMasterAdmin(admin.ModelAdmin):
    list_display = ("name", "unit", "category", "is_default", "created_at")
    list_filter = ("is_default", "category")
    search_fields = ("name", "category")
    ordering = ("name",)
    readonly_fields = ("created_at",)


class MachineryItemInline(admin.TabularInline):
    model = MachineryItem
    extra = 0
    autocomplete_fields = ("machinery_master",)
    fields = ("sr_no", "machinery_master", "qty", "status", "remark")


@admin.register(PlantMachineryReport)
class PlantMachineryReportAdmin(admin.ModelAdmin):
    list_display = (
        "project_name",
        "report_date",
        "created_by",
        "created_at",
        "item_count",
    )
    list_filter = ("report_date", "created_by")
    search_fields = ("project_name", "created_by")
    ordering = ("-report_date", "-created_at")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "report_date"
    inlines = [MachineryItemInline]

    def item_count(self, obj):
        return obj.machinery_items.count()

    item_count.short_description = "Machinery Items"


@admin.register(MachineryItem)
class MachineryItemAdmin(admin.ModelAdmin):
    list_display = (
        "sr_no",
        "machinery_master",
        "qty",
        "status",
        "report",
        "last_updated",
    )
    list_filter = ("status", "report__project_name", "report__report_date")
    search_fields = ("machinery_master__name", "remark", "report__project_name")
    ordering = ("report__report_date", "sr_no")
    readonly_fields = ("last_updated",)
    autocomplete_fields = ("report", "machinery_master")
