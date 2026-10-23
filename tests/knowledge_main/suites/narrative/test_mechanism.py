"""Arbitrary-source controls written before the integration implementation.

No organizer snapshots, question banks, or expected challenge values are used.
"""
import copy
import dataclasses
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = Path(__import__('os').environ.get('EXPERIMENT_CANDIDATE', ROOT / 'candidate'))
sys.path.insert(0, str(CANDIDATE))
import solution
from common import Context
from narrative_adapter import NarrativeGate


Q = 'How does the Cedar canvas panel organize notes?'
A = 'Choose Create, give the note a label, and drag it into the matching collection.'


def page(text=None, url='https://cedar.example/tools/canvas', title='Cedar canvas panel'):
    return SimpleNamespace(url=url, title=title, markdown=text or f'# {title}\n\n- {Q}\n\n{A}\n')


def snapshot(pages, sid='source-a', date='2024-04-08'):
    return SimpleNamespace(snapshot_id=sid, taken_on=date, pages=pages)


def plain_answer(a):
    return dataclasses.asdict(a)


def baseline(text='Cedar collections group notes for display.', confident=True):
    return dict(text=text, sources=[], confident=confident, conflict_note=None)


class SourceAdmission(unittest.TestCase):
    def setUp(self):
        self.gate = NarrativeGate()

    def admitted(self, pages=None, q=Q, raw=None):
        ctx = Context(snapshot(pages or [page()]))
        return self.gate.maybe_reply(ctx, q, raw or baseline())

    def test_exact_faq_is_complete_and_keeps_question_context(self):
        raw = self.admitted()
        self.assertEqual(raw['text'], Q + ' ' + A)
        self.assertTrue(raw['confident'])
        self.assertEqual(raw['sources'][0]['url'], page().url)

    def test_parent_fully_covering_facets_stays_identical(self):
        original = baseline(Q + ' ' + A)
        self.assertIs(self.admitted(raw=original), original)

    def test_question_only_terminal_fallback_can_gain_an_answer(self):
        raw = self.admitted(raw=baseline(Q))
        self.assertEqual(raw['text'], Q + ' ' + A)

    def test_every_refusal_stays_identical(self):
        original = baseline("I do not know this information.", confident=False)
        self.assertIs(self.admitted(raw=original), original)

    def test_protected_requests_and_incidental_claims_are_noop(self):
        claims = ['a fee', 'free', 'unlimited', 'a minimum', 'a limit', '$19',
                  'April', 'two branches', 'routing', 'contact', 'address',
                  'Iowa', 'available', 'formerly', 'a rate', 'a schedule']
        for claim in claims:
            with self.subTest(claim=claim):
                q = Q.rstrip('?') + ' and ' + claim + '?'
                original = baseline()
                p = page(f'# Canvas\n\n- {q}\n\n{A}\n')
                self.assertIs(self.admitted([p], q, original), original)
                p = page(f'# Canvas\n\n- {Q}\n\n{A} Includes {claim}.\n')
                self.assertIs(self.admitted([p], Q, original), original)

    def test_wrong_subject_facet_negation_and_condition_reject(self):
        questions = [Q.replace('Cedar', 'Birch'), Q.replace('organize', 'erase'),
                     Q.replace('organize', 'not organize'),
                     Q.rstrip('?') + ' without a label?',
                     Q.rstrip('?') + ' if I omit a label?',
                     Q.rstrip('?') + ' except shared notes?']
        for q in questions:
            with self.subTest(q=q):
                original = baseline()
                self.assertIs(self.admitted(q=q, raw=original), original)

    def test_exact_negative_condition_keeps_full_predicate(self):
        q = 'Can the Cedar canvas panel organize notes without a label?'
        a = 'No. Choose a label before dragging a note into a collection.'
        raw = self.admitted([page(f'# Canvas\n\n- {q}\n\n{a}\n')], q)
        self.assertEqual(raw['text'], q + ' ' + a)

    def test_duplicate_and_competing_passages_reject(self):
        other = page(url='https://cedar.example/tools/alternate')
        for pages in ([page(), other], [other, page()],
                      [page(), page(f'# Canvas\n\n- {Q}\n\nUse Archive to group the notes.\n', other.url)]):
            original = baseline()
            self.assertIs(self.admitted(pages=pages, raw=original), original)

    def test_only_actual_selected_context_pages_are_indexed(self):
        ctx = Context(snapshot([page()]))
        ctx.question_page_scope = page().url
        raw = self.gate.maybe_reply(ctx, Q, baseline())
        self.assertEqual(raw['sources'][0]['url'], ctx.question_page_scope)
        empty = Context(snapshot([], sid='empty-source'))
        original = baseline()
        self.assertIs(self.gate.maybe_reply(empty, Q, original), original)

    def test_long_list_multipart_heading_only_and_borrowed_text_reject(self):
        texts = [f'- {Q}\n\n' + ('Use labels to group the note. ' * 70),
                 f'- {Q}\n\n- Choose Create.\n- Drag the note.\n',
                 f'- {Q}\n\nChoose Create.\n\nDrag the note.\n',
                 f'# {Q}\n\n{A}\n',
                 f'- {Q}\n\nChoose Create.\n\n## Other panel\n\nDrag the note.\n']
        for text in texts:
            original = baseline()
            self.assertIs(self.admitted([page(text)], raw=original), original)

    def test_raw_quote_is_actual_complete_span(self):
        p = page(f'# Canvas\n\n- {Q}\n\nChoose **Create**, give the note a label, and drag it into the matching collection.\n')
        raw = self.admitted([p])
        source = raw['sources'][0]
        self.assertIn(source['quote'], p.markdown)
        self.assertIn('**Create**', source['quote'])
        self.assertIn(Q, source['quote'])


