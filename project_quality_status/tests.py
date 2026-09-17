"""
Tests for the Project Quality Status app.

Coverage:
  - Model: auto-calculations, validation, edge cases
  - Serializer: field validation, cross-field checks
  - API: CRUD endpoints + project-name lookup
"""

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models.project_quality_status import ProjectQualityStatus


# =============================================================================
# Model Tests
# =============================================================================

class ProjectQualityStatusModelTest(TestCase):
    """Unit tests for the ProjectQualityStatus model."""

    def _make(self, name="Test Project", conducted=100, passed=80):
        return ProjectQualityStatus.objects.create(
            projectName=name,
            totalTestsConducted=conducted,
            totalTestsPassed=passed,
        )

    # -------------------------------------------------------------------------
    # Auto-calculation
    # -------------------------------------------------------------------------

    def test_variance_calculated_on_save(self):
        obj = self._make(conducted=100, passed=80)
        self.assertEqual(obj.variance, 20)

    def test_performance_percentage_calculated_on_save(self):
        obj = self._make(conducted=200, passed=185)
        self.assertEqual(obj.performancePercentage, 92.5)

    def test_performance_percentage_zero_when_no_tests(self):
        obj = self._make(conducted=0, passed=0)
        self.assertEqual(obj.performancePercentage, 0.0)

    def test_performance_percentage_100_when_all_pass(self):
        obj = self._make(conducted=50, passed=50)
        self.assertEqual(obj.performancePercentage, 100.0)

    def test_variance_zero_when_all_pass(self):
        obj = self._make(conducted=50, passed=50)
        self.assertEqual(obj.variance, 0)

    def test_performance_percentage_rounded_to_2dp(self):
        # 1/3 * 100 = 33.333... → should round to 33.33
        obj = self._make(conducted=3, passed=1)
        self.assertEqual(obj.performancePercentage, 33.33)

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    def test_passed_exceeds_conducted_raises_validation_error(self):
        obj = ProjectQualityStatus(
            projectName="Bad Project",
            totalTestsConducted=50,
            totalTestsPassed=60,
        )
        with self.assertRaises(ValidationError):
            obj.save()

    def test_project_name_stripped_on_save(self):
        obj = ProjectQualityStatus.objects.create(
            projectName="  Padded Name  ",
            totalTestsConducted=10,
            totalTestsPassed=5,
        )
        self.assertEqual(obj.projectName, "Padded Name")

    def test_unique_project_name_constraint(self):
        self._make(name="Unique Project")
        with self.assertRaises(Exception):
            self._make(name="Unique Project")

    # -------------------------------------------------------------------------
    # qualityStatus property
    # -------------------------------------------------------------------------

    def test_quality_status_excellent(self):
        obj = self._make(conducted=100, passed=95)
        self.assertEqual(obj.qualityStatus, "excellent")

    def test_quality_status_good(self):
        obj = self._make(conducted=100, passed=80)
        self.assertEqual(obj.qualityStatus, "good")

    def test_quality_status_average(self):
        obj = self._make(conducted=100, passed=60)
        self.assertEqual(obj.qualityStatus, "average")

    def test_quality_status_poor(self):
        obj = self._make(conducted=100, passed=59)
        self.assertEqual(obj.qualityStatus, "poor")

    def test_quality_status_poor_when_zero_tests(self):
        obj = self._make(conducted=0, passed=0)
        self.assertEqual(obj.qualityStatus, "poor")

    # -------------------------------------------------------------------------
    # failedTests property
    # -------------------------------------------------------------------------

    def test_failed_tests_alias_for_variance(self):
        obj = self._make(conducted=100, passed=75)
        self.assertEqual(obj.failedTests, obj.variance)
        self.assertEqual(obj.failedTests, 25)

    # -------------------------------------------------------------------------
    # __str__
    # -------------------------------------------------------------------------

    def test_str_representation(self):
        obj = self._make(name="Alpha Tower", conducted=100, passed=90)
        self.assertIn("Alpha Tower", str(obj))
        self.assertIn("90/100", str(obj))

    # -------------------------------------------------------------------------
    # Recalculation on update
    # -------------------------------------------------------------------------

    def test_recalculates_on_update(self):
        obj = self._make(conducted=100, passed=80)
        obj.totalTestsPassed = 95
        obj.save()
        obj.refresh_from_db()
        self.assertEqual(obj.variance, 5)
        self.assertEqual(obj.performancePercentage, 95.0)
        self.assertEqual(obj.qualityStatus, "excellent")


