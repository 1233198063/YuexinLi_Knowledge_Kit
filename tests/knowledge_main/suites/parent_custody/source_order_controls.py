"""Source-order repair controls written before the authorized blocker repair."""
import argparse
import importlib.util
import json
import sys
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace as NS

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'submission'


def build():
    sys.path.insert(0,str(RUNTIME))
    spec=importlib.util.spec_from_file_location('source_order_candidate',RUNTIME/'solution.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module.build()


def p(value,effective,fetch,url):
    return NS(url=url,title='Aurora Savings facts',fetched_at=fetch,
              markdown=f'# Aurora Savings\n\nEffective {effective}\n\nAurora Savings APY: {value}%\n')


class SourceOrder(unittest.TestCase):
    def test_newer_effective_wins_independent_of_fetch_and_page_order(self):
        old=p('2.731','January 8, 2036','2036-03-10','https://aurora.example/a')
        new=p('4.913','February 8, 2036','2036-02-09','https://aurora.example/b')
        for pages in [[old,new],[new,old]]:
            k=build();k.ingest(NS(snapshot_id='same-capture',taken_on='2036-03-10',pages=pages))
            a=k.answer('What is Aurora Savings APY?')
            self.assertTrue(a.confident,a.text);self.assertIn('4.913%',a.text);self.assertNotIn('2.731%',a.text)
            self.assertEqual(a.sources[0].url,new.url)

    def test_equal_effective_disagreement_is_unresolved(self):
        first=p('2.731','February 8, 2036','2036-03-10','https://aurora.example/a')
        second=p('4.913','February 8, 2036','2036-03-10','https://aurora.example/b')
        answers=[]
        for pages in [[first,second],[second,first]]:
            k=build();k.ingest(NS(snapshot_id='tie',taken_on='2036-03-10',pages=pages));a=k.answer('What is Aurora Savings APY?')
            self.assertFalse(a.confident,a.text);self.assertNotIn('2.731%',a.text);self.assertNotIn('4.913%',a.text)
            answers.append(a)
        self.assertEqual(asdict(answers[0]),asdict(answers[1]))

    def test_future_effective_does_not_displace_applicable_fact(self):
        current=p('2.731','February 8, 2036','2036-02-09','https://aurora.example/a')
        future=p('9.317','April 8, 2036','2036-03-10','https://aurora.example/b')
        k=build();k.ingest(NS(snapshot_id='future',taken_on='2036-03-10',pages=[future,current]))
        a=k.answer('What is Aurora Savings APY?')
        self.assertTrue(a.confident,a.text);self.assertIn('2.731%',a.text);self.assertNotIn('9.317%',a.text)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--runtime',type=Path,default=RUNTIME);parser.add_argument('--out',type=Path)
    args=parser.parse_args();RUNTIME=args.runtime.resolve()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SourceOrder))
    report={'total':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors),
            'failures':[{'test':str(t),'traceback':e} for t,e in result.failures+result.errors]}
    if args.out:args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2)+'\n')
    sys.exit(not result.wasSuccessful())
