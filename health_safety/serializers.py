# Health & Safety Serializers
from decimal import Decimal
from rest_framework import serializers
from .models import HealthSafetyReport

# Constants for incident types
INCIDENT_KEYS = ['fatalities', 'significant', 'major', 'minor', 'near_miss']


class HealthSafetyInputSerializer(serializers.Serializer):
    """
    Serializer for input data - accepts JSON as per requirements
    """
    totalManhours = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0'), required=True)
    incidents = serializers.DictField(
        child=serializers.IntegerField(min_value=0),
        required=True
    )

    def validate_incidents(self, value):
        """
        Validate that all required incident keys are present
        """
        missing_keys = set(INCIDENT_KEYS) - set(value.keys())
        if missing_keys:
            raise serializers.ValidationError(f"Missing required incident keys: {', '.join(missing_keys)}")
        return value


class HealthSafetyReportSerializer(serializers.ModelSerializer):
    """
    Serializer for Health & Safety Report model
    """
    totalIncidents = serializers.IntegerField(source='total_incidents', read_only=True)

    class Meta:
        model = HealthSafetyReport
        fields = [
            'id', 'project_name', 'report_date', 'total_manhours',
            'fatalities', 'significant', 'major', 'minor', 'near_miss',
            'totalIncidents', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class IncidentBreakdownSerializer(serializers.Serializer):
    """Serializer for incident breakdown with counts and percentages"""
    count = serializers.IntegerField()
    percentage = serializers.DecimalField(max_digits=5, decimal_places=2)


class PyramidItemSerializer(serializers.Serializer):
    """Serializer for pyramid visualization data"""
    label = serializers.CharField()
    value = serializers.IntegerField()
    color = serializers.CharField()


class AlertFlagsSerializer(serializers.Serializer):
    """Serializer for alert flags"""
    hasFatality = serializers.BooleanField()
    highNearMiss = serializers.BooleanField()


class HealthSafetyStatusResponseSerializer(serializers.Serializer):
    """
    Complete response serializer for Health & Safety Status API
    Returns all calculated metrics and pyramid data
    """
    summary = serializers.DictField()
    breakdown = serializers.DictField()
    pyramid = PyramidItemSerializer(many=True)
    insights = serializers.ListField(child=serializers.CharField())
    alerts = AlertFlagsSerializer(required=False)
    severityIndex = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)


# =============================================================================
# HSE RECORD SERIALIZER
# Handles input validation and output formatting for HSERecord.
# Uses camelCase field names to match the frontend HSE edit modal directly.
# =============================================================================

from .models import HSERecord  # noqa: E402 — appended after existing imports


