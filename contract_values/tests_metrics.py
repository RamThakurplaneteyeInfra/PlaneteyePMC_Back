from decimal import Decimal
from unittest import TestCase

from .controllers.contract_value_metrics import contractor_summary_from_records
from .models.contract_value import ContractValue


class ContractorSummaryMetricsTest(TestCase):
    def _record(self, original, excess, saving):
        return ContractValue(
            original_contract_value=original,
            excess_value=excess,
            saving=saving,
        )

    def test_empty_records_returns_zeros(self):
        summary = contractor_summary_from_records([])
        self.assertEqual(summary["original_contract_value"], Decimal("0"))
        self.assertEqual(summary["revised_value"], Decimal("0"))
        self.assertEqual(summary["increase_percentage"], Decimal("0.00"))

    def test_single_record(self):
        summary = contractor_summary_from_records([self._record("100", "10", "5")])
        self.assertEqual(summary["original_contract_value"], Decimal("100"))
        self.assertEqual(summary["revised_value"], Decimal("105"))
        self.assertEqual(summary["increase_percentage"], Decimal("5.00"))

    def test_multiple_records_cumulative(self):
        records = [
            self._record("10000000", "300000", "100000"),
            self._record("5000000", "300000", "50000"),
        ]
        summary = contractor_summary_from_records(records)
        self.assertEqual(summary["original_contract_value"], Decimal("15000000"))
        self.assertEqual(summary["revised_value"], Decimal("15450000"))
        self.assertEqual(summary["increase_percentage"], Decimal("3.00"))
