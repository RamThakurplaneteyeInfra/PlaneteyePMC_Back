"""Invalidate MPR preview cache when source domain data changes."""

from django.db.models.signals import post_delete, post_save


def _invalidate_mpr(*_args, **_kwargs):
    from mpr.services.cache import invalidate_mpr_cache

    invalidate_mpr_cache()


def connect_mpr_invalidation_signals():
    from bottlenecks.models import Bottleneck
    from cashflow.models import CashFlow
    from construction_progress.models.construction_progress import ConstructionProgress
    from contract_values.models import ContractValue
    from correspondence.models.correspondence import CorrespondenceDocument
    from cost_performance.models import ProjectCostPerformance
    from drawings.models.drawing_file import DrawingFile
    from drawings.models.drawing_register import DrawingRegisterItem
    from dpr.models import DailyProgressReport
    from health_safety.models import HealthSafetyRecord
    from invoicing.models import InvoicingInformation
    from manpower.models import ProjectManpower
    from monthly_scope.models import MonthlyScopeWork
    from plant_machinery.models import PlantMachineryReport
    from project_dates.eot_models import ProjectEOT
    from project_dates.models import BGStatus, ProjectDates
    from project_equipment.models.project_equipment import ProjectEquipment
    from project_quality_status.models.project_quality_status import ProjectQualityStatus
    from projects.models import Project
    from site_images.models import SiteProgressImage

    for model in (
        Project,
        ProjectDates,
        ProjectEOT,
        BGStatus,
        DailyProgressReport,
        MonthlyScopeWork,
        ConstructionProgress,
        ProjectCostPerformance,
        CashFlow,
        ContractValue,
        InvoicingInformation,
        CorrespondenceDocument,
        DrawingRegisterItem,
        DrawingFile,
        Bottleneck,
        ProjectQualityStatus,
        HealthSafetyRecord,
        ProjectManpower,
        ProjectEquipment,
        PlantMachineryReport,
        SiteProgressImage,
    ):
        post_save.connect(_invalidate_mpr, sender=model, weak=False)
        post_delete.connect(_invalidate_mpr, sender=model, weak=False)


connect_mpr_invalidation_signals()
