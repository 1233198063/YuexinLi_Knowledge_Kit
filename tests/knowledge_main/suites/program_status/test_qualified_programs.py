"""New source-governed controls, authored before this repair cycle."""
import dataclasses
from types import SimpleNamespace as NS
import unittest
from test_program_status import solution, page, snapshot, answer, OPEN_Q, DATES_Q


class QualifiedPrograms(unittest.TestCase):
    def test_status_does_not_require_unasked_dates_or_borrow_current_next_cycle(self):
        body = 'Applications are open now. The next grant cycle begins in 2036.'
        a = answer(body, 'Is the nonprofit grant application period currently open?')
        self.assertTrue(a.confident, a.text)
        next_cycle = answer(body, 'Are next nonprofit grant cycle applications currently open?')
        self.assertFalse(next_cycle.confident, next_cycle.text)

    def test_future_schedule_dates_are_known_without_future_status_inference(self):
        body = ('## Effective January 1, 2036\n'
                'Application period: March 8, 2036 through May 17, 2036.')
        next_dates = answer(body, 'What are the next nonprofit grant application dates?')
        self.assertTrue(next_dates.confident, next_dates.text)
        # No next-year pointer is supplied; the actual scheduled cycle is unique.
        a = answer(body, 'What are the nonprofit grant application dates for 2036?')
        self.assertTrue(a.confident, a.text)
        self.assertIn('March 8, 2036', a.text)
        self.assertFalse(answer(body).confident)

    def test_internal_history_uses_each_snapshot_day(self):
        k = solution.build()
        k.ingest(snapshot('Applications are open now.'))
        k.ingest(snapshot('Applications are currently closed.', day='2034-05-20', sid='history-later'))
        a = k.answer('How has nonprofit grant application status changed over time?')
        self.assertTrue(a.confident, a.text)
        self.assertIn('2034-04-09', a.text)
        self.assertIn('2034-05-20', a.text)
        self.assertIn('open', a.text.lower())
        self.assertIn('closed', a.text.lower())

    def test_owner_switch_does_not_borrow_parent_cycle_year(self):
        body = ('## Nonprofit Grant cycle 2036\n'
                '### Scholarship application window\n'
                'Applications are open from March 8 through May 17.')
        a = answer(body, 'What are the scholarship application dates?')
        self.assertFalse(a.confident, a.text)
        self.assertNotIn('2036', a.text)

    def test_natural_individual_program_slots_do_not_make_cross_product(self):
        k = solution.build()
        k.ingest(snapshot('Application period begins March 8, 2034.',
                          extra=[page('Applications deadline: May 17, 2034.', 'scholarship')]))
        a = k.answer('When does nonprofit grant begin and scholarship end?')
        self.assertTrue(a.confident, a.text)
        self.assertIn('Nonprofit Grant application period begins March 8, 2034', a.text)
        self.assertIn('Scholarship application period ends May 17, 2034', a.text)
        self.assertNotIn('Scholarship application period begins', a.text)

    def test_clause_local_days_select_only_eligible_snapshots(self):
        k = solution.build()
        k.ingest(snapshot('Applications are open now.',
                          extra=[page('Applications are currently closed.', 'scholarship')]))
        k.ingest(snapshot('Applications are currently closed.', day='2034-05-20',
                          sid='later', extra=[page('Applications are open now.', 'scholarship')]))
        a = k.answer('As of April 9, 2034 are nonprofit grant applications open? '
                     'Also, as of May 20, 2034 are scholarship applications open?')
        self.assertTrue(a.confident, a.text)
        self.assertIn('2034-04-09', a.text)
        self.assertIn('2034-05-20', a.text)

    def test_title_validity_and_multiline_governing_prefix(self):
        for title in ['Nonprofit Grant Effective January 1, 2036',
                      'Nonprofit Grant Effective January 1, 20360']:
            p = page('Applications are open now.')
            p.title = title
            k = solution.build()
            k.ingest(NS(snapshot_id='title-scope', taken_on='2034-04-09', pages=[p]))
            self.assertFalse(k.answer(OPEN_Q).confident)
        self.assertFalse(answer('Do not assume the following:\nApplications are open now.').confident)

    def test_explicit_nonprofit_subject_is_not_damaged_by_article_removal(self):
        a = answer('Nonprofit Grant applications are open now.')
        self.assertTrue(a.confident, a.text)

    def test_full_polarity_and_conditions_cannot_donate_embedded_open(self):
        for line in ['Do not assume that applications are open now.',
                     'It is false that applications are open now.',
                     'We cannot confirm that applications are open.',
                     'If a committee approves, applications are open now.',
                     'Applications might be open now.',
                     'A spokesperson said "applications are open now".',
                     'Applications are open now unless funding is withheld.']:
            with self.subTest(line=line):
                a = answer(line)
                self.assertFalse(a.confident, a.text)
                self.assertIn("don't know", a.text.lower())

    def test_negated_or_conditional_dates_do_not_form_a_valid_window(self):
        for line in ['It is false that applications are open from March 8, 2034 through May 17, 2034.',
                     'If approved, applications are open from March 8, 2034 through May 17, 2034.']:
            self.assertFalse(answer(line).confident)
            self.assertFalse(answer(line, DATES_Q).confident)

    def test_future_scope_does_not_truncate_to_current_open_or_closed(self):
        for line in ['Effective January 1, 2036, applications are open.',
                     'Beginning January 1, 2036, applications are closed.',
                     'In 2036, applications are open.',
                     'Applications are open from March 8, 20340 through May 17, 20340.']:
            self.assertFalse(answer(line).confident)

    def test_peer_order_cannot_select_conflicting_status_or_dates(self):
        open_page = page('Applications are open now.')
        closed_page = page('Applications are currently closed.')
        closed_page.url += '-peer'
        for pages in [[open_page, closed_page], [closed_page, open_page]]:
            k = solution.build()
            k.ingest(NS(snapshot_id='peers', taken_on='2034-04-09', pages=pages))
            a = k.answer(OPEN_Q)
            self.assertFalse(a.confident, a.text)
            self.assertEqual(len(a.sources), 2)

    def test_explicit_effective_order_is_comparable_without_source_order(self):
        early = page('Effective April 1, 2034, applications are open.')
        late = page('Effective April 5, 2034, applications are closed.')
        late.url += '-peer'
        for pages in [[early, late], [late, early]]:
            k = solution.build()
            k.ingest(NS(snapshot_id='dated-peers', taken_on='2034-04-09', pages=pages))
            a = k.answer(OPEN_Q)
            self.assertTrue(a.confident, a.text)
            self.assertIn('closed', a.text.lower())

    def test_subsection_owner_and_historical_stack_are_retained(self):
        body = ('Nonprofit grant details will be announced.\n'
                '## Scholarship application window\n'
                'Applications are open from March 8, 2034 through May 17, 2034.\n'
                '## Previous nonprofit grant cycle 2031\n'
                '### Application window\nApplication period: June 1 – July 3, 2031.')
        self.assertFalse(answer(body).confident)
        school = answer(body, 'Are scholarship applications currently open?')
        self.assertTrue(school.confident, school.text)
        self.assertIn('Scholarship', school.text)

    def test_explicit_other_program_subject_does_not_answer_parent_owner(self):
        self.assertFalse(answer('Scholarship applications are open now.').confident)
        school = answer('Scholarship applications are open now.',
                        'Are scholarship applications currently open?')
        self.assertTrue(school.confident, school.text)

    def test_unsupported_named_program_does_not_match_generic_source(self):
        self.assertFalse(answer('Applications are open now.',
                                'Are Amber nonprofit grant applications currently open?').confident)

    def test_next_year_conflict_is_field_local(self):
        body = ('Applications are currently closed.\nThe next grant cycle begins in 2036.\n'
                'The next grant cycle begins in 2037.')
        self.assertTrue(answer(body).confident)
        self.assertFalse(answer(body, 'What year does the next nonprofit grant cycle begin?').confident)

    def test_same_program_known_start_and_unknown_status_are_both_rendered(self):
        a = answer('Application period begins March 8, 2034.',
                   'When does the nonprofit grant application period begin and are nonprofit grant applications open?')
        self.assertFalse(a.confident, a.text)
        self.assertIn('March 8, 2034', a.text)
        self.assertIn("don't know", a.text.lower())

    def test_shared_predicate_and_also_keep_every_program(self):
        k = solution.build()
        k.ingest(snapshot('Applications are open from March 8, 2034 through May 17, 2034.',
                          extra=[page('Applications are currently closed.', 'scholarship')]))
        a = k.answer('Are nonprofit grant and scholarship applications currently open?')
        self.assertTrue(a.confident, a.text)
        self.assertIn('Nonprofit Grant', a.text)
        self.assertIn('Scholarship', a.text)
        k = solution.build()
        k.ingest(snapshot('Applications are open from March 8, 2034 through May 17, 2034.',
                          extra=[page('Details will be announced.', 'scholarship')]))
        a = k.answer(OPEN_Q + ' Also, are scholarship applications currently open?')
        self.assertFalse(a.confident)
        self.assertIn('Nonprofit Grant', a.text)
        self.assertIn('Scholarship', a.text)
        self.assertIn("don't know", a.text.lower())

    def test_requested_day_and_same_snapshot_cache_keys_are_distinct(self):
        k = solution.build()
        k.ingest(snapshot('Applications are open from March 8, 2034 through May 17, 2034.',
                          day='2034-03-01'))
        for target, state in [('2034-04-09', 'open'), ('2034-05-20', 'closed'),
                              ('2034-03-07', 'not yet open'), ('2034-04-09', 'open')]:
            a = k.answer(OPEN_Q, target)
            self.assertTrue(a.confident, a.text)
            self.assertIn(state, a.text.lower())
            self.assertIn('2034-03-01', a.text)
            self.assertIn(target, a.text)

    def test_literal_now_does_not_project_to_a_later_requested_day(self):
        k = solution.build()
        k.ingest(snapshot('Applications are open now.'))
        captured = k.answer(OPEN_Q)
        self.assertTrue(captured.confident)
        self.assertIn('2034-04-09', captured.text)
        later = k.answer(OPEN_Q, '2034-04-12')
        self.assertFalse(later.confident, later.text)
        self.assertIn('2034-04-09', later.text)
        self.assertIn('2034-04-12', later.text)

    def test_future_close_does_not_infer_current_open(self):
        k = solution.build()
        k.ingest(snapshot('Beginning January 1, 2036, applications are closed.'))
        self.assertFalse(k.answer(OPEN_Q).confident)
        a = k.answer(OPEN_Q, '2036-01-02')
        self.assertTrue(a.confident, a.text)
        self.assertIn('closed', a.text.lower())

    def test_program_time_does_not_change_nonprogram_price_cache_or_context(self):
        rate = NS(url='https://linden.example/savings', title='Savings',
                  markdown='# Savings\nAnchor savings APY: 3.47%', fetched_at='2034-03-01T08:00:00Z')
        k = solution.build()
        k.ingest(snapshot('Applications are open from March 8, 2034 through May 17, 2034.',
                          day='2034-03-01', extra=[rate]))
        before = dataclasses.asdict(k.answer('What is the Anchor savings APY?', '2034-04-09'))
        k.answer(OPEN_Q, '2034-05-20')
        after = dataclasses.asdict(k.answer('What is the Anchor savings APY?', '2034-04-09'))
        self.assertEqual(before, after)
        self.assertEqual(k._at('2034-05-20').date, '2034-03-01')


if __name__ == '__main__':
    unittest.main()
