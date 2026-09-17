"""Send redesigned DPR approval sample. Delete after use."""
from __future__ import annotations

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.template.loader import render_to_string
from django.utils import timezone

from dpr.models import DailyProgressReport
from dpr.tasks import send_dpr_pmc_head_approval_email, send_dpr_rejection_email, send_dpr_submission_email
from projects.models import Project

RECIPIENTS = [
    "ram.thakur@planeteyeinfra.ai",
    "manali.songire@planeteyefarm.ai",
    "vaishnavi.nirgude@planeteyeinfra.ai",
]


def main() -> None:
    print("logo_url", settings.EMAIL_LOGO_URL)
    html = render_to_string(
        "emails/dpr_approved.html",
        {
            "email_logo_url": settings.EMAIL_LOGO_URL,
            "email_logo_cid": settings.EMAIL_LOGO_URL,
            "submitter": {"username": "ram", "get_full_name": "Ram Thakur"},
            "approved_by_role": "PMC Head",
            "dpr": {
                "project_name": "demo testing Project",
                "report_date": "2026-08-20",
                "job_no": "212",
                "approved_by": {"username": "v", "get_full_name": "Vaishnavi Nirgude"},
            },
        },
    )
    assert "{{" not in html and "{%" not in html
    assert "pmcproject.s3.ap-south-1.amazonaws.com/email/scl_logo.png" in html
    print("template_ok logo_in_html=True")

    users = [User.objects.get(email__iexact=e) for e in RECIPIENTS]
    ram, manali, vaishnavi = users
    project = Project.objects.get(pk=104)
    dpr = DailyProgressReport.objects.filter(project_name=project.name).order_by("-id").first()
    dpr.submitted_by = ram
    dpr.approved_by = vaishnavi
    dpr.approved_at = timezone.now()
    dpr.rejected_by = vaishnavi
    dpr.rejection_reason = "Template redesign verification — please ignore."
    dpr.save()
    cache.clear()
    ids = [u.id for u in users]

    for label, result in [
        ("submission", send_dpr_submission_email(dpr_id=dpr.id, submitted_by_id=ram.id, recipient_ids=ids)),
        ("approval", send_dpr_pmc_head_approval_email(dpr_id=dpr.id, recipient_ids=ids)),
        ("rejection", send_dpr_rejection_email(dpr_id=dpr.id, recipient_ids=ids, role="PMC Head")),
    ]:
        print(label, result.get("status"), result.get("error"), "ms=", result.get("smtp_time_ms"))
        if result.get("status") != "sent":
            raise SystemExit("send failed")
    print("ALL SENT")


if __name__ == "__main__":
    main()