class HSERecordSerializer(serializers.ModelSerializer):
    """
    Serializer for the HSERecord model.

    Read-only computed fields exposed for dashboard KPI cards:
      - totalIncidents   : sum of all incident categories
      - ltifr            : Lost Time Injury Frequency Rate
      - incidentRate     : Total incidents per 1,000,000 manhours

    Writable fields (all validated non-negative):
      - projectName, fatalities, significant, major, minor,
        nearMiss, totalManhours, lossOfManhours
    """

    # Computed properties from the model — read-only, never sent by the client
    totalIncidents = serializers.IntegerField(read_only=True)
    ltifr = serializers.FloatField(read_only=True)
    incidentRate = serializers.FloatField(read_only=True)

    class Meta:
        model = HSERecord
        fields = [
            "id",
            "projectName",
            "fatalities",
            "significant",
            "major",
            "minor",
            "nearMiss",
            "totalManhours",
            "lossOfManhours",
            # Computed KPI fields (read-only)
            "totalIncidents",
            "ltifr",
            "incidentRate",
            # Timestamps
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "totalIncidents",
            "ltifr",
            "incidentRate",
            "created_at",
            "updated_at",
        ]

    # -------------------------------------------------------------------------
    # Field-level validation
    # -------------------------------------------------------------------------

    def validate_projectName(self, value: str) -> str:
        """Strip whitespace and reject blank project names."""
        if not value or not value.strip():
            raise serializers.ValidationError("projectName cannot be blank.")
        return value.strip()

    def _validate_non_negative_int(self, value: int, field_name: str) -> int:
        """Reusable helper: ensure integer field is >= 0."""
        if value < 0:
            raise serializers.ValidationError(f"{field_name} must be >= 0.")
        return value

    def _validate_non_negative_decimal(self, value, field_name: str):
        """Reusable helper: ensure decimal field is >= 0."""
        if value < 0:
            raise serializers.ValidationError(f"{field_name} must be >= 0.")
        return value

    def validate_fatalities(self, value):
        return self._validate_non_negative_int(value, "fatalities")

    def validate_significant(self, value):
        return self._validate_non_negative_int(value, "significant")

    def validate_major(self, value):
        return self._validate_non_negative_int(value, "major")

    def validate_minor(self, value):
        return self._validate_non_negative_int(value, "minor")

    def validate_nearMiss(self, value):
        return self._validate_non_negative_int(value, "nearMiss")

    def validate_totalManhours(self, value):
        return self._validate_non_negative_decimal(value, "totalManhours")

    def validate_lossOfManhours(self, value):
        return self._validate_non_negative_decimal(value, "lossOfManhours")

    # -------------------------------------------------------------------------
    # Cross-field validation
    # -------------------------------------------------------------------------

    def validate(self, attrs: dict) -> dict:
        """
        Cross-field check: lossOfManhours must not exceed totalManhours.
        Falls back to existing instance values on partial updates.
        """
        instance = self.instance  # None on create, existing object on update

        total_manhours = attrs.get(
            "totalManhours",
            getattr(instance, "totalManhours", 0) if instance else 0,
        )
        loss_of_manhours = attrs.get(
            "lossOfManhours",
            getattr(instance, "lossOfManhours", 0) if instance else 0,
        )

        if loss_of_manhours > total_manhours:
            raise serializers.ValidationError(
                {
                    "lossOfManhours": (
                        f"lossOfManhours ({loss_of_manhours}) cannot exceed "
                        f"totalManhours ({total_manhours})."
                    )
                }
            )

        return attrs


# =============================================================================
# HEALTH & SAFETY RECORD SERIALIZER (monthly entry)
# =============================================================================

from .models import HealthSafetyRecord  # noqa: E402