# =============================================================================
# API Tests
# =============================================================================

class ProjectQualityStatusAPITest(APITestCase):
    """Integration tests for all ProjectQualityStatus API endpoints."""

    LIST_URL = "/api/project-quality-status/"

    def _detail_url(self, pk):
        return f"/api/project-quality-status/{pk}/"

    def _by_name_url(self, name):
        return f"/api/project-quality-status/project/{name}/"

    def _create_record(self, name="API Test Project", conducted=100, passed=80):
        return ProjectQualityStatus.objects.create(
            projectName=name,
            totalTestsConducted=conducted,
            totalTestsPassed=passed,
        )

    # -------------------------------------------------------------------------
    # CREATE  POST /api/project-quality-status/
    # -------------------------------------------------------------------------

    def test_create_returns_201(self):
        payload = {
            "projectName": "New Project",
            "totalTestsConducted": 100,
            "totalTestsPassed": 90,
        }
        response = self.client.post(self.LIST_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_response_envelope(self):
        payload = {
            "projectName": "Envelope Project",
            "totalTestsConducted": 100,
            "totalTestsPassed": 90,
        }
        response = self.client.post(self.LIST_URL, payload, format="json")
        self.assertTrue(response.data["success"])
        self.assertIn("data", response.data)
        self.assertIn("message", response.data)

    def test_create_auto_calculates_variance(self):
        payload = {
            "projectName": "Variance Project",
            "totalTestsConducted": 100,
            "totalTestsPassed": 75,
        }
        response = self.client.post(self.LIST_URL, payload, format="json")
        self.assertEqual(response.data["data"]["variance"], 25)

    def test_create_auto_calculates_performance_percentage(self):
        payload = {
            "projectName": "Perf Project",
            "totalTestsConducted": 200,
            "totalTestsPassed": 185,
        }
        response = self.client.post(self.LIST_URL, payload, format="json")
        self.assertEqual(response.data["data"]["performancePercentage"], 92.5)

    def test_create_includes_quality_status(self):
        payload = {
            "projectName": "Status Project",
            "totalTestsConducted": 100,
            "totalTestsPassed": 97,
        }
        response = self.client.post(self.LIST_URL, payload, format="json")
        self.assertEqual(response.data["data"]["qualityStatus"], "excellent")

    def test_create_includes_failed_tests(self):
        payload = {
            "projectName": "Failed Tests Project",
            "totalTestsConducted": 100,
            "totalTestsPassed": 70,
        }
        response = self.client.post(self.LIST_URL, payload, format="json")
        self.assertEqual(response.data["data"]["failedTests"], 30)

    def test_create_rejects_passed_exceeding_conducted(self):
        payload = {
            "projectName": "Invalid Project",
            "totalTestsConducted": 50,
            "totalTestsPassed": 60,
        }
        response = self.client.post(self.LIST_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])

    def test_create_rejects_missing_project_name(self):
        payload = {"totalTestsConducted": 100, "totalTestsPassed": 80}
        response = self.client.post(self.LIST_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_rejects_blank_project_name(self):
        payload = {
            "projectName": "   ",
            "totalTestsConducted": 100,
            "totalTestsPassed": 80,
        }
        response = self.client.post(self.LIST_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_rejects_duplicate_project_name(self):
        self._create_record(name="Duplicate Project")
        payload = {
            "projectName": "Duplicate Project",
            "totalTestsConducted": 50,
            "totalTestsPassed": 40,
        }
        response = self.client.post(self.LIST_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_zero_tests_allowed(self):
        payload = {
            "projectName": "Zero Tests Project",
            "totalTestsConducted": 0,
            "totalTestsPassed": 0,
        }
        response = self.client.post(self.LIST_URL, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["performancePercentage"], 0.0)

    # -------------------------------------------------------------------------
    # LIST  GET /api/project-quality-status/
    # -------------------------------------------------------------------------

    def test_list_returns_200(self):
        self._create_record()
        response = self.client.get(self.LIST_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_list_response_envelope(self):
        self._create_record()
        response = self.client.get(self.LIST_URL)
        self.assertTrue(response.data["success"])
        self.assertIn("data", response.data)

    def test_list_returns_all_records(self):
        self._create_record(name="Project A")
        self._create_record(name="Project B")
        self._create_record(name="Project C")
        response = self.client.get(self.LIST_URL)
        data = response.data["data"]
        # Paginated response has {"count": N, "results": [...]}
        # Non-paginated response is a list directly
        if isinstance(data, dict) and "results" in data:
            results = data["results"]
        elif isinstance(data, list):
            results = data
        else:
            results = []
        self.assertGreaterEqual(len(results), 3)

    def test_list_filter_by_project_name(self):
        self._create_record(name="Alpha Tower")
        self._create_record(name="Beta Complex")
        response = self.client.get(self.LIST_URL, {"project_name": "alpha"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        results = data.get("results", data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["projectName"], "Alpha Tower")

    def test_list_search_param(self):
        self._create_record(name="Gamma Site")
        self._create_record(name="Delta Site")
        response = self.client.get(self.LIST_URL, {"search": "gamma"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        results = data.get("results", data) if isinstance(data, dict) else data
        self.assertEqual(len(results), 1)

    # -------------------------------------------------------------------------
    # RETRIEVE  GET /api/project-quality-status/{id}/
    # -------------------------------------------------------------------------

    def test_retrieve_returns_200(self):
        obj = self._create_record()
        response = self.client.get(self._detail_url(obj.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_retrieve_returns_correct_record(self):
        obj = self._create_record(name="Retrieve Me")
        response = self.client.get(self._detail_url(obj.pk))
        self.assertEqual(response.data["data"]["projectName"], "Retrieve Me")

    def test_retrieve_nonexistent_returns_404(self):
        response = self.client.get(self._detail_url(99999))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.data["success"])

    def test_retrieve_includes_all_fields(self):
        obj = self._create_record()
        response = self.client.get(self._detail_url(obj.pk))
        data = response.data["data"]
        for field in [
            "id", "projectName", "totalTestsConducted", "totalTestsPassed",
            "variance", "performancePercentage", "qualityStatus",
            "failedTests", "created_at", "updated_at",
        ]:
            self.assertIn(field, data, f"Missing field: {field}")

    # -------------------------------------------------------------------------
    # UPDATE  PUT /api/project-quality-status/{id}/
    # -------------------------------------------------------------------------

    def test_full_update_returns_200(self):
        obj = self._create_record()
        payload = {
            "projectName": obj.projectName,
            "totalTestsConducted": 200,
            "totalTestsPassed": 180,
        }
        response = self.client.put(self._detail_url(obj.pk), payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_full_update_recalculates_fields(self):
        obj = self._create_record(conducted=100, passed=80)
        payload = {
            "projectName": obj.projectName,
            "totalTestsConducted": 200,
            "totalTestsPassed": 190,
        }
        response = self.client.put(self._detail_url(obj.pk), payload, format="json")
        self.assertEqual(response.data["data"]["variance"], 10)
        self.assertEqual(response.data["data"]["performancePercentage"], 95.0)
        self.assertEqual(response.data["data"]["qualityStatus"], "excellent")

    def test_full_update_nonexistent_returns_404(self):
        payload = {
            "projectName": "Ghost",
            "totalTestsConducted": 10,
            "totalTestsPassed": 5,
        }
        response = self.client.put(self._detail_url(99999), payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_full_update_rejects_invalid_data(self):
        obj = self._create_record()
        payload = {
            "projectName": obj.projectName,
            "totalTestsConducted": 50,
            "totalTestsPassed": 100,  # exceeds conducted
        }
        response = self.client.put(self._detail_url(obj.pk), payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # -------------------------------------------------------------------------
    # PARTIAL UPDATE  PATCH /api/project-quality-status/{id}/
    # -------------------------------------------------------------------------

    def test_partial_update_returns_200(self):
        obj = self._create_record(conducted=100, passed=80)
        response = self.client.patch(
            self._detail_url(obj.pk),
            {"totalTestsPassed": 90},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_partial_update_recalculates_fields(self):
        obj = self._create_record(conducted=100, passed=80)
        response = self.client.patch(
            self._detail_url(obj.pk),
            {"totalTestsPassed": 90},
            format="json",
        )
        self.assertEqual(response.data["data"]["variance"], 10)
        self.assertEqual(response.data["data"]["performancePercentage"], 90.0)

    def test_partial_update_rejects_passed_exceeding_conducted(self):
        obj = self._create_record(conducted=100, passed=80)
        response = self.client.patch(
            self._detail_url(obj.pk),
            {"totalTestsPassed": 150},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_partial_update_nonexistent_returns_404(self):
        response = self.client.patch(
            self._detail_url(99999),
            {"totalTestsPassed": 10},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # -------------------------------------------------------------------------
    # DELETE  DELETE /api/project-quality-status/{id}/
    # -------------------------------------------------------------------------

    def test_delete_returns_200(self):
        obj = self._create_record()
        response = self.client.delete(self._detail_url(obj.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_delete_removes_record(self):
        obj = self._create_record()
        self.client.delete(self._detail_url(obj.pk))
        self.assertFalse(
            ProjectQualityStatus.objects.filter(pk=obj.pk).exists()
        )

    def test_delete_response_includes_project_name(self):
        obj = self._create_record(name="Delete Me")
        response = self.client.delete(self._detail_url(obj.pk))
        self.assertIn("Delete Me", response.data["message"])

    def test_delete_nonexistent_returns_404(self):
        response = self.client.delete(self._detail_url(99999))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # -------------------------------------------------------------------------
    # CUSTOM ACTION  GET /api/project-quality-status/project/{projectName}/
    # -------------------------------------------------------------------------

    def test_get_by_project_name_returns_200(self):
        self._create_record(name="Named Project")
        response = self.client.get(self._by_name_url("Named Project"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_get_by_project_name_case_insensitive(self):
        self._create_record(name="Case Project")
        response = self.client.get(self._by_name_url("case project"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["projectName"], "Case Project")

    def test_get_by_project_name_returns_correct_data(self):
        self._create_record(name="Exact Match", conducted=150, passed=120)
        response = self.client.get(self._by_name_url("Exact Match"))
        data = response.data["data"]
        self.assertEqual(data["projectName"], "Exact Match")
        self.assertEqual(data["totalTestsConducted"], 150)
        self.assertEqual(data["totalTestsPassed"], 120)
        self.assertEqual(data["variance"], 30)

    def test_get_by_project_name_not_found_returns_404(self):
        response = self.client.get(self._by_name_url("Nonexistent Project"))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.data["success"])

    def test_get_by_project_name_includes_quality_status(self):
        self._create_record(name="Quality Check", conducted=100, passed=97)
        response = self.client.get(self._by_name_url("Quality Check"))
        self.assertEqual(response.data["data"]["qualityStatus"], "excellent")

    # -------------------------------------------------------------------------
    # Edge cases
    # -------------------------------------------------------------------------

    def test_project_name_with_spaces_in_url(self):
        self._create_record(name="Space Project")
        response = self.client.get(self._by_name_url("Space%20Project"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_all_quality_status_thresholds(self):
        cases = [
            ("Excellent Co", 100, 95, "excellent"),
            ("Good Co", 100, 80, "good"),
            ("Average Co", 100, 60, "average"),
            ("Poor Co", 100, 59, "poor"),
        ]
        for name, conducted, passed, expected_status in cases:
            with self.subTest(name=name):
                obj = self._create_record(name=name, conducted=conducted, passed=passed)
                self.assertEqual(obj.qualityStatus, expected_status)
