"""Arbitrary-source program status controls written before the repair."""
import dataclasses
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get('PROGRAM_CANDIDATE', ROOT / 'candidate'))
sys.path.insert(0, str(RUNTIME))
import solution
import facts
from common import Context

OPEN_Q = 'Are nonprofit grant applications currently open?'
DATES_Q = 'What are the nonprofit grant application dates?'


def page(body, family='non-profit-grant'):
    return NS(url='https://linden.example/programs/' + family, title='Community program',
              markdown='# Community program\n\n' + body, fetched_at='2034-04-09T08:00:00Z')


def snapshot(body, day='2034-04-09', sid='linden-source', extra=()):
    return NS(snapshot_id=sid, taken_on=day, pages=[page(body), *extra])


def answer(body, q=OPEN_Q, day='2034-04-09'):
    k = solution.build()
    k.ingest(snapshot(body, day))
    return k.answer(q)


class ProgramStatus(unittest.TestCase):
    def assert_unknown(self, a):
        self.assertFalse(a.confident)
        self.assertIn("don't know", a.text.lower())
        self.assertNotEqual(a.text.strip(), 'Nonprofit Grant application period.')

    def assert_state(self, a, state):
        self.assertTrue(a.confident, a.text)
        self.assertIn(state, a.text.lower())
        if state == 'open':
            self.assertRegex(a.text.lower(), r'\b(?:window|applications) (?:is|are) open\b')
            self.assertNotIn('not yet open', a.text.lower())

    def test_unknown_window_is_uncertain_not_a_title(self):
        self.assert_unknown(answer('Application details will be announced.'))

    def test_next_year_alone_does_not_establish_status_or_dates(self):
        body = 'The next grant cycle begins in 2036.'
        self.assert_unknown(answer(body))
        self.assert_unknown(answer(body, 'When does the next nonprofit grant application window begin?'))
        a = answer(body, 'What year does the next nonprofit grant cycle begin?')
        self.assertTrue(a.confident)
        self.assertIn('2036', a.text)
        self.assertNotRegex(a.text.lower(), r'\bapplications are (?:open|closed)\b|january')

    def test_future_year_banner_is_not_literal_open_now(self):
        self.assert_unknown(answer('Applications open in 2036.'))

    def test_open_from_through_parses_both_dates_despite_next_cycle(self):
        body = 'Applications are open from March 8, 2034 through May 17, 2034. The next grant cycle begins in 2036.'
        record, _ = facts._program(Context(snapshot(body)), page(body))
        self.assertEqual(record['start'], '2034-03-08')
        self.assertEqual(record['end'], '2034-05-17')
        self.assert_state(answer(body), 'open')

    def test_starts_and_ends_are_both_retained(self):
        body = 'Application period starts March 8, 2034 and ends May 17, 2034.'
        a = answer(body, DATES_Q)
        self.assertTrue(a.confident)
        self.assertIn('March 8, 2034', a.text)
        self.assertIn('May 17, 2034', a.text)
        self.assertNotRegex(a.text.lower(), r'\b(?:window|applications) (?:is|are) open\b')

    def test_begin_end_with_literal_banner_keeps_date_status_separate(self):
        body = 'Application period begins March 8, 2034 and ends May 17, 2034. Applications are open now.'
        self.assert_state(answer(body), 'open')
        a = answer(body, DATES_Q)
        self.assertTrue(a.confident)
        self.assertIn('May 17, 2034', a.text)
        self.assertNotIn('open now', a.text.lower())

    def test_explicit_open_and_closed_without_dates(self):
        self.assert_state(answer('Applications are open now.'), 'open')
        self.assert_state(answer('Applications are currently closed.'), 'closed')
        self.assert_unknown(answer('Applications are open now.', DATES_Q))

    def test_date_bounds_include_both_exact_boundaries(self):
        body = 'Application period: March 8 – May 17, 2034.'
        for day in ['2034-03-08', '2034-04-09', '2034-05-17']:
            with self.subTest(day=day):
                self.assert_state(answer(body, day=day), 'open')
        self.assert_state(answer(body, day='2034-03-07'), 'not yet open')
        self.assert_state(answer(body, day='2034-05-18'), 'closed')

    def test_one_sided_start_does_not_invent_an_end_or_open_state(self):
        body = 'Application period begins March 8, 2034.'
        self.assert_unknown(answer(body, day='2034-04-09'))
        self.assert_unknown(answer(body, day='2034-03-08'))
        self.assert_state(answer(body, day='2034-03-07'), 'not yet open')
        a = answer(body, 'When does the nonprofit grant application period begin?')
        self.assertTrue(a.confident)
        self.assertIn('March 8, 2034', a.text)
        self.assertNotIn('ends', a.text.lower())

    def test_one_sided_end_does_not_invent_a_start_or_open_state(self):
        body = 'Applications deadline: May 17, 2034.'
        self.assert_unknown(answer(body))
        self.assert_unknown(answer(body, day='2034-05-17'))
        self.assert_state(answer(body, day='2034-05-18'), 'closed')
        a = answer(body, 'What is the nonprofit grant application deadline?')
        self.assertTrue(a.confident)
        self.assertIn('May 17, 2034', a.text)
        self.assertNotIn('begins', a.text.lower())

    def test_separate_open_deadline_lines_can_bind_in_same_section(self):
        body = 'Application opens: March 8, 2034.\nApplications deadline: May 17, 2034.'
        self.assert_state(answer(body), 'open')
        self.assertIn('May 17, 2034', answer(body, DATES_Q).text)

    def test_undated_days_do_not_borrow_next_cycle_or_snapshot_year(self):
        body = 'Applications are open from March 8 through May 17. The next grant cycle begins in 2036.'
        self.assert_unknown(answer(body))
        record, _ = facts._program(Context(snapshot(body)), page(body))
        self.assertIsNone(record['start'])
        self.assertIsNone(record['end'])

    def test_iso_and_explicit_cross_year_dates(self):
        self.assert_state(answer('Applications are open from 2034-03-08 through 2034-05-17.'), 'open')
        body = 'Application period: December 19, 2033 through January 11, 2034.'
        self.assert_state(answer(body, day='2034-01-02'), 'open')

    def test_invalid_or_reversed_date_pair_is_uncertain(self):
        for body in ['Application period: May 17, 2034 through March 8, 2034.',
                     'Applications are open from February 30, 2034 through May 17, 2034.']:
            self.assert_unknown(answer(body))

    def test_current_heading_outranks_explicit_history(self):
        body = ('## Current application window\nApplication period: March 8 – May 17, 2034.\n'
                '## Previous cycle\nApplication period: June 1 – July 3, 2031.')
        self.assert_state(answer(body), 'open')
        a = answer(body, DATES_Q)
        self.assertIn('2034', a.text)
        self.assertNotIn('2031', a.text)
        history = answer(body, 'What were the nonprofit grant application dates for 2031?')
        self.assertTrue(history.confident)
        self.assertIn('June 1, 2031', history.text)
        self.assertNotIn('2034', history.text)

    def test_multiple_equal_current_windows_remain_ambiguous(self):
        body = ('Application period: March 8 – May 17, 2034.\n'
                'Application period: July 2 – August 3, 2034.')
        self.assert_unknown(answer(body))
        self.assert_unknown(answer(body, DATES_Q))

    def test_next_year_and_historical_window_do_not_establish_current_state(self):
        body = ('The next grant cycle begins in 2036.\n## Previous cycle\n'
                'Application period: March 8 – May 17, 2031.')
        self.assert_unknown(answer(body))

    def test_conflicting_current_literal_states_are_uncertain(self):
        self.assert_unknown(answer('Applications are open now. Applications are currently closed.'))

    def test_before_first_snapshot_and_removed_page_preserve_refusal(self):
        k = solution.build()
        k.ingest(snapshot('Applications are open now.'))
        self.assert_unknown(k.answer(OPEN_Q, '2030-01-01'))
        k.ingest(NS(snapshot_id='removed', taken_on='2034-05-03', pages=[]))
        self.assertFalse(k.answer(OPEN_Q).confident)

    def test_compound_request_preserves_known_part_and_unknown_part(self):
        k = solution.build()
        k.ingest(snapshot('Applications are open from March 8, 2034 through May 17, 2034.',
                          extra=[page('The next application cycle begins in 2036.', 'scholarship')]))
        a = k.answer(OPEN_Q + ' And are scholarship applications currently open?')
        self.assertFalse(a.confident)
        self.assertRegex(a.text.lower(), r'\bwindow is open\b')
        self.assertIn("don't know", a.text.lower())
        self.assertNotIn('2036', a.text)

    def test_nonstatus_program_question_uses_eligibility_section(self):
        body = ('Application period: March 8 – May 17, 2034.\n'
                '## Eligibility\nRegistered neighborhood associations may apply.')
        a = answer(body, 'Who can apply for the nonprofit grant?')
        self.assertTrue(a.confident)
        self.assertIn('Registered neighborhood associations', a.text)
        self.assertNotIn('application period', a.text.lower())

    def test_sources_are_actual_raw_spans_and_result_mutation_isolated(self):
        body = 'Applications are **open** from March 8, 2034 through May 17, 2034.'
        k = solution.build()
        s = snapshot(body)
        k.ingest(s)
        wanted = dataclasses.asdict(k.answer(OPEN_Q))
        self.assertTrue(wanted['confident'])
        for source in wanted['sources']:
            self.assertEqual(source['snapshot_id'], s.snapshot_id)
            self.assertTrue(source['quote'] is None or source['quote'] in s.pages[0].markdown)
        a = k.answer(OPEN_Q)
        a.sources.clear()
        self.assertEqual(dataclasses.asdict(k.answer(OPEN_Q)), wanted)


if __name__ == '__main__':
    unittest.main()
