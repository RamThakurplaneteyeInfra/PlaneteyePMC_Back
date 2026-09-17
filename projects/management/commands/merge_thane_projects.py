"""
Safely merge duplicate Thane projects into one master and rename.

Master (KEEP): Multi-Modal Transit Hub – Thane (TSCL)  → renamed to Satis Thane
Duplicate:     Thane Project                           → status=merged, merged_into=master

Usage:
  python manage.py merge_thane_projects --dry-run
  python manage.py merge_thane_projects --execute
"""

from __future__ import annotations

from decimal import Decimal

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction
from django.db.models import Sum

from projects.models import Project
from projects.pmc_team_mappings import TL_PROJECT_MAPPINGS

MASTER_NAME_CANDIDATES = (
    "Multi-Modal Transit Hub – Thane (TSCL)",  # en-dash
    "Multi-Modal Transit Hub - Thane (TSCL)",  # hyphen
    "Multi-Modal Transit Hub - Thane",
)
DUPLICATE_NAME = "Thane Project"
NEW_MASTER_NAME = "Satis Thane"

STRING_PROJECT_FIELDS: list[tuple[str, str, str]] = [
    ("budget_performance", "BudgetCostPerformance", "project_name"),
    ("cashflow", "CashFlow", "project_name"),
    ("construction_progress", "ConstructionProgress", "projectName"),
    ("contract_performance", "ContractPerformance", "projectName"),
    ("contract_values", "ContractValue", "project_name"),
    ("contracts", "Contract", "project_name"),
    ("correspondence", "CorrespondenceDocument", "project_name"),
    ("correspondence", "InboundCorrespondenceSummary", "project_name"),
    ("correspondence", "SCLDeliveredCorrespondenceSummary", "project_name"),
    ("cost_performance", "ProjectCostPerformance", "project_name"),
    ("dpr", "DailyProgressReport", "project_name"),
    ("equipment", "ProjectEquipment", "project_name"),
    ("health_safety", "HealthSafetyReport", "project_name"),
    ("health_safety", "HSERecord", "projectName"),
    ("health_safety", "HealthSafetyRecord", "project_name"),
    ("invoicing", "InvoicingInformation", "project_name"),
    ("manpower", "ProjectManpower", "project_name"),
    ("manpower_management", "ManpowerRecord", "project_name"),
    ("planned_earned_value", "PlannedEarnedValue", "project_name"),
    ("plant_machinery", "PlantMachineryReport", "project_name"),
    ("project_equipment", "ProjectEquipment", "projectName"),
    ("project_progress", "ProjectProgressStatus", "project_name"),
    ("project_quality_status", "ProjectQualityStatus", "projectName"),
    ("project_quality_status", "TestFrequencyMaster", "projectName"),
    ("project_quality_status", "FrequencyChartEntry", "projectName"),
    ("site_images", "SiteProgressImage", "project_name"),
]

CACHE_PREFIXES = [
    "cashflow_list",
    "contracts_list",
    "dpr_list",
    "dpr_pending_approval",
    "dpr_rejected",
    "invoicing_list",
    "equipment_list",
    "manpower_list",
    "correspondence_list",
    "budget_performance_list",
    "cost_performance_list",
    "contract_values_list",
    "contract_performance_list",
    "project_equipment_list",
    "construction_progress_list",
    "quality_status_list",
    "hse_list",
    "health_safety_list",
]


def _is_numeric_field(field) -> bool:
    return isinstance(
        field,
        (
            models.IntegerField,
            models.PositiveIntegerField,
            models.PositiveSmallIntegerField,
            models.SmallIntegerField,
            models.BigIntegerField,
            models.DecimalField,
            models.FloatField,
        ),
    )


