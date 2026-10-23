"""Preimplementation arbitrary-input specification. No actual-answer fixtures."""
import argparse
import dataclasses
import importlib.util
from pathlib import Path
import sys
import unittest

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--submission', required=True)
parser.add_argument('--phase', default='1')
args, rest = parser.parse_known_args()
ROOT = Path(args.submission).resolve()
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('experiment_solution', ROOT / 'solution.py')
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

@dataclasses.dataclass(frozen=True)
class Page:
    url: str
    title: str
    markdown: str
    fetched_at: str = '2026-06-01'

@dataclasses.dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    taken_on: str
    pages: list

DOC = '''# Cobalt Loan\n\n## Application documents\nCobalt Loan applicants must provide:\n- A signed project plan.\n- Proof of address.\n- A current equipment inventory.\nApplications without the signed plan cannot be processed.\n\n## How to apply\nSubmit the documents through [the secure intake form](https://example.org/intake).\nStaff confirm receipt by email.\n\n## Loan rates\nThe advertised APR is 8.72%.\n\n## Frequently Asked Questions\n**Can I apply for Cobalt Loan without an equipment inventory?**\nNo. An equipment inventory is required for Cobalt Loan.\n\n**Can I apply for Cobalt Loan without a business registration?**\nYes. Cobalt Loan does not require a business registration.\n'''

