"""Tests for project-logs bottleneck dashboard sync."""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from bottlenecks.models import Bottleneck
from core.test_auth import authenticate_client
from projects.bottleneck_sync import sync_bottlenecks_from_dashboard
from projects.models import Project, ProjectLog, ProjectLogEntry

User = get_user_model()


class BottleneckSyncTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sync_user", password="pass12345")
        self.project = Project.objects.create(name="Sync Project")

    def test_sync_normalizes_frontend_enums(self):
        payload = json.dumps(
            [
                {
                    "id": "4fbafe83-e955-4d1c-ba35-c74a7ec6389d",
                    "type": "ISSUE",
                    "description": "assds",
                    "priority": "Medium",
                    "status": "Open",
                    "assignedTo": "",
                }
            ]
        )
        sync_bottlenecks_from_dashboard(self.project.id, payload, user=self.user)
        bn = Bottleneck.objects.get(project=self.project)
        self.assertEqual(bn.type, "ISSUE")
        self.assertEqual(bn.priority, "MEDIUM")
        self.assertEqual(bn.status, "OPEN")
        self.assertEqual(bn.client_id, "4fbafe83-e955-4d1c-ba35-c74a7ec6389d")


class ProjectLogBottleneckAPITest(APITestCase):
    def setUp(self):
        self.user = authenticate_client(self.client)
        self.project = Project.objects.create(name="Log API Project")
        self.log = ProjectLog.objects.create(project=self.project, created_by=self.user)

    def test_put_project_logs_saves_bottleneck_dashboard(self):
        left_text = json.dumps(
            [
                {
                    "id": "uuid-123",
                    "type": "RISK",
                    "description": "Rain delay",
                    "priority": "High",
                    "status": "Open",
                    "assignedTo": "",
                }
            ]
        )
        response = self.client.put(
            f"/api/project-logs/{self.project.id}/",
            {
                "entries": [
                    {
                        "entry_type": "bottleneck_dashboard",
                        "left_text": left_text,
                        "right_text": "",
                        "row_order": 1,
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Bottleneck.objects.filter(project=self.project).count(), 1)
        entry = ProjectLogEntry.objects.get(project_log=self.log)
        self.assertEqual(entry.entry_type, "bottleneck_dashboard")
        saved = json.loads(entry.left_text)
        self.assertEqual(saved[0]["description"], "Rain delay")
