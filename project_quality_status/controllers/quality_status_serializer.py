"""
Project Quality Status Serializer.

Writable: projectName, month, year, tests_required, tests_conducted,
          tests_passed, tests_failed

Computed (never stored): shortfall, quality_performance, pass_rate, fail_rate
Legacy read aliases: totalTestsConducted, totalTestsPassed, variance,
                     performancePercentage, qualityStatus, failedTests
"""

from rest_framework import serializers

from ..models.project_quality_status import ProjectQualityStatus
from .quality_metrics import (
    compute_fail_rate,
    compute_pass_rate,
    compute_quality_performance,
    compute_shortfall,
    metrics_from_record,
    quality_status_from_performance,
)


class ProjectQualityStatusSerializer(serializers.ModelSerializer):
    """Full serializer for monthly ProjectQualityStatus records."""

    project_name = serializers.SerializerMethodField()

    shortfall = serializers.SerializerMethodField()
    quality_performance = serializers.SerializerMethodField()
    pass_rate = serializers.SerializerMethodField()
    fail_rate = serializers.SerializerMethodField()

    # Legacy aliases (read-only, backward compatible)
    totalTestsConducted = serializers.IntegerField(source="tests_conducted", read_only=True)
    totalTestsPassed = serializers.IntegerField(source="tests_passed", read_only=True)
    variance = serializers.SerializerMethodField()
    performancePercentage = serializers.SerializerMethodField()
    qualityStatus = serializers.SerializerMethodField()
    failedTests = serializers.IntegerField(source="tests_failed", read_only=True)

    projectName = serializers.CharField(max_length=255)

    class Meta:
        model = ProjectQualityStatus
        fields = [
            "id",
            "projectName",
            "project_name",
            "month",
            "year",
            "tests_required",
            "tests_conducted",
            "tests_passed",
            "tests_failed",
            "shortfall",
            "quality_performance",
            "pass_rate",
            "fail_rate",
            # Legacy
            "totalTestsConducted",
            "totalTestsPassed",
            "variance",
            "performancePercentage",
            "qualityStatus",
            "failedTests",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "project_name",
            "shortfall",
            "quality_performance",
            "pass_rate",
            "fail_rate",
            "totalTestsConducted",
            "totalTestsPassed",
            "variance",
            "performancePercentage",
            "qualityStatus",
            "failedTests",
            "created_at",
            "updated_at",
        ]
        validators = []

    def get_project_name(self, obj) -> str:
        return obj.projectName

    def get_shortfall(self, obj) -> int:
        return compute_shortfall(obj.tests_required, obj.tests_conducted)

    def get_quality_performance(self, obj) -> float:
        return compute_quality_performance(obj.tests_passed, obj.tests_conducted)

    def get_pass_rate(self, obj) -> float:
        return compute_pass_rate(obj.tests_passed, obj.tests_required)

    def get_fail_rate(self, obj) -> float:
        return compute_fail_rate(obj.tests_failed, obj.tests_conducted)

    def get_variance(self, obj) -> int:
        """Legacy: failed + pending vs old variance semantics."""
        return obj.tests_failed

    def get_performancePercentage(self, obj) -> float:
        return self.get_quality_performance(obj)

    def get_qualityStatus(self, obj) -> str:
        return quality_status_from_performance(self.get_quality_performance(obj))

    def to_internal_value(self, data):
        if hasattr(data, "copy"):
            data = data.copy()
        else:
            data = dict(data)

        if "project_name" in data and "projectName" not in data:
            data["projectName"] = data["project_name"]

        # Legacy field mapping
        if "total_tests_conducted" in data and "tests_conducted" not in data:
            data["tests_conducted"] = data["total_tests_conducted"]
        if "totalTestsConducted" in data and "tests_conducted" not in data:
            data["tests_conducted"] = data["totalTestsConducted"]

        if "total_tests_passed" in data and "tests_passed" not in data:
            data["tests_passed"] = data["total_tests_passed"]
        if "totalTestsPassed" in data and "tests_passed" not in data:
            data["tests_passed"] = data["totalTestsPassed"]

        if "total_tests_failed" in data and "tests_failed" not in data:
            data["tests_failed"] = data["total_tests_failed"]
        if "failed_tests" in data and "tests_failed" not in data:
            data["tests_failed"] = data["failed_tests"]

        return super().to_internal_value(data)

    def validate_projectName(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("projectName cannot be blank.")
        return value.strip()

    def validate_month(self, value: int) -> int:
        if not (1 <= value <= 12):
            raise serializers.ValidationError("month must be between 1 and 12.")
        return value

    def validate_year(self, value: int) -> int:
        if not (2000 <= value <= 2100):
            raise serializers.ValidationError("year must be between 2000 and 2100.")
        return value

    def _validate_non_negative(self, value: int, field_name: str) -> int:
        if value < 0:
            raise serializers.ValidationError(f"{field_name} must be >= 0.")
        return value

    def validate_tests_required(self, value):
        return self._validate_non_negative(value, "tests_required")

    def validate_tests_conducted(self, value):
        return self._validate_non_negative(value, "tests_conducted")

    def validate_tests_passed(self, value):
        return self._validate_non_negative(value, "tests_passed")

    def validate_tests_failed(self, value):
        return self._validate_non_negative(value, "tests_failed")

    def validate(self, attrs: dict) -> dict:
        instance = self.instance

        conducted = attrs.get(
            "tests_conducted",
            getattr(instance, "tests_conducted", 0) if instance else 0,
        )
        passed = attrs.get(
            "tests_passed",
            getattr(instance, "tests_passed", 0) if instance else 0,
        )
        failed = attrs.get(
            "tests_failed",
            getattr(instance, "tests_failed", 0) if instance else 0,
        )

        if passed + failed > conducted:
            raise serializers.ValidationError(
                {
                    "tests_passed": (
                        f"tests_passed ({passed}) + tests_failed ({failed}) cannot exceed "
                        f"tests_conducted ({conducted})."
                    )
                }
            )

        return attrs
