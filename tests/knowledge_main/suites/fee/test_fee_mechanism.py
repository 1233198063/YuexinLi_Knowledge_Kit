"""Arbitrary-source fee controls authored before implementation.

Values, domains, snapshots and fee labels are independent of official answers.
"""
import dataclasses
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = Path(os.environ.get('FEE_CANDIDATE', ROOT / 'candidate'))
sys.path.insert(0, str(CANDIDATE))
import solution

LABEL = 'Badge reprint'
Q = 'What is the published base fee for a badge reprint?'
CARD_Q = 'What is the published fee for lost debit card replacement?'


def page(md=None, title='Service Fees', url='https://maple.example/resources/service-prices', fetched='2031-02-11T08:00:00Z'):
    return NS(url=url, title=title, markdown=md or '# Service Fees\n\nBadge reprint fee: $37.45\n', fetched_at=fetched)


def snap(pages, sid='maple-source-a', date='2031-02-11'):
    return NS(snapshot_id=sid, taken_on=date, pages=pages)


def state(a):
    return dataclasses.asdict(a)


def systems(snapshots):
    parent, combined = solution.build_parent(), solution.build()
    for s in snapshots:
        parent.ingest(s)
        combined.ingest(s)
    return parent, combined


class FeeCompatibility(unittest.TestCase):
    def setUp(self):
        self.old = snap([page()])
        self.new = snap([], 'maple-source-b', '2031-03-06')

    def assert_parent(self, snapshots, question=Q, as_of=None):
        parent, combined = systems(snapshots)
        self.assertEqual(state(combined.answer(question, as_of)), state(parent.answer(question, as_of)))

    def test_missing_entire_fee_document_recovers_qualified_base_fee(self):
        parent, combined = systems([self.old, self.new])
        self.assertFalse(parent.answer(Q).confident)
        a = combined.answer(Q)
        self.assertTrue(a.confident)
        self.assertIn('$37.45', a.text)
        self.assertIn('most recently available published base fee', a.text)
        self.assertIn('was', a.text)
        self.assertIn('2031-02-11', a.text)
        self.assertNotIn('current fee is', a.text.lower())
        self.assertEqual(a.sources[0].snapshot_id, self.old.snapshot_id)
        self.assertEqual(a.sources[0].url, self.old.pages[0].url)

    def test_debit_replacement_donor_fee_lane_is_source_derived(self):
        old = snap([page('# Fees\n\nLost debit card replacement fee: $43.70\n')])
        parent, combined = systems([old, self.new])
        a = combined.answer(CARD_Q)
        self.assertFalse(parent.answer(CARD_Q).confident)
        self.assertTrue(a.confident)
        self.assertIn('$43.70', a.text)
        self.assertEqual(a.sources[0].snapshot_id, old.snapshot_id)

    def test_row_removed_new_schedule_is_tombstone(self):
        changed = snap([page('# Service Fees\n\nPaper folding fee: $62.80\n', fetched='2031-03-06T08:00:00Z')], self.new.snapshot_id, self.new.taken_on)
        self.assert_parent([self.old, changed])

    def test_current_updated_fee_is_parent_exact(self):
        changed = snap([page('# Service Fees\n\nBadge reprint fee: $62.80\n', fetched='2031-03-06T08:00:00Z')], self.new.snapshot_id, self.new.taken_on)
        self.assert_parent([self.old, changed])

    def test_renamed_or_empty_new_schedule_blocks_old_row(self):
        for p in [page('# Service Fees\n', url='https://maple.example/new/price-list', fetched='2031-03-06T08:00:00Z'),
                  page('# Customer Service\n\nNew service fee terms apply.\n', title='Customer Service', fetched='2031-03-06T08:00:00Z')]:
            self.assert_parent([self.old, snap([p], self.new.snapshot_id, self.new.taken_on)])

    def test_latest_known_evidence_is_used_and_removed_rows_not_resurrected(self):
        middle = snap([page('# Service Fees\n\nBadge reprint fee: $62.80\n', fetched='2031-02-20T08:00:00Z')], 'maple-middle', '2031-02-20')
        parent, combined = systems([self.old, middle, self.new])
        self.assertIn('$62.80', combined.answer(Q).text)
        self.assertNotIn('$37.45', combined.answer(Q).text)
        removed = snap([page('# Service Fees\n\nPaper folding fee: $62.80\n', fetched='2031-02-20T08:00:00Z')], middle.snapshot_id, middle.taken_on)
        self.assert_parent([self.old, removed, self.new])

    def test_one_omission_and_donor_age_bound(self):
        self.assert_parent([self.old, self.new, snap([], 'maple-source-c', '2031-03-18')])
        self.assert_parent([self.old, snap([], 'maple-late', '2031-08-18')])

    def test_before_first_asof_and_no_future_snapshot(self):
        self.assert_parent([self.old, self.new], as_of='2030-09-01')
        self.assert_parent([self.old, self.new], as_of='2031-02-18')
        parent, combined = systems([self.old, self.new])
        self.assertIn('$37.45', combined.answer(Q, '2031-03-08').text)
        future = snap([page('# Service Fees\n\nBadge reprint fee: $91.60\n', fetched='2031-04-09T08:00:00Z')], 'maple-future', '2031-04-09')
        parent, combined = systems([future, self.new, self.old])
        a = combined.answer(Q, '2031-03-08')
        self.assertIn('$37.45', a.text)
        self.assertNotIn('$91.60', a.text)

    def test_old_snapshot_quote_is_actual_raw_substring(self):
        p = page('# Service Fees\n\n**Badge reprint fee:** $37.45\n')
        old = snap([p])
        _, combined = systems([old, self.new])
        a = combined.answer(Q)
        self.assertTrue(a.confident)
        self.assertEqual(a.sources[0].snapshot_id, old.snapshot_id)
        self.assertIn(a.sources[0].quote, p.markdown)
        self.assertIn('**', a.sources[0].quote)

    def test_future_capture_effective_and_expiry_never_fallback(self):
        texts = [
            '# Service Fees\n\nBadge reprint fee: $37.45\n\nEffective 2031-07-19.\n',
            '# Service Fees\n\nBadge reprint fee: $37.45\n\nEffective July 19, 2031.\n',
            '# Service Fees\n\nBadge reprint fee: $37.45\n\nEffective 07/19/2031.\n',
            '# Service Fees\n\nBadge reprint fee: $37.45\n\nExpires 2031-02-18.\n',
            '# Service Fees\n\nBadge reprint fee: $37.45\n\nValid from 2031-07-19.\n',
            '# Service Fees\n\nBadge reprint fee: $37.45\n\nEffective next summer.\n',
        ]
        for text in texts:
            with self.subTest(text=text):
                self.assert_parent([snap([page(text)]), self.new])
        self.assert_parent([snap([page(fetched='2031-07-19T08:00:00Z')]), self.new])

    def test_expiry_is_evaluated_at_requested_asof(self):
        old = snap([page('# Service Fees\n\nBadge reprint fee: $37.45\n\nExpires 2031-03-07.\n')])
        _, combined = systems([old, self.new])
        self.assertIn('$37.45', combined.answer(Q, '2031-03-06').text)
        self.assert_parent([old, self.new], as_of='2031-03-09')

    def test_competing_fee_documents_rows_and_capture_ties_preserve_parent(self):
        different = page('# Service Fees\n\nBadge reprint fee: $91.60\n', url='https://maple.example/resources/other-prices')
        for pages in ([page(), different], [different, page()],
                      [page('# Service Fees\n\nBadge reprint fee: $37.45\nBadge reprint fee: $91.60\n')]):
            self.assert_parent([snap(pages), self.new])
        other = snap([different], 'maple-source-peer', self.old.taken_on)
        self.assert_parent([self.old, other, self.new])

    def test_private_actual_charge_institution_and_unknown_conditions_stay_parent(self):
        questions = ['How much was I charged for a badge reprint?',
                     'What is my badge reprint fee?',
                     'What will my account be charged for a badge reprint?',
                     'What is the actual fee for a badge reprint?',
                     'What is the badge reprint fee at Pine Credit Union?',
                     'What is the fee for a badge reprint if I am not a member?',
                     'What is the business badge reprint fee?',
                     'What is the fee for a badge reprint without a label?',
                     'What is the fee for a badge reprint after the waiver?',
                     'What is the fee for a badge reprint that is not lost?']
        for q in questions:
            with self.subTest(q=q):
                self.assert_parent([self.old, self.new], q)

    def test_latest_snapshot_and_page_only_scope_stays_parent(self):
        for q in [Q.rstrip('?') + ' according to the latest snapshot?',
                  Q.rstrip('?') + ' using only the latest fee page?',
                  Q.rstrip('?') + ' in the current crawl?',
                  Q.rstrip('?') + ' from https://maple.example/resources/service-prices?']:
            self.assert_parent([self.old, self.new], q)

    def test_mixed_multipart_and_history_never_use_cached_fallback(self):
        parent, combined = systems([self.old, self.new])
        self.assertTrue(combined.answer(Q).confident)
        for q in [Q + ' And what is the savings APY?',
                  'What is the badge reprint fee and the lost debit card replacement fee?',
                  'What is the badge reprint fee; separately what is the certificate rate?',
                  'How has the badge reprint fee changed?',
                  'What was the badge reprint fee previously?']:
            self.assertEqual(state(combined.answer(q)), state(parent.answer(q)))

    def test_unknown_fee_amount_conditions_and_partial_name_reject(self):
        for text in ['# Service Fees\n\nBadge reprint fee: $37.45 for members only.\n',
                     '# Service Fees\n\nBadge reprint fee: $37.45\n\nFees waived for qualifying customers.\n',
                     '# Service Fees\n\nPremium badge reprint fee: $37.45\n',
                     '# Service Fees\n\nBadge reprint fee: up to $37.45\n',
                     '# Service Fees\n\nBadge reprint fee: free\n']:
            self.assert_parent([snap([page(text)]), self.new])

    def test_generic_fee_table_uses_actual_source_url(self):
        p = page('# Service Fees\n\n| Service | Fee |\n| --- | --- |\n| Badge reprint | $37.45 |\n')
        _, combined = systems([snap([p]), self.new])
        a = combined.answer(Q)
        self.assertTrue(a.confident)
        self.assertEqual(a.sources[0].url, p.url)
        self.assertIn(a.sources[0].quote, p.markdown)

    def test_cache_reingest_and_mutation_leave_conflicts_parent_owned(self):
        parent, combined = systems([self.old, self.new])
        conflicts = [state(c) for c in parent.conflicts()]
        before = state(combined.answer(Q))
        a = combined.answer(Q)
        a.sources[0].quote = 'invented'
        a.sources.clear()
        self.assertEqual(state(combined.answer(Q)), before)
        self.assertEqual([state(c) for c in combined.conflicts()], conflicts)
        parent.ingest(snap([], self.old.snapshot_id, self.old.taken_on))
        combined.ingest(snap([], self.old.snapshot_id, self.old.taken_on))
        self.assertEqual(state(combined.answer(Q)), state(parent.answer(Q)))
        self.assertEqual([state(c) for c in combined.conflicts()], [state(c) for c in parent.conflicts()])

    def test_disable_switch_and_dependency_import(self):
        parent, _ = systems([self.old, self.new])
        disabled = solution.build(enable_fee_fallback=False)
        disabled.ingest(self.old)
        disabled.ingest(self.new)
        self.assertEqual(state(disabled.answer(Q)), state(parent.answer(Q)))
        result = subprocess.run([sys.executable, '-I', '-B', '-c',
                                 'import sys; sys.path.insert(0, ' + repr(str(CANDIDATE)) + '); import solution; print(type(solution.build()).__name__)'],
                                capture_output=True, text=True, check=True)
        self.assertIn('FeeCompatibilityKnowledge', result.stdout)


if __name__ == '__main__':
    unittest.main()
