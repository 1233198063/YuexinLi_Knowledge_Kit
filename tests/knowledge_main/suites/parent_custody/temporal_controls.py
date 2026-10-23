"""Arbitrary-value controls for API/query/capture/effective-date semantics."""
import argparse
import dataclasses
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'submission'


def load():
    sys.path.insert(0,str(RUNTIME))
    spec=importlib.util.spec_from_file_location('candidate_temporal',RUNTIME/'solution.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module.build()


def page(apr,effective,term=30,amount=330000,url='https://ice.example/personal/loans/home-loans',title='Ice Home Loans'):
    md=f'''# Home Loans - Purchase
| Program | Rate | Points | APR | Payment |
|---|---|---|---|---|
| Purchase: {term}-Year Fixed Conventional ${amount:,} or less | 2.01% | 0 | {apr}% | $811 |

Rates effective as of {effective}.
'''
    return NS(url=url,title=title,markdown=md,fetched_at=effective)


def snap(sid,day,pages):return NS(snapshot_id=sid,taken_on=day,pages=pages)


class TemporalControls(unittest.TestCase):
    def setUp(self):
        self.ks=load()
        self.ks.ingest(snap('first','2035-01-10',[page('3.731','01/08/2035')]))
        self.ks.ingest(snap('second','2035-03-10',[page('4.817','03/08/2035')]))
        self.ks.ingest(snap('third','2035-05-10',[page('5.913','05/08/2035')]))

    def assert_apr(self,a,wanted,others=()):
        self.assertTrue(a.confident,a.text);self.assertIn(wanted+'%',a.text)
        for n in others:self.assertNotIn(n+'%',a.text)

    def test_snapshot_boundaries_and_no_eligible_history(self):
        q='What APR for a $220,000 30-year purchase mortgage?'
        self.assertFalse(self.ks.answer(q,'2035-01-09').confident)
        self.assert_apr(self.ks.answer(q,'2035-01-10'),'3.731',['4.817','5.913'])
        self.assert_apr(self.ks.answer(q,'2035-03-09'),'3.731',['4.817','5.913'])
        self.assert_apr(self.ks.answer(q,'2035-03-10'),'4.817',['3.731','5.913'])
        self.assert_apr(self.ks.answer(q,'2035-03-11'),'4.817',['3.731','5.913'])

    def test_api_date_overrides_old_question_date(self):
        self.assert_apr(self.ks.answer('As of January 10, 2035, what APR for a $220,000 30-year purchase mortgage?','2035-03-10'),'4.817',['3.731','5.913'])

    def test_api_date_overrides_later_question_date(self):
        self.assert_apr(self.ks.answer('As of May 10, 2035, what APR for a $220,000 30-year purchase mortgage?','2035-01-10'),'3.731',['4.817','5.913'])

    def test_api_date_is_preserved_for_each_compound_clause(self):
        q='As of May 10, 2035, what APR for a $220,000 30-year purchase mortgage; and as of May 10, 2035, what APR for a $250,000 30-year purchase mortgage?'
        self.assert_apr(self.ks.answer(q,'2035-01-10'),'3.731',['4.817','5.913'])

    def test_compound_question_dates_work_when_api_is_absent(self):
        q='As of January 10, 2035, what APR for a $220,000 30-year purchase mortgage; and as of May 10, 2035, what APR for a $250,000 30-year purchase mortgage?'
        a=self.ks.answer(q);self.assert_apr(a,'3.731',['4.817']);self.assertIn('5.913%',a.text)
        self.assertEqual({s.snapshot_id for s in a.sources},{'first','third'})

    def test_repeated_date_calls_do_not_share_the_wrong_cache(self):
        q='What APR for a $220,000 30-year purchase mortgage?'
        old=self.ks.answer(q,'2035-01-10');new=self.ks.answer(q,'2035-05-10');again=self.ks.answer(q,'2035-01-10')
        self.assertEqual(old,again);self.assertNotEqual(old.text,new.text)

    def test_api_after_newest_uses_latest_available_snapshot(self):
        self.assert_apr(self.ks.answer('What APR for a $220,000 30-year purchase mortgage?','2036-08-19'),'5.913',['3.731','4.817'])

    def test_invalid_api_date_does_not_lexically_select_a_snapshot(self):
        for bad in ['2035-02-31','not-a-date','2035-99-01']:
            a=self.ks.answer('What APR for a $220,000 30-year purchase mortgage?',bad)
            self.assertFalse(a.confident,a.text);self.assertEqual(a.sources,[])

    def test_effective_date_in_a_future_snapshot_cannot_rewrite_earlier_capture(self):
        self.assert_apr(self.ks.answer('What APR for a $220,000 30-year purchase mortgage?','2035-05-07'),'4.817',['3.731','5.913'])

    def test_within_selected_snapshot_future_effective_value_is_unknown(self):
        k=load();k.ingest(snap('future-only','2035-01-10',[page('9.179','May 8, 2035')]))
        a=k.answer('What APR for a $220,000 30-year purchase mortgage?','2035-01-10')
        self.assertFalse(a.confident,a.text);self.assertNotIn('9.179%',a.text)

    def test_history_comparison_does_not_adopt_the_last_mentioned_model_year(self):
        q='How did the $220,000 30-year purchase mortgage APR change from January 2035 to May 2035?'
        a=self.ks.answer(q);self.assertTrue(a.confident,a.text)
        for value in ['3.731','4.817','5.913']:self.assertIn(value+'%',a.text)

    def test_future_cycle_notice_is_not_proof_of_current_application_status(self):
        k=load();p=NS(url='https://ice.example/scholarships',title='Scholarships',fetched_at='2035-01-10',markdown='# Scholarships\n\nNext application cycle will be announced in 2036.\n')
        k.ingest(snap('notice','2035-01-10',[p]))
        a=k.answer('Are scholarship applications open now?','2035-01-10')
        self.assertFalse(a.confident,a.text)

    def test_date_wordings_agree_before_a_second_change_in_same_month(self):
        self.ks.ingest(snap('march-later','2035-03-20',[page('7.313','03/20/2035')]))
        queries=['As of Mar. 10, 2035, what APR for a $220,000 30-year purchase mortgage?',
                 'As of 03/10/2035, what APR for a $220,000 30-year purchase mortgage?',
                 'As of mid-March 2035, what APR for a $220,000 30-year purchase mortgage?',
                 'As of 10 March 2035, what APR for a $220,000 30-year purchase mortgage?',
                 'As of March 10th, 2035, what APR for a $220,000 30-year purchase mortgage?',
                 'As of March 10, 2035, what APR for a $220,000 30-year purchase mortgage?']
        for q in queries:self.assert_apr(self.ks.answer(q),'4.817',['3.731','5.913','7.313'])

    def test_abbreviated_question_dates_are_removed_without_changing_model_year(self):
        k=load()
        md='''# Auto & Motorcycle Loans
| Loan Program | Term | Annual Percentage Rate (As Low As) |
|---|---|---|
| 2034-36 Model Year | 60 Months | 4.917% APR |
| 2031-33 Model Year | 60 Months | 6.113% APR |

Rates effective as of 03/08/2035.
'''
        p=NS(url='https://ice.example/personal/loans/auto-motorcycle-loans',title='Auto Loans',markdown=md,fetched_at='2035-03-10')
        k.ingest(snap('auto','2035-03-10',[p]))
        a=k.answer('As of Mar. 10, 2035, what APR for a 2032 auto loan for 60 months?')
        self.assert_apr(a,'6.113',['4.917'])

    def test_enumerated_history_remains_inside_api_cutoff(self):
        q='Compare the $220,000 30-year purchase mortgage APR across each snapshot on January 10, 2035, March 10, 2035 and May 10, 2035.'
        a=self.ks.answer(q,'2035-03-11')
        self.assertTrue(a.confident,a.text)
        self.assertIn('3.731%',a.text);self.assertIn('4.817%',a.text);self.assertNotIn('5.913%',a.text)
        self.assertTrue(all(s.snapshot_id in {'first','second'} for s in a.sources))

    def test_explicit_invalid_question_date_is_not_latest(self):
        a=self.ks.answer('As of February 30, 2035, what APR for a $220,000 30-year purchase mortgage?')
        self.assertFalse(a.confident,a.text)
        for n in ['3.731','4.817','5.913']:self.assertNotIn(n+'%',a.text)

    def test_simple_fact_source_effective_date_is_respected(self):
        k=load();p=NS(url='https://ice.example/future-note',title='Aurora Savings',fetched_at='2035-01-10',
                      markdown='# Aurora Savings\n\nEffective May 8, 2035\n\nAurora Savings APY: 9.179%\n')
        k.ingest(snap('simple-future','2035-01-10',[p]))
        a=k.answer('What is the current Aurora Savings APY?','2035-01-10')
        self.assertFalse(a.confident,a.text);self.assertNotIn('9.179%',a.text)

    def test_simple_fact_identity_cannot_drop_product_qualifier(self):
        k=load();p=NS(url='https://ice.example/metrics',title='Aurora Products',fetched_at='2035-01-10',
                      markdown='# Aurora Products\n\nAurora Savings APY: 3.717%\nAurora Certificate APY: 8.913%\n')
        k.ingest(snap('simple-products','2035-01-10',[p]))
        a=k.answer('What is the Aurora Certificate APY?','2035-01-10')
        self.assertTrue(a.confident,a.text);self.assertIn('8.913%',a.text);self.assertNotIn('3.717%',a.text)

    def test_unknown_current_cycle_does_not_adopt_old_open_date(self):
        k=load();p=NS(url='https://ice.example/nonprofit-grant',title='Nonprofit Grant',fetched_at='2035-01-10',
                      markdown='# Nonprofit Grant\n\nApplication opens: April 1, 2032\n\nThe next grant cycle begins in 2036. We have not announced whether the next application window is open, or its dates.\n')
        k.ingest(snap('unannounced','2035-01-10',[p]))
        a=k.answer('Are nonprofit grant applications currently open?','2035-01-10')
        self.assertFalse(a.confident,a.text)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runtime',type=Path,default=RUNTIME);p.add_argument('--out',type=Path)
    args=p.parse_args();RUNTIME=args.runtime.resolve()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TemporalControls))
    report={'total':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors),
            'failures':[{'test':str(t),'traceback':e} for t,e in result.failures+result.errors]}
    if args.out:args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2)+'\n')
    sys.exit(not result.wasSuccessful())
