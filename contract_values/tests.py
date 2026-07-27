from decimal import Decimal

from django.contrib.auth.models import Group, User
from rest_framework import status
from rest_framework.test import APITestCase

from core.test_auth import authenticate_client
from contractors.models import Contractor
from projects.models import Project

from .models.contract_value import ContractValue


class MultiContractorContractValuesAPITest(APITestCase):
    CREATE_URL = "/api/contract-values/"
    BY_PROJECT_URL = "/api/contract-values/project/Thane%20Project/"

    def setUp(self):
        self.project = Project.objects.create(name="Thane Project", status="active")
        tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.user = User.objects.create_user("cv_tl_user", password="testpass123")
        self.user.groups.add(tl_group)
        self.project.team_lead = self.user
        self.project.save()

        authenticate_client(self.client, username="cv_tl_user", password="testpass123")
        ContractValue.objects.filter(project_name__iexact="Thane Project").delete()
        Contractor.objects.filter(project=self.project).delete()

    def _ensure_contractor(self, name: str) -> int:
        contractor, _ = Contractor.objects.get_or_create(
            project=self.project,
            contractor_name=name,
            defaults={"status": Contractor.Status.ACTIVE},
        )
        return contractor.id

    def _create_scl(self, **overrides):
        payload = {
            "project_name": "Thane Project",
            "contract_type": "SCL",
            "original_contract_value": "10000000.00",
            "excess_value": "500000.00",
            "saving": "250000.00",
        }
        payload.update(overrides)
        return self.client.post(self.CREATE_URL, payload, format="json")

    def _create_contractor(self, name, **overrides):
        payload = {
            "project_name": "Thane Project",
            "contract_type": "CONTRACTOR",
            "contractor_id": self._ensure_contractor(name),
            "original_contract_value": "5000000.00",
            "excess_value": "100000.00",
            "saving": "50000.00",
        }
        payload.update(overrides)
        return self.client.post(self.CREATE_URL, payload, format="json")

    def test_create_multiple_contractors(self):
        self._create_scl()
        r1 = self._create_contractor("ABC Infra")
        r2 = self._create_contractor("XYZ Construction")
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED)

        response = self.client.get(self.BY_PROJECT_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(len(data["contractors"]), 2)
        names = {c["contractor_name"] for c in data["contractors"]}
        self.assertEqual(names, {"ABC Infra", "XYZ Construction"})
        self.assertIsNotNone(data["scl"])
        self.assertEqual(data["contractor"]["contractor_name"], "ABC Infra")

    def test_upsert_isolated_per_contractor(self):
        self._create_contractor("ABC Infra", original_contract_value="100.00")
        self._create_contractor("XYZ Construction", original_contract_value="200.00")

        self._create_contractor("ABC Infra", original_contract_value="150.00")

        response = self.client.get(self.BY_PROJECT_URL)
        contractors = response.data["data"]["contractors"]
        abc = next(c for c in contractors if c["contractor_name"] == "ABC Infra")
        xyz = next(c for c in contractors if c["contractor_name"] == "XYZ Construction")
        self.assertEqual(
            Decimal(abc["contract_values"]["original_contract_value"]), Decimal("150.00")
        )
        self.assertEqual(
            Decimal(xyz["contract_values"]["original_contract_value"]), Decimal("200.00")
        )

    def test_contractor_name_required_for_contractor_type(self):
        response = self.client.post(
            self.CREATE_URL,
            {
                "project_name": "Thane Project",
                "contract_type": "CONTRACTOR",
                "original_contract_value": "100.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("contractor_id", response.data["errors"])

    def test_delete_one_contractor_leaves_others(self):
        self._create_contractor("ABC Infra")
        r2 = self._create_contractor("XYZ Construction")
        contractor_b_id = r2.data["data"]["id"]

        delete_response = self.client.delete(f"{self.CREATE_URL}{contractor_b_id}/")
        self.assertEqual(delete_response.status_code, status.HTTP_200_OK)

        response = self.client.get(self.BY_PROJECT_URL)
        contractors = response.data["data"]["contractors"]
        self.assertEqual(len(contractors), 1)
        self.assertEqual(contractors[0]["contractor_name"], "ABC Infra")

    def test_get_by_type_requires_contractor_name_when_multiple(self):
        self._create_contractor("ABC Infra")
        self._create_contractor("XYZ Construction")

        url = "/api/contract-values/project/Thane%20Project/type/CONTRACTOR/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get(f"{url}?contractor_id={self._ensure_contractor('XYZ Construction')}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["contractor_name"], "XYZ Construction")

    def test_get_by_type_returns_selected_contractor_values(self):
        abc_id = self._ensure_contractor("ABC Infra")
        xyz_id = self._ensure_contractor("XYZ Construction")
        self._create_contractor("ABC Infra", original_contract_value="100.00")
        self._create_contractor("XYZ Construction", original_contract_value="200.00")

        url = "/api/contract-values/project/Thane%20Project/type/CONTRACTOR/"

        abc_response = self.client.get(f"{url}?contractor_id={abc_id}")
        self.assertEqual(abc_response.status_code, status.HTTP_200_OK)
        self.assertEqual(abc_response.data["data"]["contractor"]["id"], abc_id)
        self.assertEqual(
            Decimal(abc_response.data["data"]["original_contract_value"]),
            Decimal("100.00"),
        )

        xyz_response = self.client.get(f"{url}?contractor_id={xyz_id}")
        self.assertEqual(xyz_response.status_code, status.HTTP_200_OK)
        self.assertEqual(xyz_response.data["data"]["contractor"]["id"], xyz_id)
        self.assertEqual(
            Decimal(xyz_response.data["data"]["original_contract_value"]),
            Decimal("200.00"),
        )

    def test_get_by_type_wrong_contractor_id_returns_404(self):
        self._create_contractor("ABC Infra")
        url = "/api/contract-values/project/Thane%20Project/type/CONTRACTOR/"
        response = self.client.get(f"{url}?contractor_id=99999")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ContractorSummaryContractValuesAPITest(APITestCase):
    CREATE_URL = "/api/contract-values/"
    BY_PROJECT_URL = "/api/contract-values/project/Thane%20Project/"

    def setUp(self):
        self.project = Project.objects.create(name="Thane Project", status="active")
        tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.user = User.objects.create_user("cv_summary_user", password="testpass123")
        self.user.groups.add(tl_group)
        self.project.team_lead = self.user
        self.project.save()

        authenticate_client(self.client, username="cv_summary_user", password="testpass123")
        ContractValue.objects.filter(project_name__iexact="Thane Project").delete()
        Contractor.objects.filter(project=self.project).delete()

    def _ensure_contractor(self, name: str) -> int:
        contractor, _ = Contractor.objects.get_or_create(
            project=self.project,
            contractor_name=name,
            defaults={"status": Contractor.Status.ACTIVE},
        )
        return contractor.id

    def _create_scl(self, **overrides):
        payload = {
            "project_name": "Thane Project",
            "contract_type": "SCL",
            "original_contract_value": "10000000.00",
            "excess_value": "500000.00",
            "saving": "250000.00",
        }
        payload.update(overrides)
        return self.client.post(self.CREATE_URL, payload, format="json")

    def _create_contractor(self, name, **overrides):
        payload = {
            "project_name": "Thane Project",
            "contract_type": "CONTRACTOR",
            "contractor_id": self._ensure_contractor(name),
            "original_contract_value": "5000000.00",
            "excess_value": "100000.00",
            "saving": "50000.00",
        }
        payload.update(overrides)
        return self.client.post(self.CREATE_URL, payload, format="json")

    def _get_summary(self) -> dict:
        response = self.client.get(self.BY_PROJECT_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        summary = response.data["data"]["contractor_summary"]
        self.assertIsNotNone(summary)
        return summary

    def test_no_contractors_summary_is_zeros(self):
        self._create_scl()
        summary = self._get_summary()
        self.assertEqual(Decimal(summary["original_contract_value"]), Decimal("0"))
        self.assertEqual(Decimal(summary["revised_value"]), Decimal("0"))
        self.assertEqual(Decimal(summary["excess_value"]), Decimal("0"))
        self.assertEqual(Decimal(summary["saving"]), Decimal("0"))
        self.assertEqual(Decimal(summary["cos"]), Decimal("0"))
        self.assertEqual(Decimal(summary["increase_percentage"]), Decimal("0"))

    def test_single_contractor_summary_matches_record(self):
        self._create_contractor(
            "ABC Infra",
            original_contract_value="10000000.00",
            excess_value="300000.00",
            saving="100000.00",
        )
        summary = self._get_summary()
        self.assertEqual(Decimal(summary["original_contract_value"]), Decimal("10000000.00"))
        self.assertEqual(Decimal(summary["excess_value"]), Decimal("300000.00"))
        self.assertEqual(Decimal(summary["saving"]), Decimal("100000.00"))
        self.assertEqual(Decimal(summary["revised_value"]), Decimal("10200000.00"))
        self.assertEqual(Decimal(summary["increase_percentage"]), Decimal("2.00"))

    def test_multiple_contractors_cumulative_summary(self):
        self._create_contractor(
            "ABC Infra",
            original_contract_value="10000000.00",
            excess_value="300000.00",
            saving="100000.00",
        )
        self._create_contractor(
            "XYZ Construction",
            original_contract_value="5000000.00",
            excess_value="300000.00",
            saving="50000.00",
        )
        summary = self._get_summary()
        self.assertEqual(Decimal(summary["original_contract_value"]), Decimal("15000000.00"))
        self.assertEqual(Decimal(summary["excess_value"]), Decimal("600000.00"))
        self.assertEqual(Decimal(summary["saving"]), Decimal("150000.00"))
        self.assertEqual(Decimal(summary.get("cos", 0)), Decimal("0"))
        self.assertEqual(Decimal(summary["revised_value"]), Decimal("15450000.00"))
        self.assertEqual(Decimal(summary["increase_percentage"]), Decimal("3.00"))

    def test_zero_values_summary(self):
        self._create_contractor(
            "ABC Infra",
            original_contract_value="0.00",
            excess_value="0.00",
            saving="0.00",
        )
        summary = self._get_summary()
        self.assertEqual(Decimal(summary["original_contract_value"]), Decimal("0"))
        self.assertEqual(Decimal(summary["revised_value"]), Decimal("0"))
        self.assertEqual(Decimal(summary["increase_percentage"]), Decimal("0"))

    def test_percentage_from_cumulative_totals_not_average(self):
        self._create_contractor(
            "ABC Infra",
            original_contract_value="100.00",
            excess_value="10.00",
            saving="0.00",
        )
        self._create_contractor(
            "XYZ Construction",
            original_contract_value="100.00",
            excess_value="30.00",
            saving="0.00",
        )
        summary = self._get_summary()
        self.assertEqual(Decimal(summary["original_contract_value"]), Decimal("200.00"))
        self.assertEqual(Decimal(summary["revised_value"]), Decimal("240.00"))
        self.assertEqual(Decimal(summary["increase_percentage"]), Decimal("20.00"))


class ContractValueCosAPITest(APITestCase):
    """COS (Change of Scope) belongs on contract values, not contract performance."""

    CREATE_URL = "/api/contract-values/"
    BY_PROJECT_URL = "/api/contract-values/project/Thane%20Project/"

    def setUp(self):
        self.project = Project.objects.create(name="Thane Project", status="active")
        tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.user = User.objects.create_user("cv_cos_user", password="testpass123")
        self.user.groups.add(tl_group)
        self.project.team_lead = self.user
        self.project.save()

        authenticate_client(self.client, username="cv_cos_user", password="testpass123")
        ContractValue.objects.filter(project_name__iexact="Thane Project").delete()

    def test_create_scl_with_cos(self):
        response = self.client.post(
            self.CREATE_URL,
            {
                "project_name": "Thane Project",
                "contract_type": "SCL",
                "original_contract_value": "10000000.00",
                "excess_value": "500000.00",
                "saving": "250000.00",
                "cos": "75000.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(response.data["data"]["cos"]), Decimal("75000.00"))
        self.assertEqual(Decimal(response.data["data"]["Cos"]), Decimal("75000.00"))
        # COS does not change revised_value formula
        self.assertEqual(Decimal(response.data["data"]["revised_value"]), Decimal("10250000.00"))

    def test_create_accepts_Cos_and_COS_aliases(self):
        r1 = self.client.post(
            self.CREATE_URL,
            {
                "project_name": "Thane Project",
                "contract_type": "SCL",
                "original_contract_value": "100.00",
                "Cos": "12.50",
            },
            format="json",
        )
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Decimal(r1.data["data"]["cos"]), Decimal("12.50"))

        record_id = r1.data["data"]["id"]
        r2 = self.client.patch(
            f"{self.CREATE_URL}{record_id}/",
            {"COS": "99.00"},
            format="json",
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(r2.data["data"]["cos"]), Decimal("99.00"))

    def test_project_summary_includes_cos(self):
        contractor, _ = Contractor.objects.get_or_create(
            project=self.project,
            contractor_name="ABC Infra",
            defaults={"status": Contractor.Status.ACTIVE},
        )
        self.client.post(
            self.CREATE_URL,
            {
                "project_name": "Thane Project",
                "contract_type": "CONTRACTOR",
                "contractor_id": contractor.id,
                "original_contract_value": "1000.00",
                "excess_value": "0.00",
                "saving": "0.00",
                "cos": "40.00",
            },
            format="json",
        )
        response = self.client.get(self.BY_PROJECT_URL)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        summary = response.data["data"]["contractor_summary"]
        self.assertEqual(Decimal(summary["cos"]), Decimal("40.00"))