def _merge_instance_values(survivor, donor) -> list[str]:
    """Copy non-empty donor scalars onto empty/zero survivor fields. Returns changed names."""
    changed = []
    for field in survivor._meta.concrete_fields:
        if field.primary_key or field.name in ("created_at", "updated_at"):
            continue
        if isinstance(field, (models.ForeignKey, models.OneToOneField)):
            # Don't overwrite FKs except when survivor FK is null
            att = field.attname
            if getattr(survivor, att) in (None, "") and getattr(donor, att) not in (None, ""):
                setattr(survivor, att, getattr(donor, att))
                changed.append(field.name)
            continue
        if isinstance(field, models.FileField):
            if not getattr(survivor, field.name) and getattr(donor, field.name):
                setattr(survivor, field.name, getattr(donor, field.name))
                changed.append(field.name)
            continue
        sval = getattr(survivor, field.name)
        dval = getattr(donor, field.name)
        if dval in (None, "", []):
            continue
        if _is_numeric_field(field):
            try:
                if sval in (None, 0, Decimal("0"), Decimal("0.00"), 0.0) and dval not in (
                    None,
                    0,
                    Decimal("0"),
                    Decimal("0.00"),
                    0.0,
                ):
                    setattr(survivor, field.name, dval)
                    changed.append(field.name)
            except Exception:
                pass
        elif sval in (None, ""):
            setattr(survivor, field.name, dval)
            changed.append(field.name)
    if changed:
        survivor.save()
    return changed


