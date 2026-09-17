from decimal import Decimal
from unittest import TestCase

from .controllers.invoicing_metrics import contractor_summary_from_records
from .models.invoicing_information import InvoicingInformation


class ContractorSummaryMetricsTest(TestCase):
    def _record(self, gross_billed, gross_certified_billed):
        return InvoicingInformation(
            gross_billed=gross_billed,
            gross_certified_billed=gross_certified_billed,
        )

    def test_empty_records_returns_zeros(self):
        summary = contractor_summary_from_records([])
        self.assertEqual(summary["gross_billed"], Decimal("0"))
        self.assertEqual(summary["difference"], Decimal("0"))
        self.assertEqual(summary["certification_efficiency"], Decimal("0.00"))

    def test_single_record(self):
        summary = contractor_summary_from_records([self._record("100", "90")])
        self.assertEqual(summary["gross_billed"], Decimal("100"))
        self.assertEqual(summary["difference"], Decimal("10"))
        self.assertEqual(summary["certification_efficiency"], Decimal("90.00"))

    def test_multiple_records_cumulative(self):
        records = [
            self._record("50000000", "47500000"),
            self._record("20000000", "17500000"),
        ]
        summary = contractor_summary_from_records(records)
        self.assertEqual(summary["gross_billed"], Decimal("70000000"))
        self.assertEqual(summary["gross_certified_billed"], Decimal("65000000"))
        self.assertEqual(summary["difference"], Decimal("5000000"))
        self.assertEqual(summary["certification_efficiency"], Decimal("92.86"))
