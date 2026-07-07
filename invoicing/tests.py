from decimal import Decimal

from django.contrib.auth.models import Group, User
from rest_framework import status
from rest_framework.test import APITestCase

from core.test_auth import authenticate_client
from contractors.models import Contractor
from projects.models import Project

from .models.invoicing_information import InvoicingInformation


class MultiContractorInvoicingAPITest(APITestCase):
    CREATE_URL = "/api/invoicing/"
    BY_PROJECT_URL = "/api/invoicing/project/Thane%20Project/"

    def setUp(self):
        self.project = Project.objects.create(name="Thane Project", status="active")
        bse_group, _ = Group.objects.get_or_create(name="Billing Site Engineer")
        self.user = User.objects.create_user("inv_bse_user", password="testpass123")
        self.user.groups.add(bse_group)
        self.project.billing_site_engineer = self.user
        self.project.save()

        authenticate_client(self.client, username="inv_bse_user", password="testpass123")
        InvoicingInformation.objects.filter(project_name__iexact="Thane Project").delete()
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
            "invoice_type": "SCL",
            "gross_billed": "120000000.00",
            "gross_certified_billed": "100000000.00",
        }
        payload.update(overrides)
        return self.client.post(self.CREATE_URL, payload, format="json")

    def _create_contractor(self, name, **overrides):
        payload = {
            "project_name": "Thane Project",
            "invoice_type": "CONTRACTOR",
            "contractor_id": self._ensure_contractor(name),
            "gross_billed": "50000000.00",
            "gross_certified_billed": "45000000.00",
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
        self._create_contractor("ABC Infra", gross_billed="100.00")
        self._create_contractor("XYZ Construction", gross_billed="200.00")

        self._create_contractor("ABC Infra", gross_billed="150.00")

        response = self.client.get(self.BY_PROJECT_URL)
        contractors = response.data["data"]["contractors"]
        abc = next(c for c in contractors if c["contractor_name"] == "ABC Infra")
        xyz = next(c for c in contractors if c["contractor_name"] == "XYZ Construction")
        self.assertEqual(Decimal(abc["invoicing"]["gross_billed"]), Decimal("150.00"))
        self.assertEqual(Decimal(xyz["invoicing"]["gross_billed"]), Decimal("200.00"))

    def test_contractor_name_required_for_contractor_type(self):
        response = self.client.post(
            self.CREATE_URL,
            {
                "project_name": "Thane Project",
                "invoice_type": "CONTRACTOR",
                "gross_billed": "100.00",
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

        url = "/api/invoicing/project/Thane%20Project/type/CONTRACTOR/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get(f"{url}?contractor_id={self._ensure_contractor('XYZ Construction')}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["contractor_name"], "XYZ Construction")

    def test_get_by_type_returns_selected_contractor_values(self):
        abc_id = self._ensure_contractor("ABC Infra")
        xyz_id = self._ensure_contractor("XYZ Construction")
        self._create_contractor("ABC Infra", gross_billed="100.00")
        self._create_contractor("XYZ Construction", gross_billed="200.00")

        url = "/api/invoicing/project/Thane%20Project/type/CONTRACTOR/"

        abc_response = self.client.get(f"{url}?contractor_id={abc_id}")
        self.assertEqual(abc_response.status_code, status.HTTP_200_OK)
        self.assertEqual(abc_response.data["data"]["contractor"]["id"], abc_id)
        self.assertEqual(
            Decimal(abc_response.data["data"]["gross_billed"]),
            Decimal("100.00"),
        )

        xyz_response = self.client.get(f"{url}?contractor_id={xyz_id}")
        self.assertEqual(xyz_response.status_code, status.HTTP_200_OK)
        self.assertEqual(xyz_response.data["data"]["contractor"]["id"], xyz_id)
        self.assertEqual(
            Decimal(xyz_response.data["data"]["gross_billed"]),
            Decimal("200.00"),
        )

    def test_get_by_type_wrong_contractor_id_returns_404(self):
        self._create_contractor("ABC Infra")
        url = "/api/invoicing/project/Thane%20Project/type/CONTRACTOR/"
        response = self.client.get(f"{url}?contractor_id=99999")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ContractorSummaryInvoicingAPITest(APITestCase):
    CREATE_URL = "/api/invoicing/"
    BY_PROJECT_URL = "/api/invoicing/project/Thane%20Project/"

    def setUp(self):
        self.project = Project.objects.create(name="Thane Project", status="active")
        bse_group, _ = Group.objects.get_or_create(name="Billing Site Engineer")
        self.user = User.objects.create_user("inv_summary_user", password="testpass123")
        self.user.groups.add(bse_group)
        self.project.billing_site_engineer = self.user
        self.project.save()

        authenticate_client(self.client, username="inv_summary_user", password="testpass123")
        InvoicingInformation.objects.filter(project_name__iexact="Thane Project").delete()
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
            "invoice_type": "SCL",
            "gross_billed": "120000000.00",
            "gross_certified_billed": "100000000.00",
        }
        payload.update(overrides)
        return self.client.post(self.CREATE_URL, payload, format="json")

    def _create_contractor(self, name, **overrides):
        payload = {
            "project_name": "Thane Project",
            "invoice_type": "CONTRACTOR",
            "contractor_id": self._ensure_contractor(name),
            "gross_billed": "50000000.00",
            "gross_certified_billed": "45000000.00",
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
        self.assertEqual(Decimal(summary["gross_billed"]), Decimal("0"))
        self.assertEqual(Decimal(summary["gross_certified_billed"]), Decimal("0"))
        self.assertEqual(Decimal(summary["difference"]), Decimal("0"))
        self.assertEqual(Decimal(summary["certification_efficiency"]), Decimal("0"))

    def test_single_contractor_summary_matches_record(self):
        self._create_contractor(
            "ABC Infra",
            gross_billed="50000000.00",
            gross_certified_billed="45000000.00",
        )
        summary = self._get_summary()
        self.assertEqual(Decimal(summary["gross_billed"]), Decimal("50000000.00"))
        self.assertEqual(Decimal(summary["gross_certified_billed"]), Decimal("45000000.00"))
        self.assertEqual(Decimal(summary["difference"]), Decimal("5000000.00"))
        self.assertEqual(Decimal(summary["certification_efficiency"]), Decimal("90.00"))

    def test_multiple_contractors_cumulative_summary(self):
        self._create_contractor(
            "ABC Infra",
            gross_billed="50000000.00",
            gross_certified_billed="47500000.00",
        )
        self._create_contractor(
            "XYZ Construction",
            gross_billed="20000000.00",
            gross_certified_billed="17500000.00",
        )
        summary = self._get_summary()
        self.assertEqual(Decimal(summary["gross_billed"]), Decimal("70000000.00"))
        self.assertEqual(Decimal(summary["gross_certified_billed"]), Decimal("65000000.00"))
        self.assertEqual(Decimal(summary["difference"]), Decimal("5000000.00"))
        self.assertEqual(Decimal(summary["certification_efficiency"]), Decimal("92.86"))

    def test_zero_values_summary(self):
        self._create_contractor(
            "ABC Infra",
            gross_billed="0.00",
            gross_certified_billed="0.00",
        )
        summary = self._get_summary()
        self.assertEqual(Decimal(summary["gross_billed"]), Decimal("0"))
        self.assertEqual(Decimal(summary["difference"]), Decimal("0"))
        self.assertEqual(Decimal(summary["certification_efficiency"]), Decimal("0"))

    def test_efficiency_from_cumulative_totals_not_average(self):
        self._create_contractor(
            "ABC Infra",
            gross_billed="100.00",
            gross_certified_billed="80.00",
        )
        self._create_contractor(
            "XYZ Construction",
            gross_billed="100.00",
            gross_certified_billed="60.00",
        )
        summary = self._get_summary()
        self.assertEqual(Decimal(summary["gross_billed"]), Decimal("200.00"))
        self.assertEqual(Decimal(summary["gross_certified_billed"]), Decimal("140.00"))
        self.assertEqual(Decimal(summary["difference"]), Decimal("60.00"))
        self.assertEqual(Decimal(summary["certification_efficiency"]), Decimal("70.00"))


class InvoicingDuplicateProjectContractorTest(APITestCase):
    """Contractor id must resolve when duplicate Project rows share the same name."""

    CREATE_URL = "/api/invoicing/"

    def setUp(self):
        self.project_name = "KHB Multiplex, Kengeri (A-3462)"
        self.canonical_project = Project.objects.create(
            name=self.project_name,
            status="active",
        )
        self.duplicate_project = Project.objects.create(
            name="Khb Multiplex, Kengeri (A-3462)",
            status="active",
        )
        self.contractor = Contractor.objects.create(
            project=self.canonical_project,
            contractor_name="ABC",
            status=Contractor.Status.ACTIVE,
        )

        bse_group, _ = Group.objects.get_or_create(name="Billing Site Engineer")
        self.user = User.objects.create_user("inv_khb_bse", password="testpass123")
        self.user.groups.add(bse_group)
        self.canonical_project.billing_site_engineer = self.user
        self.canonical_project.save()
        authenticate_client(self.client, username="inv_khb_bse", password="testpass123")

    def test_contractor_id_resolves_with_duplicate_project_rows(self):
        response = self.client.post(
            self.CREATE_URL,
            {
                "project_name": self.project_name,
                "invoice_type": "Contractor",
                "contractor_id": self.contractor.id,
                "contractor_name": "ABC",
                "gross_billed": "0",
                "gross_certified_billed": "0",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(
            response.data["data"]["contractor"]["id"],
            self.contractor.id,
        )

