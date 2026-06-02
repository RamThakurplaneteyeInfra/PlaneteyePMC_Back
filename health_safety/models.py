# Health & Safety Models
from django.db import models
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError


class HealthSafetyReport(models.Model):
    """
    Health & Safety Status Report
    Stores incident data and manhours for safety analysis
    """
    project_name = models.CharField(max_length=255, db_index=True, help_text="Name of the project")
    report_date = models.DateField(help_text="Date of the report")
    total_manhours = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Total manhours worked"
    )
    
    # Incident counts
    fatalities = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of fatalities"
    )
    significant = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of significant incidents"
    )
    major = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of major incidents"
    )
    minor = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of minor incidents"
    )
    near_miss = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of near miss incidents"
    )
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-report_date', '-created_at']
        verbose_name = "Health & Safety Report"
        verbose_name_plural = "Health & Safety Reports"
        indexes = [
            models.Index(fields=['project_name', '-report_date']),
            models.Index(fields=['-report_date']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['project_name', 'report_date'], name='unique_project_date_hs'),
        ]

    def save(self, *args, **kwargs):
        # Normalize project_name by stripping whitespace
        if self.project_name:
            self.project_name = self.project_name.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"H&S - {self.project_name} ({self.report_date})"

    @property
    def total_incidents(self):
        """Calculate total incidents"""
        return self.fatalities + self.significant + self.major + self.minor + self.near_miss


# =============================================================================
# HSE RECORD MODEL
# One cumulative record per project — used for dashboard KPI cards and the
# HSE edit modal in the PMC frontend.
#
# Scalable for future additions:
#   - monthly HSE tracking (add month_year field)
#   - incident history (add HSEIncident child model)
#   - LTIFR / TRIR calculations (add computed properties)
#   - safety score calculation (add safety_score field)
#   - project-wise HSE analytics (filter by projectName)
# =============================================================================

class HSERecord(models.Model):
    """
    Project-level HSE (Health, Safety & Environment) record.

    Stores cumulative incident counts and manhour data for a single project.
    One record per project — use PUT /api/hse/{id}/ to update as new data arrives.

    Field naming uses camelCase to match the frontend HSE edit modal and
    dashboard card expectations directly (no transformation needed).
    """

    # -------------------------------------------------------------------------
    # Core identifier
    # -------------------------------------------------------------------------
    projectName = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique project name for this HSE record",
    )

    # -------------------------------------------------------------------------
    # Incident counts (all non-negative integers)
    # -------------------------------------------------------------------------
    fatalities = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of fatality incidents",
    )
    significant = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of significant incidents",
    )
    major = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of major incidents",
    )
    minor = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of minor incidents",
    )
    nearMiss = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of near-miss incidents",
    )

    # -------------------------------------------------------------------------
    # Manhour data
    # -------------------------------------------------------------------------
    totalManhours = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Total manhours worked on the project",
    )
    lossOfManhours = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Total manhours lost due to incidents",
    )

    # -------------------------------------------------------------------------
    # Timestamps
    # -------------------------------------------------------------------------
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Record creation timestamp",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Last update timestamp",
    )

    # =========================================================================
    # Validation
    # =========================================================================

    def clean(self):
        """
        Cross-field validation.
        lossOfManhours must not exceed totalManhours.
        """
        if (
            self.lossOfManhours is not None
            and self.totalManhours is not None
            and self.lossOfManhours > self.totalManhours
        ):
            raise ValidationError(
                {
                    "lossOfManhours": (
                        "lossOfManhours cannot exceed totalManhours. "
                        f"Got lossOfManhours={self.lossOfManhours}, "
                        f"totalManhours={self.totalManhours}."
                    )
                }
            )

    # =========================================================================
    # Save override
    # =========================================================================

    def save(self, *args, **kwargs):
        """
        Normalize projectName and run full validation before persisting.
        """
        if self.projectName:
            self.projectName = self.projectName.strip()
        self.full_clean()
        super().save(*args, **kwargs)

    # =========================================================================
    # Computed properties (available in Python; not stored in DB)
    # These are exposed via the serializer for dashboard KPI cards.
    # =========================================================================

    @property
    def totalIncidents(self) -> int:
        """Sum of all incident categories."""
        return (
            self.fatalities
            + self.significant
            + self.major
            + self.minor
            + self.nearMiss
        )

    @property
    def ltifr(self) -> float:
        """
        Lost Time Injury Frequency Rate.
        LTIFR = (lossOfManhours / totalManhours) * 1,000,000
        Returns 0.0 if totalManhours is zero.
        """
        if not self.totalManhours:
            return 0.0
        return round(float(self.lossOfManhours / self.totalManhours) * 1_000_000, 2)

    @property
    def incidentRate(self) -> float:
        """
        Total Recordable Incident Rate (TRIR proxy).
        incidentRate = (totalIncidents / totalManhours) * 1,000,000
        Returns 0.0 if totalManhours is zero.
        """
        if not self.totalManhours:
            return 0.0
        return round((self.totalIncidents / float(self.totalManhours)) * 1_000_000, 2)

    # =========================================================================
    # Meta & helpers
    # =========================================================================

    def __str__(self) -> str:
        return f"HSE — {self.projectName} ({self.totalIncidents} incidents)"

    class Meta:
        ordering = ["projectName"]
        verbose_name = "HSE Record"
        verbose_name_plural = "HSE Records"
        indexes = [
            models.Index(fields=["projectName"], name="hse_record_project_name_idx"),
        ]


