"""Tests for PMC Head / Head Office DPR executive digest."""

from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings

from dpr.models import DailyProgressReport
from dpr.services.digest import build_executive_digest, resolve_digest_recipients
from dpr.services.executive_digest import send_dpr_executive_digest
from projects.models import Project
from services.notifications import notify_dpr_executive_digest


@override_settings(
    DPR_EMAIL_INLINE=True,
    DPR_DIGEST_ENABLED=True,
    DPR_EMAIL_ENABLED=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_TRANSPORT="smtp",
    BREVO_API_KEY="",
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "dpr-executive-digest-tests",
        }
    },
)
class DprExecutiveDigestTests(TestCase):
    def setUp(self):
        cache.clear()
        self.pmc_group, _ = Group.objects.get_or_create(name="PMC Head")
        self.ho_group, _ = Group.objects.get_or_create(name="Head Office")

        self.pmc_head = User.objects.create_user(
            username="digest_pmc",
            email="pmc.head@example.com",
            password="x",
            first_name="Priya",
            last_name="Head",
        )
        self.pmc_head.groups.add(self.pmc_group)

        self.ho = User.objects.create_user(
            username="digest_ho",
            email="ho@example.com",
            password="x",
            first_name="HO",
            last_name="User",
        )
        self.ho.groups.add(self.ho_group)

        self.tl = User.objects.create_user(
            username="digest_tl",
            email="tl@example.com",
            password="x",
            first_name="Team",
            last_name="Lead",
        )
        self.se = User.objects.create_user(
            username="digest_se",
            email="se@example.com",
            password="x",
            first_name="Site",
            last_name="Eng",
        )

        self.report_date = date(2026, 8, 20)

        self.filled_project = Project.objects.create(
            name="Digest Filled Project",
            status="active",
            team_lead=self.tl,
            site_engineer=self.se,
        )
        self.missing_project = Project.objects.create(
            name="Digest Missing Project",
            status="active",
            team_lead=self.tl,
            site_engineer=self.se,
        )
        Project.objects.create(
            name="Digest Completed Project",
            status="completed",
            team_lead=self.tl,
        )

        DailyProgressReport.objects.create(
            project_name=self.filled_project.name,
            job_no="J-1",
            report_date=self.report_date,
            issued_by="SE",
            designation="Site Engineer",
            status=DailyProgressReport.Status.PENDING_PMC_HEAD,
            current_approver_role="PMC Head",
            submitted_by=self.se,
        )

    def test_resolve_recipients_pmc_head_and_ho(self):
        recipients = resolve_digest_recipients()
        emails = {u.email for u in recipients}
        self.assertEqual(emails, {"pmc.head@example.com", "ho@example.com"})

    def test_build_digest_counts_pending_and_missing(self):
        digest = build_executive_digest(report_date=self.report_date)
        self.assertEqual(digest.counts.projects_active, 2)
        self.assertEqual(digest.counts.total_filled, 1)
        self.assertEqual(digest.counts.pending_pmc_head, 1)
        self.assertEqual(digest.counts.pending_total, 1)
        self.assertEqual(digest.counts.projects_missing, 1)
        self.assertEqual(len(digest.missing_projects), 1)
        self.assertEqual(digest.missing_projects[0].project_name, "Digest Missing Project")
        self.assertEqual(digest.missing_projects[0].team_lead, "Team Lead")
        self.assertEqual(len(digest.pending_items), 1)

    def test_draft_only_does_not_count_as_filled(self):
        DailyProgressReport.objects.create(
            project_name=self.missing_project.name,
            job_no="J-2",
            report_date=self.report_date,
            issued_by="SE",
            designation="Site Engineer",
            status=DailyProgressReport.Status.DRAFT,
            submitted_by=self.se,
        )
        digest = build_executive_digest(report_date=self.report_date)
        self.assertEqual(digest.counts.projects_missing, 1)
        self.assertEqual(digest.counts.draft_only, 1)
        self.assertEqual(digest.counts.total_filled, 1)

    def test_notify_sends_digest_email(self):
        summary = send_dpr_executive_digest(
            report_date=self.report_date,
            force=True,
            source="test",
        )
        self.assertEqual(summary["status"], "sent")
        self.assertEqual(summary["missing"], 1)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn("DPR Executive Digest", message.subject)
        self.assertIn("Digest Missing Project", message.body)
        self.assertCountEqual(
            message.to,
            ["pmc.head@example.com", "ho@example.com"],
        )

    def test_dry_run_does_not_send(self):
        summary = notify_dpr_executive_digest(
            report_date=self.report_date,
            dry_run=True,
        )
        self.assertEqual(summary["status"], "dry_run")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(DPR_DIGEST_ENABLED=False)
    def test_disabled_setting(self):
        summary = send_dpr_executive_digest(report_date=self.report_date, force=True)
        self.assertEqual(summary["status"], "disabled")
        self.assertEqual(len(mail.outbox), 0)

    def test_management_command_dry_run(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command(
            "send_dpr_executive_digest",
            "--date",
            self.report_date.isoformat(),
            "--dry-run",
            stdout=out,
        )
        self.assertIn("dry_run", out.getvalue())
        self.assertEqual(len(mail.outbox), 0)


@override_settings(
    DPR_EMAIL_INLINE=True,
    DPR_DIGEST_ENABLED=True,
    DPR_EMAIL_ENABLED=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_TRANSPORT="smtp",
    BREVO_API_KEY="",
)
class PmcHeadDigestOnlyEmailTests(TestCase):
    """PMC Head / HO must not receive per-event DPR emails — digest only."""

    def setUp(self):
        self.pmc_group, _ = Group.objects.get_or_create(name="PMC Head")
        self.pmc_head = User.objects.create_user(
            username="head_only",
            email="pmc.head.only@example.com",
            password="x",
        )
        self.pmc_head.groups.add(self.pmc_group)
        self.tl = User.objects.create_user(
            username="tl_ok",
            email="tl.ok@example.com",
            password="x",
        )
        self.se = User.objects.create_user(
            username="se_ok",
            email="se.ok@example.com",
            password="x",
        )
        self.project = Project.objects.create(
            name="Head Digest Only Project",
            status="active",
            team_lead=self.tl,
            pmc_head=self.pmc_head,
            site_engineer=self.se,
        )
        self.dpr = DailyProgressReport.objects.create(
            project_name=self.project.name,
            job_no="J-H",
            report_date=date(2026, 8, 20),
            issued_by="SE",
            designation="Site Engineer",
            status=DailyProgressReport.Status.PENDING_PMC_HEAD,
            current_approver_role="PMC Head",
            submitted_by=self.se,
        )

    @patch("services.email_utils.send_html_email", return_value=True)
    @patch("services.notifications.send_websocket_notification")
    def test_pending_pmc_head_skips_event_email(self, mock_ws, mock_email):
        from services.notifications import notify_dpr_submitted

        with self.captureOnCommitCallbacks(execute=True):
            notify_dpr_submitted(self.dpr)

        self.assertTrue(mock_ws.called)
        mock_email.assert_not_called()

    @patch("services.email_utils.send_html_email", return_value=True)
    @patch("services.notifications.send_websocket_notification")
    def test_team_leader_still_gets_submission_email(self, mock_ws, mock_email):
        from services.notifications import notify_dpr_submitted

        self.dpr.status = DailyProgressReport.Status.PENDING_TEAM_LEAD
        self.dpr.current_approver_role = "Team Leader"
        self.dpr.save(update_fields=["status", "current_approver_role"])

        with self.captureOnCommitCallbacks(execute=True):
            notify_dpr_submitted(self.dpr)

        mock_email.assert_called_once()
        recipients = mock_email.call_args.kwargs.get("recipient_list") or []
        self.assertIn("tl.ok@example.com", recipients)
        self.assertNotIn("pmc.head.only@example.com", recipients)

    @patch("services.email_utils.send_html_email", return_value=True)
    @patch("services.notifications.send_websocket_notification")
    def test_head_office_excluded_from_event_email(self, mock_ws, mock_email):
        from services.notifications import notify_dpr_submitted

        ho_group, _ = Group.objects.get_or_create(name="Head Office")
        ho = User.objects.create_user(
            username="ho_only",
            email="ho.only@example.com",
            password="x",
        )
        ho.groups.add(ho_group)
        self.project.coordinators.add(ho)

        self.dpr.status = DailyProgressReport.Status.PENDING_COORDINATOR
        self.dpr.current_approver_role = "PMC Manager"
        self.dpr.save(update_fields=["status", "current_approver_role"])

        manager = User.objects.create_user(
            username="mgr_ok",
            email="mgr.ok@example.com",
            password="x",
        )
        self.project.coordinators.add(manager)

        with self.captureOnCommitCallbacks(execute=True):
            notify_dpr_submitted(self.dpr)

        mock_email.assert_called_once()
        recipients = mock_email.call_args.kwargs.get("recipient_list") or []
        self.assertIn("mgr.ok@example.com", recipients)
        self.assertNotIn("ho.only@example.com", recipients)
