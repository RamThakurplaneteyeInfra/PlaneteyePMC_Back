"""
Guardrails so DPR/project emails cannot fail silently due to broken templates.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings

from services.email_utils import _collapse_multiline_django_tags, send_html_email


_TEMPLATES_DIR = Path(settings.BASE_DIR) / "templates" / "emails"
_MULTILINE_TAG_RE = re.compile(r"(\{\{.*?\}\}|\{%.*?%\})", re.DOTALL)


class EmailTemplateSourceGuardTests(SimpleTestCase):
    def test_email_templates_have_no_multiline_django_tags(self):
        offenders = []
        for path in sorted(_TEMPLATES_DIR.glob("*.html")):
            raw = path.read_text(encoding="utf-8")
            for match in _MULTILINE_TAG_RE.finditer(raw):
                if "\n" in match.group(0):
                    offenders.append(f"{path.name}: {match.group(0)[:80]!r}")
        self.assertEqual(
            offenders,
            [],
            "Email Django tags must stay on one line (formatter-safe):\n"
            + "\n".join(offenders),
        )

    def test_collapse_multiline_django_tags_repairs_broken_source(self):
        broken = (
            '{% firstof\n            a.b c.d "x" %}'
            '{{ job|default:"Not\n            specified" }}'
        )
        fixed = _collapse_multiline_django_tags(broken)
        self.assertNotIn("\n", fixed)
        self.assertIn('{% firstof a.b c.d "x" %}', fixed)
        self.assertIn('{{ job|default:"Not specified" }}', fixed)


@override_settings(
    EMAIL_TRANSPORT="smtp",
    BREVO_API_KEY="",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class EmailDeliveryRepairTests(TestCase):
    def test_send_html_email_renders_clean_html(self):
        ok = send_html_email(
            subject="Audit",
            template_name="dpr_submitted",
            context={
                "approver": {"username": "tl", "get_full_name": "TL"},
                "dpr": {
                    "project_name": "P",
                    "report_date": "2026-08-21",
                    "job_no": "J",
                    "issued_by": "SE",
                    "submitted_by": {"username": "se", "get_full_name": "SE"},
                },
            },
            recipient_list=["tl@example.com"],
        )
        self.assertTrue(ok)
        self.assertEqual(len(mail.outbox), 1)
        html = mail.outbox[0].alternatives[0][0]
        self.assertNotIn("{{", html)
        self.assertNotIn("{%", html)