class Command(BaseCommand):
    help = (
        "Merge 'Thane Project' into 'Multi-Modal Transit Hub – Thane (TSCL)', "
        "rename master to 'Satis Thane', and archive the duplicate."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Analyze and print plan without writing.",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Perform the migration inside a single atomic transaction.",
        )
        parser.add_argument(
            "--master-id",
            type=int,
            default=None,
            help="Override master project id (default: resolve by name).",
        )
        parser.add_argument(
            "--duplicate-id",
            type=int,
            default=None,
            help="Override duplicate project id (default: resolve by name).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        execute = options["execute"]
        if dry_run == execute:
            raise CommandError("Specify exactly one of --dry-run or --execute.")

        master, duplicate = self._resolve_projects(options)
        report = self._build_report(master, duplicate)
        self._print_report(master, duplicate, report)

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run only — no changes written."))
            return

        with transaction.atomic():
            stats = self._migrate(master, duplicate, report)
            # Re-fetch after rename
            master.refresh_from_db()
            duplicate.refresh_from_db()
            self._post_verify(master, duplicate, report, stats)

        self._invalidate_caches()
        self.stdout.write(self.style.SUCCESS("Migration committed successfully."))
        self._print_final(master, duplicate, stats)

    def _resolve_projects(self, options):
        if options["master_id"] and options["duplicate_id"]:
            master = Project.objects.filter(pk=options["master_id"]).first()
            duplicate = Project.objects.filter(pk=options["duplicate_id"]).first()
        else:
            master = None
            for name in MASTER_NAME_CANDIDATES:
                master = Project.objects.filter(name=name).first()
                if master:
                    break
            if master is None:
                master = Project.objects.filter(name__icontains="Multi-Modal Transit Hub").filter(
                    name__icontains="Thane"
                ).first()
            duplicate = Project.objects.filter(name__iexact=DUPLICATE_NAME).first()

        if master is None:
            raise CommandError("Master project not found.")
        if duplicate is None:
            raise CommandError(f"Duplicate project '{DUPLICATE_NAME}' not found.")
        if master.pk == duplicate.pk:
            raise CommandError("Master and duplicate resolve to the same row — aborting.")
        return master, duplicate

    def _iter_project_fk_fields(self):
        ProjectModel = apps.get_model("projects", "Project")
        for model in apps.get_models():
            for field in model._meta.get_fields():
                if not isinstance(field, (models.ForeignKey, models.OneToOneField)):
                    continue
                if getattr(field, "auto_created", False) and not field.concrete:
                    continue
                try:
                    if field.related_model is not ProjectModel:
                        continue
                except Exception:
                    continue
                # Skip Project.merged_into self-FK during discovery of child refs
                if model is Project and field.name == "merged_into":
                    continue
                yield model, field

    def _build_report(self, master, duplicate):
        fk_counts = []
        total_fk = 0
        for model, field in self._iter_project_fk_fields():
            c = model.objects.filter(**{field.attname: duplicate.pk}).count()
            if c:
                fk_counts.append((model._meta.label, field.name, c, field))
                total_fk += c

        str_counts = []
        total_str = 0
        for app, model_name, fname in STRING_PROJECT_FIELDS:
            Model = apps.get_model(app, model_name)
            c = Model.objects.filter(**{f"{fname}__iexact": DUPLICATE_NAME}).count()
            if c:
                str_counts.append((f"{app}.{model_name}", fname, c))
                total_str += c

        m2m = {
            "site_engineers": {
                "dup": list(duplicate.site_engineers.values_list("id", flat=True)),
                "master": list(master.site_engineers.values_list("id", flat=True)),
            },
            "coordinators": {
                "dup": list(duplicate.coordinators.values_list("id", flat=True)),
                "master": list(master.coordinators.values_list("id", flat=True)),
            },
            "assigned_users": {
                "dup": list(duplicate.assigned_users.values_list("id", flat=True)),
                "master": list(master.assigned_users.values_list("id", flat=True)),
            },
        }
        return {
            "fk_counts": fk_counts,
            "total_fk": total_fk,
            "str_counts": str_counts,
            "total_str": total_str,
            "m2m": m2m,
        }

    def _print_report(self, master, duplicate, report):
        self.stdout.write("")
        self.stdout.write("=" * 72)
        self.stdout.write("PROJECT MERGE ANALYSIS")
        self.stdout.write("=" * 72)
        self.stdout.write(f"Master ID:     {master.pk}")
        self.stdout.write(f"Master name:   {master.name!r}")
        self.stdout.write(f"Duplicate ID:  {duplicate.pk}")
        self.stdout.write(f"Duplicate name:{duplicate.name!r}")
        self.stdout.write(f"Rename master -> {NEW_MASTER_NAME!r}")
        self.stdout.write("")
        self.stdout.write(f"FK/O2O rows on duplicate: {report['total_fk']}")
        for label, fname, c, _ in report["fk_counts"]:
            self.stdout.write(f"  {label}.{fname}: {c}")
        self.stdout.write(f"String project refs (Thane Project): {report['total_str']}")
        for label, fname, c in report["str_counts"]:
            self.stdout.write(f"  {label}.{fname}: {c}")
        self.stdout.write("M2M:")
        for k, v in report["m2m"].items():
            self.stdout.write(f"  {k}: dup={v['dup']} master={v['master']}")
        self.stdout.write("=" * 72)

    def _migrate(self, master, duplicate, report):
        stats = {
            "fk_updated": 0,
            "fk_merged_conflicts": 0,
            "str_updated": 0,
            "str_merged_conflicts": 0,
            "m2m_added": 0,
            "staff_copied": [],
            "consolidated_rows": [],
        }

        # 1) Merge staff FKs on Project when master is empty
        for attr in (
            "team_lead",
            "site_engineer",
            "billing_site_engineer",
            "qaqc_site_engineer",
            "hse_site_engineer",
            "pmc_head",
        ):
            if getattr(master, f"{attr}_id") is None and getattr(duplicate, f"{attr}_id") is not None:
                setattr(master, attr, getattr(duplicate, attr))
                stats["staff_copied"].append(attr)
        if stats["staff_copied"]:
            master.save(update_fields=[*stats["staff_copied"], "updated_at"])

        # 2) M2M merge
        for fname in ("site_engineers", "coordinators", "assigned_users"):
            m2m = getattr(master, fname)
            for uid in report["m2m"][fname]["dup"]:
                if uid not in report["m2m"][fname]["master"]:
                    m2m.add(uid)
                    stats["m2m_added"] += 1

        # 3) Reassign Project FKs / O2Os
        for model, field in self._iter_project_fk_fields():
            qs = model.objects.filter(**{field.attname: duplicate.pk})

            # Handle rows that would violate unique/O2O constraints individually
            conflict_ids = []
            for obj in qs.iterator():
                if self._would_unique_conflict(model, field, obj, master.pk):
                    survivor = (
                        model.objects.filter(**{field.attname: master.pk})
                        .exclude(pk=obj.pk)
                        .first()
                    )
                    if survivor is not None:
                        changed = _merge_instance_values(survivor, obj)
                        stats["fk_merged_conflicts"] += 1
                        stats["consolidated_rows"].append(
                            f"{model._meta.label}#{obj.pk} -> #{survivor.pk} fields={changed}"
                        )
                        self._sync_denorm_name(survivor, NEW_MASTER_NAME)
                        if hasattr(survivor, "project_name") or hasattr(survivor, "projectName"):
                            try:
                                survivor.save()
                            except Exception:
                                # Prefer FK-only persist when model validation is strict
                                type(survivor).objects.filter(pk=survivor.pk).update(
                                    **{
                                        k: getattr(survivor, k)
                                        for k in ("project_name", "projectName")
                                        if hasattr(survivor, k)
                                        and not isinstance(getattr(type(survivor), k, None), property)
                                    }
                                )
                        obj.delete()
                        conflict_ids.append(obj.pk)

            # Bulk update remaining FKs (bypasses model.save validation)
            remaining = model.objects.filter(**{field.attname: duplicate.pk})
            updated = remaining.update(**{field.attname: master.pk})
            stats["fk_updated"] += updated

            # Bulk sync denormalized names for rows now on master that still say Thane Project
            for attr in ("project_name", "projectName"):
                try:
                    f = model._meta.get_field(attr)
                except Exception:
                    continue
                if not f.concrete:
                    continue
                model.objects.filter(**{field.attname: master.pk}).filter(
                    **{f"{attr}__iexact": DUPLICATE_NAME}
                ).update(**{attr: NEW_MASTER_NAME})

        # 4) Rename remaining string refs Thane Project / old master name -> Satis Thane
        old_names = {DUPLICATE_NAME, master.name, *MASTER_NAME_CANDIDATES}
        for app, model_name, fname in STRING_PROJECT_FIELDS:
            Model = apps.get_model(app, model_name)
            for old in old_names:
                qs = Model.objects.filter(**{f"{fname}__iexact": old}).exclude(
                    **{f"{fname}__iexact": NEW_MASTER_NAME}
                )
                # Process unique conflicts first
                for obj in list(qs):
                    if not self._string_rename_conflicts(Model, fname, obj, NEW_MASTER_NAME):
                        continue
                    survivor = self._find_string_survivor(Model, obj, fname)
                    if survivor is None:
                        survivor = (
                            Model.objects.filter(**{f"{fname}__iexact": NEW_MASTER_NAME})
                            .exclude(pk=obj.pk)
                            .filter(**self._unique_lookup_for(Model, obj, fname))
                            .first()
                        )
                    if survivor is not None:
                        changed = _merge_instance_values(survivor, obj)
                        if hasattr(survivor, "project_id"):
                            type(survivor).objects.filter(pk=survivor.pk).update(
                                project_id=master.pk
                            )
                        stats["str_merged_conflicts"] += 1
                        stats["consolidated_rows"].append(
                            f"{Model._meta.label}#{obj.pk} -> #{survivor.pk} (string) {changed}"
                        )
                        obj.delete()

                # Bulk rename the rest
                remaining = Model.objects.filter(**{f"{fname}__iexact": old}).exclude(
                    **{f"{fname}__iexact": NEW_MASTER_NAME}
                )
                count = remaining.update(**{fname: NEW_MASTER_NAME})
                stats["str_updated"] += count
                # Align any FK still pointing at duplicate for these models
                if hasattr(Model, "project_id"):
                    Model.objects.filter(project_id=duplicate.pk).update(project_id=master.pk)
        # 5) Rename master (same PK)
        master.name = NEW_MASTER_NAME
        if master.description:
            master.description = (
                f"{master.description}\n[Merged from '{DUPLICATE_NAME}' (id={duplicate.pk})]"
            ).strip()
        else:
            master.description = f"[Merged from '{DUPLICATE_NAME}' (id={duplicate.pk})]"
        master.status = "active"
        master.save(update_fields=["name", "description", "status", "updated_at"])

        # 6) Archive duplicate (never hard-delete)
        duplicate.status = "merged"
        duplicate.merged_into = master
        note = f"[ARCHIVED] Merged into {NEW_MASTER_NAME} (id={master.pk})"
        duplicate.description = (
            f"{duplicate.description}\n{note}".strip()
            if duplicate.description
            else note
        )
        duplicate.save(
            update_fields=["status", "merged_into", "description", "updated_at"]
        )

        return stats

    def _sync_denorm_name(self, obj, name: str) -> None:
        for attr in ("project_name", "projectName"):
            if not hasattr(obj, attr):
                continue
            # Skip @property without setter (e.g. DrawingSummary.project_name)
            cls_attr = getattr(type(obj), attr, None)
            if isinstance(cls_attr, property) and cls_attr.fset is None:
                continue
            try:
                field = obj._meta.get_field(attr)
            except Exception:
                continue
            if field.concrete and not field.many_to_many:
                setattr(obj, attr, name)

    def _would_unique_conflict(self, model, field, obj, master_id) -> bool:
        """True if moving obj.project → master would violate a unique constraint involving project."""
        # OneToOne always conflicts if master already has a row
        if isinstance(field, models.OneToOneField):
            return model.objects.filter(**{field.attname: master_id}).exclude(pk=obj.pk).exists()

        # UniqueConstraint / unique_together including this FK
        for ut in model._meta.unique_together:
            if field.name in ut:
                lookup = {field.attname: master_id}
                for fname in ut:
                    if fname == field.name:
                        continue
                    lookup[fname] = getattr(obj, fname)
                if model.objects.filter(**lookup).exclude(pk=obj.pk).exists():
                    return True
        for uc in model._meta.constraints:
            if not isinstance(uc, models.UniqueConstraint):
                continue
            if field.name not in uc.fields:
                continue
            lookup = {}
            for fname in uc.fields:
                if fname == field.name:
                    lookup[field.attname] = master_id
                else:
                    f = model._meta.get_field(fname)
                    lookup[f.attname if hasattr(f, "attname") else fname] = getattr(obj, fname)
            if model.objects.filter(**lookup).exclude(pk=obj.pk).exists():
                return True
        return False

    def _string_rename_conflicts(self, Model, fname, obj, new_name) -> bool:
        for ut in Model._meta.unique_together:
            if fname in ut:
                lookup = {fname: new_name}
                for other in ut:
                    if other == fname:
                        continue
                    lookup[other] = getattr(obj, other)
                if Model.objects.filter(**lookup).exclude(pk=obj.pk).exists():
                    return True
        for uc in Model._meta.constraints:
            if not isinstance(uc, models.UniqueConstraint):
                continue
            if fname not in uc.fields:
                continue
            lookup = {}
            for other in uc.fields:
                if other == fname:
                    lookup[other] = new_name
                else:
                    lookup[other] = getattr(obj, other)
            if Model.objects.filter(**lookup).exclude(pk=obj.pk).exists():
                return True
        # unique=True on the project name field itself (e.g. HSERecord.projectName)
        field = Model._meta.get_field(fname)
        if getattr(field, "unique", False):
            if Model.objects.filter(**{fname: new_name}).exclude(pk=obj.pk).exists():
                return True
        return False

    def _unique_lookup_for(self, Model, obj, fname) -> dict:
        for ut in Model._meta.unique_together:
            if fname in ut:
                return {other: getattr(obj, other) for other in ut if other != fname}
        for uc in Model._meta.constraints:
            if isinstance(uc, models.UniqueConstraint) and fname in uc.fields:
                return {
                    other: getattr(obj, other) for other in uc.fields if other != fname
                }
        return {}

    def _find_string_survivor(self, Model, obj, fname):
        lookup = self._unique_lookup_for(Model, obj, fname)
        if not lookup:
            return None
        return (
            Model.objects.filter(**lookup)
            .filter(**{f"{fname}__iexact": NEW_MASTER_NAME})
            .exclude(pk=obj.pk)
            .first()
        )

    def _post_verify(self, master, duplicate, report, stats):
        remaining_fk = 0
        for model, field in self._iter_project_fk_fields():
            remaining_fk += model.objects.filter(**{field.attname: duplicate.pk}).count()

        remaining_str = 0
        for app, model_name, fname in STRING_PROJECT_FIELDS:
            Model = apps.get_model(app, model_name)
            remaining_str += Model.objects.filter(**{f"{fname}__iexact": DUPLICATE_NAME}).count()

        if remaining_fk:
            raise CommandError(
                f"Verification failed: {remaining_fk} FK rows still point at duplicate."
            )
        # String refs may remain only if somehow missed — fail hard
        if remaining_str:
            raise CommandError(
                f"Verification failed: {remaining_str} string rows still say 'Thane Project'."
            )
        if master.name != NEW_MASTER_NAME:
            raise CommandError(f"Master rename failed: got {master.name!r}")
        if duplicate.status != "merged" or duplicate.merged_into_id != master.pk:
            raise CommandError("Duplicate was not archived correctly.")

        # Mapping table sanity
        mapped = dict(TL_PROJECT_MAPPINGS)
        if mapped.get("pmc_tl12") != NEW_MASTER_NAME:
            self.stdout.write(
                self.style.WARNING(
                    f"pmc_team_mappings pmc_tl12 is {mapped.get('pmc_tl12')!r}; "
                    f"expected {NEW_MASTER_NAME!r} (update source if needed)."
                )
            )

        stats["remaining_fk_on_dup"] = remaining_fk
        stats["remaining_str_thane_project"] = remaining_str

    def _invalidate_caches(self):
        try:
            from core.cache_keys import invalidate_list_cache
        except Exception:
            return
        for prefix in CACHE_PREFIXES:
            try:
                invalidate_list_cache(prefix)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"Cache invalidate {prefix}: {exc}"))

    def _print_final(self, master, duplicate, stats):
        self.stdout.write("")
        self.stdout.write("=" * 72)
        self.stdout.write(self.style.SUCCESS("MIGRATION RESULT"))
        self.stdout.write("=" * 72)
        self.stdout.write(f"Master: {master.pk} {master.name!r} status={master.status}")
        self.stdout.write(
            f"Duplicate archived: {duplicate.pk} {duplicate.name!r} "
            f"status={duplicate.status} merged_into={duplicate.merged_into_id}"
        )
        self.stdout.write(f"FK rows reassigned:     {stats['fk_updated']}")
        self.stdout.write(f"FK conflicts merged:    {stats['fk_merged_conflicts']}")
        self.stdout.write(f"String rows renamed:    {stats['str_updated']}")
        self.stdout.write(f"String conflicts merged:{stats['str_merged_conflicts']}")
        self.stdout.write(f"M2M memberships added:  {stats['m2m_added']}")
        self.stdout.write(f"Staff fields copied:    {stats['staff_copied']}")
        if stats["consolidated_rows"]:
            self.stdout.write("Consolidated (values preserved on survivor, donor row removed):")
            for line in stats["consolidated_rows"]:
                self.stdout.write(f"  - {line}")
        self.stdout.write("Caches invalidated.")
        self.stdout.write("Transaction committed (rollback would have undone all writes on error).")
        self.stdout.write("=" * 72)