class HealthSafetyRecordSerializer(serializers.ModelSerializer):
    """
    Serializer for HealthSafetyRecord.

    Writable fields include legacy incidents/manhours plus monthly statistics.
    Auto-calculated (read-only on write path via model.save):
      man_days_worked, man_hours_worked, medical_checkup_total
      (total_manhours synced from man_hours_worked when working_days > 0)

    Read-only computed:
      total_incidents, ltifr, incident_rate
    """

    total_incidents = serializers.IntegerField(read_only=True)
    ltifr = serializers.FloatField(read_only=True)
    incident_rate = serializers.FloatField(read_only=True)
    man_days_worked = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    man_hours_worked = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    medical_checkup_total = serializers.IntegerField(read_only=True)

    class Meta:
        model = HealthSafetyRecord
        fields = [
            "id",
            "project_name",
            "month",
            "year",
            "fatalities",
            "significant",
            "major",
            "minor",
            "near_miss",
            "total_manhours",
            "loss_of_manhours",
            # Monthly statistics
            "average_daily_manpower",
            "working_days",
            "man_days_worked",
            "man_hours_worked",
            "reportable_accident_lti",
            "dangerous_occurrences",
            "first_aid_cases",
            "medical_treatment_cases",
            "utility_damage",
            "internal_training_count",
            "internal_training_hours",
            "external_training_count",
            "external_training_hours",
            "mock_drills",
            "medical_checkup_workers",
            "medical_checkup_staff",
            "medical_checkup_total",
            # Computed
            "total_incidents",
            "ltifr",
            "incident_rate",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "man_days_worked",
            "man_hours_worked",
            "medical_checkup_total",
            "total_incidents",
            "ltifr",
            "incident_rate",
            "created_at",
            "updated_at",
        ]
        # Suppress auto UniqueTogetherValidator — controller handles upsert
        validators = []

    # -------------------------------------------------------------------------
    # Field-level validation
    # -------------------------------------------------------------------------

    def validate_project_name(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("project_name cannot be blank.")
        return value.strip()

    def validate_month(self, value: int) -> int:
        if not (1 <= value <= 12):
            raise serializers.ValidationError("month must be between 1 and 12.")
        return value

    def validate_year(self, value: int) -> int:
        if not (2000 <= value <= 2100):
            raise serializers.ValidationError("year must be between 2000 and 2100.")
        return value

    def _validate_non_negative(self, value, field_name: str):
        if value is None:
            return value
        if value < 0:
            raise serializers.ValidationError(f"{field_name} must be >= 0.")
        return value

    def validate_fatalities(self, v):
        return self._validate_non_negative(v, "fatalities")

    def validate_significant(self, v):
        return self._validate_non_negative(v, "significant")

    def validate_major(self, v):
        return self._validate_non_negative(v, "major")

    def validate_minor(self, v):
        return self._validate_non_negative(v, "minor")

    def validate_near_miss(self, v):
        return self._validate_non_negative(v, "near_miss")

    def validate_total_manhours(self, v):
        return self._validate_non_negative(v, "total_manhours")

    def validate_loss_of_manhours(self, v):
        return self._validate_non_negative(v, "loss_of_manhours")

    def validate_average_daily_manpower(self, v):
        return self._validate_non_negative(v, "average_daily_manpower")

    def validate_working_days(self, v):
        if v is None:
            return v
        if v < 0:
            raise serializers.ValidationError("working_days must be >= 0.")
        return v

    def validate_reportable_accident_lti(self, v):
        return self._validate_non_negative(v, "reportable_accident_lti")

    def validate_dangerous_occurrences(self, v):
        return self._validate_non_negative(v, "dangerous_occurrences")

    def validate_first_aid_cases(self, v):
        return self._validate_non_negative(v, "first_aid_cases")

    def validate_medical_treatment_cases(self, v):
        return self._validate_non_negative(v, "medical_treatment_cases")

    def validate_utility_damage(self, v):
        return self._validate_non_negative(v, "utility_damage")

    def validate_internal_training_count(self, v):
        return self._validate_non_negative(v, "internal_training_count")

    def validate_internal_training_hours(self, v):
        return self._validate_non_negative(v, "internal_training_hours")

    def validate_external_training_count(self, v):
        return self._validate_non_negative(v, "external_training_count")

    def validate_external_training_hours(self, v):
        return self._validate_non_negative(v, "external_training_hours")

    def validate_mock_drills(self, v):
        return self._validate_non_negative(v, "mock_drills")

    def validate_medical_checkup_workers(self, v):
        return self._validate_non_negative(v, "medical_checkup_workers")

    def validate_medical_checkup_staff(self, v):
        return self._validate_non_negative(v, "medical_checkup_staff")

    # -------------------------------------------------------------------------
    # Cross-field validation
    # -------------------------------------------------------------------------

    def validate(self, attrs: dict) -> dict:
        instance = self.instance

        average_daily_manpower = attrs.get(
            "average_daily_manpower",
            getattr(instance, "average_daily_manpower", 0) if instance else 0,
        )
        working_days = attrs.get(
            "working_days",
            getattr(instance, "working_days", 0) if instance else 0,
        )

        # When submitting manpower stats, working_days must be > 0
        try:
            adm = float(average_daily_manpower or 0)
        except (TypeError, ValueError):
            adm = 0
        if adm > 0 and (working_days is None or working_days <= 0):
            raise serializers.ValidationError(
                {"working_days": "working_days must be > 0 when average_daily_manpower is set."}
            )

        # Preview totals for loss_of_manhours check (mirrors model recalculate)
        if working_days and working_days > 0:
            from decimal import Decimal

            man_days = Decimal(str(average_daily_manpower or 0)) * Decimal(working_days)
            total_manhours = (man_days * Decimal("8")).quantize(Decimal("0.01"))
        else:
            total_manhours = attrs.get(
                "total_manhours",
                getattr(instance, "total_manhours", 0) if instance else 0,
            )

        loss_of_manhours = attrs.get(
            "loss_of_manhours",
            getattr(instance, "loss_of_manhours", 0) if instance else 0,
        )

        if loss_of_manhours > total_manhours:
            raise serializers.ValidationError(
                {
                    "loss_of_manhours": (
                        f"loss_of_manhours ({loss_of_manhours}) cannot exceed "
                        f"total_manhours ({total_manhours})."
                    )
                }
            )

        return attrs


class HealthSafetyRecordDataSerializer(serializers.Serializer):
    """Core monthly HSE fields returned by read endpoints."""

    month = serializers.IntegerField()
    year = serializers.IntegerField()
    fatalities = serializers.IntegerField()
    significant = serializers.IntegerField()
    major = serializers.IntegerField()
    minor = serializers.IntegerField()
    near_miss = serializers.IntegerField()
    total_manhours = serializers.DecimalField(max_digits=18, decimal_places=2)
    loss_of_manhours = serializers.DecimalField(max_digits=18, decimal_places=2)
    average_daily_manpower = serializers.DecimalField(max_digits=18, decimal_places=2)
    working_days = serializers.IntegerField()
    man_days_worked = serializers.DecimalField(max_digits=18, decimal_places=2)
    man_hours_worked = serializers.DecimalField(max_digits=18, decimal_places=2)
    reportable_accident_lti = serializers.IntegerField()
    dangerous_occurrences = serializers.IntegerField()
    first_aid_cases = serializers.IntegerField()
    medical_treatment_cases = serializers.IntegerField()
    utility_damage = serializers.IntegerField()
    internal_training_count = serializers.IntegerField()
    internal_training_hours = serializers.DecimalField(max_digits=18, decimal_places=2)
    external_training_count = serializers.IntegerField()
    external_training_hours = serializers.DecimalField(max_digits=18, decimal_places=2)
    mock_drills = serializers.IntegerField()
    medical_checkup_workers = serializers.IntegerField()
    medical_checkup_staff = serializers.IntegerField()
    medical_checkup_total = serializers.IntegerField()


class YearlySummarySerializer(serializers.Serializer):
    """Read-only serializer for yearly aggregated HSE data."""

    project_name = serializers.CharField()
    year = serializers.IntegerField()
    fatalities = serializers.IntegerField()
    significant = serializers.IntegerField()
    major = serializers.IntegerField()
    minor = serializers.IntegerField()
    near_miss = serializers.IntegerField()
    total_manhours = serializers.DecimalField(max_digits=18, decimal_places=2)
    loss_of_manhours = serializers.DecimalField(max_digits=18, decimal_places=2)
    average_daily_manpower = serializers.DecimalField(max_digits=18, decimal_places=2)
    working_days = serializers.IntegerField()
    man_days_worked = serializers.DecimalField(max_digits=18, decimal_places=2)
    man_hours_worked = serializers.DecimalField(max_digits=18, decimal_places=2)
    reportable_accident_lti = serializers.IntegerField()
    dangerous_occurrences = serializers.IntegerField()
    first_aid_cases = serializers.IntegerField()
    medical_treatment_cases = serializers.IntegerField()
    utility_damage = serializers.IntegerField()
    internal_training_count = serializers.IntegerField()
    internal_training_hours = serializers.DecimalField(max_digits=18, decimal_places=2)
    external_training_count = serializers.IntegerField()
    external_training_hours = serializers.DecimalField(max_digits=18, decimal_places=2)
    mock_drills = serializers.IntegerField()
    medical_checkup_workers = serializers.IntegerField()
    medical_checkup_staff = serializers.IntegerField()
    medical_checkup_total = serializers.IntegerField()
