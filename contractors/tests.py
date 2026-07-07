"""Tests for Contractor Master module."""

from django.contrib.auth.models import Group, User
from rest_framework import status
from rest_framework.test import APITestCase

from core.test_auth import authenticate_client
from projects.models import Project

from .models import Contractor


class ContractorMasterAPITest(APITestCase):
    LIST_URL = "/api/projects/{project}/contractors/"
    DETAIL_URL = "/api/projects/contractors/{pk}/"

    def setUp(self):
        self.project = Project.objects.create(name="Thane Project", status="active")
        tl_group, _ = Group.objects.get_or_create(name="Team Leader")
        self.user = User.objects.create_user("contractor_tl", password="testpass123")
        self.user.groups.add(tl_group)
        self.project.team_lead = self.user
        self.project.save()
        authenticate_client(self.client, username="contractor_tl", password="testpass123")
        Contractor.objects.filter(project=self.project).delete()

    def test_create_and_list_contractors(self):
        create = self.client.post(
            self.LIST_URL.format(project="Thane%20Project"),
            {
                "contractor_name": "ABC Infra",
                "contractor_code": "ABC001",
                "contact_person": "John Smith",
                "phone": "9876543210",
            },
            format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create.data["data"]["contractor_name"], "ABC Infra")
        self.assertEqual(create.data["data"]["status"], "ACTIVE")

        listing = self.client.get(self.LIST_URL.format(project="Thane%20Project"))
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(len(listing.data["data"]), 1)
        self.assertEqual(listing.data["data"][0]["contractor_name"], "ABC Infra")

    def test_duplicate_contractor_name_rejected(self):
        self.client.post(
            self.LIST_URL.format(project="Thane%20Project"),
            {"contractor_name": "ABC Infra"},
            format="json",
        )
        response = self.client.post(
            self.LIST_URL.format(project="Thane%20Project"),
            {"contractor_name": "ABC Infra"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("contractor_name", response.data["errors"])

    def test_patch_contractor(self):
        create = self.client.post(
            self.LIST_URL.format(project="Thane%20Project"),
            {"contractor_name": "XYZ Construction"},
            format="json",
        )
        pk = create.data["data"]["id"]
        response = self.client.patch(
            self.DETAIL_URL.format(pk=pk),
            {"contact_person": "Rahul Sharma", "phone": "9999999999"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["contact_person"], "Rahul Sharma")

    def test_team_leader_via_assigned_users_can_create_contractor(self):
        """Team Leaders assigned via assigned_users (not team_lead FK) can add contractors."""
        self.project.team_lead = None
        self.project.save()
        self.project.assigned_users.add(self.user)

        response = self.client.post(
            self.LIST_URL.format(project="Thane%20Project"),
            {"contractor_name": "Assigned TL Contractor"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data["data"]["contractor_name"],
            "Assigned TL Contractor",
        )

    def test_delete_marks_inactive(self):
        create = self.client.post(
            self.LIST_URL.format(project="Thane%20Project"),
            {"contractor_name": "PQR Builders"},
            format="json",
        )
        pk = create.data["data"]["id"]
        response = self.client.delete(self.DETAIL_URL.format(pk=pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        contractor = Contractor.objects.get(pk=pk)
        self.assertEqual(contractor.status, Contractor.Status.INACTIVE)

        listing = self.client.get(self.LIST_URL.format(project="Thane%20Project"))
        self.assertEqual(len(listing.data["data"]), 0)

        listing_all = self.client.get(
            f"{self.LIST_URL.format(project='Thane%20Project')}?include_inactive=true"
        )
        self.assertEqual(len(listing_all.data["data"]), 1)
