"""Presentation invariants, not question-bank or financial selection tests."""
import copy
from decimal import Decimal
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = Path(os.environ.get('FEE_CANDIDATE', ROOT / 'candidate'))
sys.path.insert(0, str(CANDIDATE))
import solution
from percent_display import format_conflicts, format_percent_text


class PercentPresentation(unittest.TestCase):
    def test_plain_tokens_pad_without_rounding_or_space_changes(self):
        text = 'Values: 6%, 6.7 %, .8%, 9.%, +2.1%, -7.4%.'
        self.assertEqual(format_percent_text(text),
                         'Values: 6.00%, 6.70 %, .80%, 9.00%, +2.10%, -7.40%.')

    def test_additional_precision_and_tiny_values_remain_exact(self):
        text = '3.802% / 3.800% / 0.0000000000000123456789012345678901% / -0.00000000000009%'
        self.assertEqual(format_percent_text(text), text)
        long = '12345678901234567890123456789012345678901234567890.1%'
        self.assertEqual(format_percent_text(long), long[:-1] + '0%')
        self.assertEqual(Decimal(long[:-1]), Decimal(format_percent_text(long)[:-1]))

    def test_scientific_and_unrecognized_tokens_stay_unchanged(self):
        text = '1e-9% / -2.1E+4% / 1,234.5% / 1.2.3% / 0x3.5% / −4.1% / 2e--4% / $3.1% / 7.1%APR'
        self.assertEqual(format_percent_text(text), text)

    def test_idempotent_and_decimal_equal_across_signed_examples(self):
        values = ['0', '-0', '+0.0', '1', '-8.2', '+2.50', '.1', '-.2',
                  '3.802', '0.0000000000001', '999999999999999999999999999.1']
        for value in values:
            formatted = format_percent_text(value + '%')
            self.assertEqual(Decimal(value), Decimal(formatted[:-1]))
            self.assertEqual(format_percent_text(formatted), formatted)

    def test_only_values_and_resolution_change_on_copied_containers(self):
        source = solution._parent.Source('https://example.test/proof', 'source-only', 'Raw source: 6.7%')
        original = solution._parent.Conflict('Topic 6.7%', ['6.7% / 7.2%', '$48.35'],
                                             [source], 'Selected 7.2%', 'Reason retains 6.7%')
        control = copy.deepcopy(original)
        formatted = format_conflicts([original])
        self.assertEqual(original, control)
        self.assertEqual(formatted[0].values, ['6.70% / 7.20%', '$48.35'])
        self.assertEqual(formatted[0].resolution, 'Selected 7.20%')
        self.assertEqual(formatted[0].topic, original.topic)
        self.assertEqual(formatted[0].sources, original.sources)
        self.assertEqual(formatted[0].reason, original.reason)
        formatted[0].sources[0].quote = 'mutated'
        formatted[0].values.clear()
        self.assertEqual(original, control)

    def test_conflict_order_and_missing_or_nonstring_fields_preserved(self):
        records = [NS(topic='second', values=[None, 12, '5%'], resolution=None, reason='stable'),
                   NS(topic='first', values=('3.5%',), resolution=42, reason=None)]
        result = format_conflicts(records)
        self.assertEqual([r.topic for r in result], ['second', 'first'])
        self.assertEqual(result[0].values, [None, 12, '5.00%'])
        self.assertIsNone(result[0].resolution)
        self.assertEqual(result[1].values, ('3.5%',))
        self.assertEqual(result[1].resolution, 42)

    def test_coordinator_switch_restores_iteration3_and_cache_is_not_mutated(self):
        original = solution._parent.Conflict('Stable', ['6.7%'], [], '6.7%', 'reason')
        enabled = solution.build()
        enabled._spine = NS(conflicts=lambda: [original])
        first = enabled.conflicts()
        self.assertEqual(first[0].values, ['6.70%'])
        first[0].values[0] = 'invented'
        self.assertEqual(enabled.conflicts()[0].values, ['6.70%'])
        self.assertEqual(original.values, ['6.7%'])
        disabled = solution.build(enable_percent_display=False)
        disabled._spine = NS(conflicts=lambda: [original])
        self.assertEqual(disabled.conflicts(), [original])


if __name__ == '__main__':
    unittest.main()