# =============================================================================
# HEALTH & SAFETY RECORD MODEL (monthly entry)
# One record per project per month/year.
# Yearly totals are calculated dynamically using DB aggregation (Sum).
# Never stored — always computed on the fly.
# =============================================================================

class HealthSafetyRecord(models.Model):
    """
    Monthly Health & Safety record per project.

    One record per (project_name, month, year).
    Yearly totals are aggregated dynamically — never stored.

    Computed properties (not stored):
      - total_incidents  = fatalities + significant + major + minor + near_miss
      - ltifr            = (loss_of_manhours / total_manhours) * 1,000,000
      - incident_rate    = (total_incidents / total_manhours) * 1,000,000
    """

    # -------------------------------------------------------------------------
    # Core identifiers
    # -------------------------------------------------------------------------
    project_name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Project name for this monthly HSE record",
    )
    month = models.PositiveSmallIntegerField(
        db_index=True,
        help_text="Month number (1–12)",
    )
    year = models.PositiveSmallIntegerField(
        db_index=True,
        help_text="Year (e.g. 2026)",
    )

    # -------------------------------------------------------------------------
    # Incident counts
    # -------------------------------------------------------------------------
    fatalities = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of fatality incidents this month",
    )
    significant = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of significant incidents this month",
    )
    major = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of major incidents this month",
    )
    minor = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of minor incidents this month",
    )
    near_miss = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of near-miss incidents this month",
    )

    # -------------------------------------------------------------------------
    # Manhour data
    # -------------------------------------------------------------------------
    total_manhours = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Total manhours worked this month",
    )
    loss_of_manhours = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Manhours lost due to incidents this month",
    )

    # -------------------------------------------------------------------------
    # Timestamps
    # -------------------------------------------------------------------------
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # =========================================================================
    # Validation
    # =========================================================================

    def clean(self):
        errors = {}

        if self.month is not None and not (1 <= self.month <= 12):
            errors["month"] = "month must be between 1 and 12."

        if self.year is not None and not (2000 <= self.year <= 2100):
            errors["year"] = "year must be between 2000 and 2100."

        if (
            self.loss_of_manhours is not None
            and self.total_manhours is not None
            and self.loss_of_manhours > self.total_manhours
        ):
            errors["loss_of_manhours"] = (
                f"loss_of_manhours ({self.loss_of_manhours}) cannot exceed "
                f"total_manhours ({self.total_manhours})."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.project_name:
            self.project_name = self.project_name.strip()
        self.full_clean()
        super().save(*args, **kwargs)

    # =========================================================================
    # Computed properties
    # =========================================================================

    @property
    def total_incidents(self) -> int:
        return (
            self.fatalities
            + self.significant
            + self.major
            + self.minor
            + self.near_miss
        )

    @property
    def ltifr(self) -> float:
        """Lost Time Injury Frequency Rate = (loss_of_manhours / total_manhours) * 1,000,000"""
        if not self.total_manhours:
            return 0.0
        return round(float(self.loss_of_manhours / self.total_manhours) * 1_000_000, 2)

    @property
    def incident_rate(self) -> float:
        """Incident Rate = (total_incidents / total_manhours) * 1,000,000"""
        if not self.total_manhours:
            return 0.0
        return round((self.total_incidents / float(self.total_manhours)) * 1_000_000, 2)

    def __str__(self) -> str:
        return f"HSE Monthly — {self.project_name} ({self.month:02d}/{self.year})"

    class Meta:
        ordering = ["project_name", "year", "month"]
        verbose_name = "Health & Safety Record"
        verbose_name_plural = "Health & Safety Records"
        db_table = "health_safety_healthsafetyrecord"
        unique_together = [("project_name", "month", "year")]
        indexes = [
            models.Index(fields=["project_name", "year", "month"], name="mhse_proj_year_month_idx"),
            models.Index(fields=["year", "month"], name="mhse_year_month_idx"),
        ]