class PlannerMechanism(unittest.TestCase):
    def make(self, pages=None, on=True, snapshots=None):
        ks = mod.build(enable_request_planner=on)
        for s in snapshots or [Snapshot('s1','2026-06-01', pages or [Page('https://example.org/cobalt','Cobalt Loan',DOC)])]:
            ks.ingest(s)
        return ks

    def decision(self, ks, q, when=None):
        from request_planner import analyze, resolve
        ctx = ks._at(when)
        return resolve(ctx, analyze(ctx,q,when,False, phase=int(args.phase)))

    def test_complete_list_with_final_disqualifier_and_exact_quote(self):
        ks = self.make()
        q = 'Which application documents are required for Cobalt Loan?'
        d = self.decision(ks,q)
        self.assertEqual('SOURCE_ANSWER',d.kind)
        a = ks.answer(q)
        for part in ('signed project plan','Proof of address','equipment inventory','without the signed plan'):
            self.assertIn(part,a.text)
        self.assertNotIn('8.72',a.text)
        self.assertNotIn('receipt',a.text)
        self.assertTrue(a.confident)
        self.assertIn(a.sources[0].quote,DOC)
        self.assertIn('cannot be processed',a.sources[0].quote)

    def test_actual_early_dispatch_not_terminal_fallback(self):
        ks = self.make()
        for m in ks.modules:
            old = m.answer
            m.answer = lambda ctx,q: ctx.reply('WRONG unrelated member benefit: 99.9%.')
            try:
                a = ks.answer('List the application documents for Cobalt Loan.')
                self.assertNotIn('99.9',a.text)
                self.assertIn('equipment inventory',a.text)
            finally:
                m.answer = old

    def test_generic_words_cannot_establish_entity(self):
        ks = self.make()
        for q in ('What benefits do loan members get?', 'What documents are needed for a loan?', 'How do members apply?', 'What documents does Indigo Loan require?'):
            self.assertEqual('DELEGATE_PARENT',self.decision(ks,q).kind,q)

    def test_anchored_unsupported_facet_is_unknown(self):
        ks = self.make()
        for q in ('What residency requirement does Cobalt Loan publish?', 'Which insurance documents are required for Cobalt Loan?', 'Can I apply for Cobalt Loan without an inspection?'):
            self.assertEqual('ABSTAIN',self.decision(ks,q).kind,q)
            self.assertFalse(ks.answer(q).confident)

    def test_renamed_source_only_actual_labels_and_urls(self):
        pages=[Page('https://example.org/relocated-zeta','Zeta Loan',DOC.replace('Cobalt','Zeta'))]
        ks=self.make(pages)
        a=ks.answer('What application documents does Zeta Loan require?')
        self.assertTrue(a.confident)
        self.assertEqual('https://example.org/relocated-zeta',a.sources[0].url)
        self.assertEqual('DELEGATE_PARENT',self.decision(ks,'What application documents does Cobalt Loan require?').kind)

    def test_scope_is_explicit_and_ambiguity_cannot_choose_by_order(self):
        personal=Page('https://example.org/p','Personal Cobalt Loan',DOC.replace('# Cobalt','# Personal Cobalt'))
        business=Page('https://example.org/b','Business Cobalt Loan',DOC.replace('# Cobalt','# Business Cobalt').replace('equipment inventory','business ledger'))
        for pages in ([personal,business],[business,personal]):
            ks=self.make(pages)
            self.assertEqual('ABSTAIN',self.decision(ks,'What application documents does Cobalt Loan require?').kind)
            a=ks.answer('What application documents does personal Cobalt Loan require?')
            self.assertTrue(a.confident)
            self.assertIn('equipment inventory',a.text)
            self.assertNotIn('business ledger',a.text)

    def test_explicit_source_wrong_overlap_and_missing_url(self):
        wrong=Page('https://example.org/wrong','Application Documents', '# Application Documents\nCobalt Loan members see a teller.\n')
        ks=self.make([wrong,Page('https://example.org/cobalt','Cobalt Loan',DOC)])
        a=ks.answer('According to https://example.org/cobalt, what application documents does Cobalt Loan require?')
        self.assertTrue(a.confident)
        self.assertIn('inventory',a.text)
        self.assertFalse(ks.answer('According to https://example.org/absent, what application documents does Cobalt Loan require?').confident)

    def test_opposite_faq_verdicts_do_not_transfer(self):
        ks=self.make()
        q='Can I apply for Cobalt Loan without an equipment inventory?'
        a=ks.answer(q)
        self.assertTrue(a.confident)
        self.assertIn('No.',a.text)
        self.assertNotIn('Yes.',a.text)
        q='Can I apply for Cobalt Loan without a business registration?'
        a=ks.answer(q)
        self.assertTrue(a.confident)
        self.assertIn('Yes.',a.text)
        a=ks.answer('Can I apply for Cobalt Loan with an equipment inventory?')
        self.assertFalse(a.confident)
        self.assertNotIn('No.',a.text)
        self.assertNotIn('Yes.',a.text)

    def test_changed_conditions_negation_and_or_cannot_copy_verdict(self):
        ks=self.make()
        for q in ('Can I apply for Cobalt Loan without an equipment inventory and a business registration?', 'Can I apply for Cobalt Loan without an equipment inventory or a business registration?', 'Can I not apply for Cobalt Loan without an equipment inventory?', 'Can a business apply for Cobalt Loan without an equipment inventory?'):
            self.assertFalse(ks.answer(q).confident,q)

    def test_protected_pricing_history_branch_counter_program_status(self):
        ks=self.make()
        for q in ('What APR does Cobalt Loan advertise?', 'What rate and application documents does Cobalt Loan publish?', 'How did Cobalt Loan requirements change between snapshots?', 'What is the Cobalt Loan branch address?', 'How many Cobalt Loan members are there?', 'Is the Cobalt Loan program open for applications now?', 'What is my Cobalt Loan account number?'):
            self.assertEqual('DELEGATE_PARENT',self.decision(ks,q).kind,q)

    def test_exact_as_of_selection_changed_restriction_and_removed_source(self):
        old=Page('https://example.org/cobalt','Cobalt Loan',DOC)
        new=Page('https://example.org/cobalt','Cobalt Loan',DOC.replace('current equipment inventory','current safety certificate'))
        ks=self.make(snapshots=[Snapshot('old','2026-02-01',[old]),Snapshot('new','2026-06-01',[new])])
        q='As of 2026-03-01, what application documents does Cobalt Loan require?'
        a=ks.answer(q)
        self.assertIn('equipment inventory',a.text)
        self.assertEqual('old',a.sources[0].snapshot_id)
        a=ks.answer('What application documents does Cobalt Loan require?',as_of='2026-06-10')
        self.assertIn('safety certificate',a.text)
        self.assertNotIn('current equipment inventory',a.text)
        ks.ingest(Snapshot('new','2026-06-01',[]))
        self.assertEqual('DELEGATE_PARENT',self.decision(ks,'What application documents does Cobalt Loan require?').kind)

    def test_empty_heading_and_oversized_section_are_not_confident(self):
        for body in ('# Cobalt Loan\n## Application documents\n', '# Cobalt Loan\n## Application documents\n'+('A required application document is a signed plan.\n'*200)):
            ks=self.make([Page('https://example.org/cobalt','Cobalt Loan',body)])
            d=self.decision(ks,'What application documents does Cobalt Loan require?')
            self.assertEqual('ABSTAIN',d.kind)

    def test_peer_conflicts_no_new_winner_and_duplicate_order_invariant(self):
        a=Page('https://example.org/a','Cobalt Loan',DOC)
        b=Page('https://example.org/b','Cobalt Loan',DOC.replace('Proof of address','Proof of income'))
        q='What application documents does Cobalt Loan require?'
        for pages in ([a,b],[b,a]):
            self.assertEqual('ABSTAIN',self.decision(self.make(pages),q).kind)
        dup=Page('https://example.org/copy','Cobalt Loan',DOC)
        ks=self.make([a,dup])
        self.assertEqual('SOURCE_ANSWER',self.decision(ks,q).kind)

    def test_repeat_returncopy_reingest_and_conflicts_unchanged(self):
        ks=self.make()
        q='Which application documents are required for Cobalt Loan?'
        before=ks.conflicts()
        a=ks.answer(q)
        original=a.text
        a.text='MUTATED'
        a.sources.clear()
        self.assertEqual(original,ks.answer(q).text)
        self.assertTrue(ks.answer(q).sources)
        self.assertEqual(before,ks.conflicts())
        self.assertEqual(ks.answer(q).text,ks.answer('List the application documents for Cobalt Loan.').text)
        ks.ingest(Snapshot('s1','2026-06-01',[Page('https://example.org/cobalt','Cobalt Loan',DOC.replace('Proof of address','Proof of residency'))]))
        self.assertIn('Proof of residency',ks.answer(q).text)

    def test_no_unasked_quantitative_values(self):
        body=DOC.replace('Applications without','The deposit balance threshold is $8,450. Applications without')
        ks=self.make([Page('https://example.org/cobalt','Cobalt Loan',body)])
        self.assertEqual('ABSTAIN',self.decision(ks,'Which application documents are required for Cobalt Loan?').kind)
        self.assertNotIn('8,450',ks.answer('Which application documents are required for Cobalt Loan?').text)

    @unittest.skipUnless(args.phase=='2','iteration 2 bounded extension')
    def test_multiple_h1_entity_ancestry_does_not_cross_bind(self):
        body='# Jasper Loan\n## Application documents\nJasper Loan requires a signed plan.\n# Emerald Loan\n## Application documents\nEmerald Loan requires an inventory.\n'
        ks=self.make([Page('https://example.org/guide','Loan Guide',body)])
        a=ks.answer('What application documents does Jasper Loan require?')
        self.assertNotIn('inventory',a.text)
        if a.confident:self.assertIn('signed plan',a.text)

    @unittest.skipUnless(args.phase=='2','iteration 2 bounded extension')
    def test_inherited_facet_heading_cannot_select_unrelated_child(self):
        body='# Cobalt Loan\n## Application documents\nCobalt Loan applicants must provide a signed project plan.\n### Mug benefits\nThe welcome mug includes a decorative document.\n'
        ks=self.make([Page('https://example.org/cobalt','Cobalt Loan',body)])
        a=ks.answer('What application documents does Cobalt Loan require?')
        self.assertNotIn('decorative',a.text)
        self.assertNotIn('mug',a.text.lower())

    @unittest.skipUnless(args.phase=='2','iteration 2 bounded extension')
    def test_same_page_peer_docs_disagreement_refuses_under_reorder(self):
        one='## Application documents\nCobalt Loan requires a signed project plan.\n'
        two='## Application documents\nCobalt Loan requires a current inventory.\n'
        for body in ('# Cobalt Loan\n'+one+two,'# Cobalt Loan\n'+two+one):
            ks=self.make([Page('https://example.org/cobalt','Cobalt Loan',body)])
            a=ks.answer('What application documents does Cobalt Loan require?')
            self.assertFalse(a.confident)
            self.assertNotIn('signed project plan',a.text)
            self.assertNotIn('current inventory',a.text)

    @unittest.skipUnless(args.phase=='2','iteration 2 bounded extension')
    def test_raw_heading_and_spelled_financial_assertions_guarded(self):
        for body in ('# Cobalt Loan\n## Application documents: APR 9.91%\nCobalt Loan requires a signed plan.\n', '# Cobalt Loan\n## Application documents\nCobalt Loan requires a signed plan. The replacement fee is two hundred dollars.\n', '# Cobalt Loan\n## Application documents: program closed\nCobalt Loan requires a signed plan.\n'):
            ks=self.make([Page('https://example.org/cobalt','Cobalt Loan',body)])
            a=ks.answer('What application documents does Cobalt Loan require?')
            self.assertFalse(a.confident)
            for value in ('9.91','two hundred','program closed'):self.assertNotIn(value,a.text)

    @unittest.skipUnless(args.phase=='2','iteration 2 bounded extension')
    def test_attribution_does_not_add_unasked_title_value(self):
        ks=self.make([Page('https://example.org/cobalt','Cobalt Loan: Earn 9.91% now',DOC)])
        a=ks.answer('What application documents does Cobalt Loan require?')
        self.assertTrue(a.confident)
        self.assertNotIn('9.91',a.text)
        self.assertNotIn('8.72',a.text)

    @unittest.skipUnless(args.phase=='2','iteration 2 bounded extension')
    def test_explicit_scope_requires_source_declaration(self):
        ks=self.make()
        self.assertFalse(ks.answer('What application documents does business Cobalt Loan require?').confident)

    @unittest.skipUnless(args.phase=='2','iteration 2 bounded extension')
    def test_unknown_additional_facet_and_disjunction_cannot_compose(self):
        ks=self.make()
        for q in ('List Cobalt Loan application documents and explain the insurance requirement.', 'List Cobalt Loan application documents or explain how to apply.'):
            self.assertFalse(ks.answer(q).confident,q)

    @unittest.skipUnless(args.phase=='2','iteration 2 bounded extension')
    def test_two_complete_same_page_facets_keep_link(self):
        ks=self.make()
        q='List Cobalt Loan application documents and explain how to apply.'
        a=ks.answer(q)
        self.assertTrue(a.confident)
        for v in ('inventory','cannot be processed','secure intake form','https://example.org/intake','confirm receipt'):
            self.assertIn(v,a.text)
        self.assertNotIn('8.72',a.text)
        self.assertEqual(1,len(a.sources))
        self.assertIn(a.sources[0].quote,DOC)

    @unittest.skipUnless(args.phase=='2','iteration 2 bounded extension')
    def test_asked_duration_and_count_preserve_operators_conditions(self):
        body='''# Amber Access\n## Qualification requirements\nAmber Access applicants must be at least 19 years old and provide exactly 3 identity documents. Newly transferred funds must arrive within 17 days of registration. Funds from an Amber Access account are excluded.\n'''
        ks=self.make([Page('https://example.org/amber','Amber Access',body)])
        q='What age, document count and funds arrival duration requirements does Amber Access publish?'
        a=ks.answer(q)
        self.assertTrue(a.confident)
        for v in ('at least 19','exactly 3','within 17 days','of registration','are excluded'):
            self.assertIn(v,a.text)

    @unittest.skipUnless(args.phase=='2','iteration 2 bounded extension')
    def test_duration_does_not_become_as_of_and_peer_literal_disagreement(self):
        body='# Amber Access\n## Funds arrival duration\nNew funds for Amber Access must arrive within 17 days of registration. Transfers from an Amber Access account are excluded.\n'
        a=Page('https://example.org/amber','Amber Access',body)
        ks=self.make([a])
        self.assertTrue(ks.answer('What funds arrival duration does Amber Access require?').confident)
        b=Page('https://example.org/peer','Amber Access',body.replace('17 days','11 days'))
        ks=self.make([a,b])
        answer=ks.answer('What funds arrival duration does Amber Access require?')
        self.assertFalse(answer.confident)
        self.assertNotIn('17',answer.text)
        self.assertNotIn('11',answer.text)

if __name__=='__main__':
    unittest.main(argv=[sys.argv[0]]+rest)