class IntegrationInvariants(unittest.TestCase):
    def build_pair(self, snapshots):
        parent = solution.build_parent()
        combined = solution.build()
        for s in snapshots:
            parent.ingest(s)
            combined.ingest(s)
        return parent, combined

    def test_terminal_only_and_switch_restore_parent(self):
        p, k = self.build_pair([snapshot([page()])])
        a = p.answer(Q)
        self.assertEqual(a.text.lstrip('- '), Q)
        self.assertEqual(k.answer(Q).text, Q + ' ' + A)
        disabled = solution.build(enable_narrative=False)
        disabled.ingest(snapshot([page()]))
        self.assertEqual(plain_answer(disabled.answer(Q)), plain_answer(a))

    def test_asof_removed_pages_and_ingest_cache_invalidation(self):
        p, k = self.build_pair([snapshot([page()]), snapshot([], 'source-b', '2024-07-20')])
        self.assertEqual(k.answer(Q, '2024-05-01').text, Q + ' ' + A)
        self.assertEqual(plain_answer(k.answer(Q)), plain_answer(p.answer(Q)))
        k.ingest(snapshot([], 'source-a', '2024-04-08'))
        p.ingest(snapshot([], 'source-a', '2024-04-08'))
        self.assertEqual(plain_answer(k.answer(Q, '2024-05-01')), plain_answer(p.answer(Q, '2024-05-01')))
        self.assertFalse(k._narrative_gate._cache)

    def test_protected_answers_history_and_conflicts_unchanged(self):
        s = snapshot([page('# Cedar tools\n\nPanel fee: $19\n\n- ' + Q + '\n\n' + A + '\n')])
        p, k = self.build_pair([s, snapshot([page('# Cedar tools\n\nPanel fee: $23\n')], 'source-b', '2024-07-20')])
        before = [dataclasses.asdict(c) for c in k.conflicts()]
        for q in ['What is the panel fee?', 'How has the panel fee changed over time?',
                  'What is my account balance?', 'What is the canvas panel routing number?',
                  'What is the panel fee and how does the Cedar canvas panel organize notes?']:
            self.assertEqual(plain_answer(k.answer(q)), plain_answer(p.answer(q)))
        self.assertEqual(before, [dataclasses.asdict(c) for c in k.conflicts()])
        self.assertEqual(before, [dataclasses.asdict(c) for c in p.conflicts()])

    def test_returned_answers_and_conflicts_do_not_mutate_cache(self):
        p, k = self.build_pair([snapshot([page()])])
        wanted = plain_answer(k.answer(Q))
        a = k.answer(Q)
        a.sources[0].quote = 'mutated'
        a.sources.append(SimpleNamespace(url='invented'))
        self.assertEqual(plain_answer(k.answer(Q)), wanted)
        c = k.conflicts()
        c.append(SimpleNamespace(topic='mutated'))
        self.assertEqual([dataclasses.asdict(x) for x in k.conflicts()],
                         [dataclasses.asdict(x) for x in p.conflicts()])

    def test_dependency_import_without_official_contract(self):
        code = "import solution; k=solution.build(); print(type(k).__name__)"
        result = subprocess.run([sys.executable, '-I', '-c',
                                 "import sys; sys.path.insert(0, " + repr(str(CANDIDATE)) + "); " + code],
                                capture_output=True, text=True, check=True)
        self.assertIn('NarrativeKnowledge', result.stdout)


if __name__ == '__main__':
    unittest.main()
