"""General source-derived controls after limited question-only development exposure."""
import argparse
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'submission'


def build():
    sys.path.insert(0,str(RUNTIME));spec=importlib.util.spec_from_file_location('limited_mechanism_candidate',RUNTIME/'solution.py')
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);return m.build()


def page(path,title,md,day='2037-10-09'):
    return NS(url='https://summit.example'+path,title=title,markdown=md,fetched_at=day)


def ingest(k,sid,day,pages):k.ingest(NS(snapshot_id=sid,taken_on=day,pages=pages))


class LimitedMechanisms(unittest.TestCase):
    def savings(self):
        k=build();p=page('/personal/savings-account','Savings Rates','''# Savings Rates
| Account Type | Balance Tier | Dividend Rate | APY | Min. to Open | Min. to Earn |
|---|---|---|---|---|---|
| Aurora Savings | $700-$9,799.99 | 7.11% | 7.19% | $90 | $700 |
| Aurora Savings | $9,800+ | 8.31% | 8.41% | $90 | $9,800 |
| Orion Money Market | $0+ | 11.61% | 11.73% | $0 | $0 |
''')
        ingest(k,'savings','2037-10-09',[p]);return k

    def test_noun_pair_and_top_metric_bind_to_separate_balances(self):
        a=self.savings().answer('Give the Aurora Savings rate/yield pair for nineteen hundred dollars and the top Aurora Savings annual yield with its starting balance.')
        self.assertTrue(a.confident,a.text)
        for v in ['7.11%','7.19%','8.41%','$9,800']:self.assertIn(v,a.text)
        self.assertNotIn('11.73%',a.text)

    def test_question_head_pair_and_top_is_equivalent(self):
        a=self.savings().answer('What dividend rate and APY apply to $1,900 in Aurora Savings, and what APY and balance threshold define the highest Aurora Savings tier?')
        self.assertTrue(a.confident,a.text)
        for v in ['7.11%','7.19%','8.41%','$9,800']:self.assertIn(v,a.text)

    def auto(self):
        k=build()
        def md(program,apr):return f'''# Auto & Motorcycle Loans
| Loan Program | Term | Annual Percentage Rate (As Low As) |
|---|---|---|
| {program} Model Year | 60 Months | {apr}% APR |
'''
        ingest(k,'old','2037-03-17',[page('/personal/loans/auto-motorcycle-loans','Auto Loans',md('2034-37','2.817')),
                                     page('/personal/checking-accounts','Checking',md('2034-37','8.217'))])
        ingest(k,'new','2037-10-09',[page('/personal/loans/auto-motorcycle-loans','Auto Loans',md('2033-35','4.133'))])
        return k

    def test_both_snapshot_request_does_not_require_compare_verb(self):
        a=self.auto().answer('For a 2035 car financed for 60 months, give the March 17 and October 9 snapshot APRs and identify the authoritative March source.','2037-10-09')
        self.assertTrue(a.confident,a.text);self.assertIn('2.817%',a.text);self.assertIn('4.133%',a.text)
        self.assertIn('product-specific',a.text.lower());self.assertNotIn('8.217%',a.text)
        self.assertEqual({s.snapshot_id for s in a.sources},{'old','new'})

    def card(self):
        k=build();p=page('/personal/credit-cards','Personal Credit Cards','''# Credit Cards
## Platinum Visa
- Lower ongoing rate if you carry a balance: 11.83%–18.31% APR.
- New cardmember transfer introductory APR: 1.731% for eight months.
The 1.731% annual percentage rate (APR) balance transfer introductory rate is valid for new cardholders' balance transfers that post to your Platinum Visa during the first 37 days following the opening of Platinum Visa. The 1.731% introductory annual percentage rate (APR) expires eight months from the date of your first balance transfer, at which time the standard APR applies.
''')
        ingest(k,'card','2037-10-09',[p]);return k

    def test_two_clocks_offer_wording_preserves_distinct_anchors(self):
        a=self.card().answer('Explain the captured Platinum transfer offer percentage and two timing rules: account-opening qualification versus first-transfer expiry.')
        self.assertTrue(a.confident,a.text)
        for v in ['1.731%','37 days','eight months','first balance transfer']:self.assertIn(v,a.text)
        self.assertNotIn('11.83%',a.text)

    def test_stated_posting_day_is_compared_to_source_window(self):
        a=self.card().answer('A new-card transfer posts on day 38. Can it qualify under the advertised transfer offer? State the introductory APR and distinguish posting from expiry.')
        self.assertTrue(a.confident,a.text);self.assertIn('1.731%',a.text);self.assertIn('No',a.text)
        self.assertIn('37',a.text);self.assertIn('eight months',a.text)

    def test_following_range_is_a_requested_fact_not_an_unasked_extra(self):
        a=self.card().answer('What transfer intro APR applies, for how long, and what range follows?')
        self.assertTrue(a.confident,a.text);self.assertIn('1.731%',a.text)
        self.assertIn('11.83%',a.text);self.assertIn('18.31%',a.text)

    def privacy(self,condition=True):
        k=build();text='''# Digital Privacy Policy
You can review and change your personal information in your accounts by logging into Summit SecurePortal. You may call Summit at 800-555-0173 to request access to or correct information.
'''
        if condition:text+='\nWe may not accommodate a request to change information if you cannot adequately verify your identity and account ownership.\n'
        ingest(k,'policy','2037-10-09',[page('/renamed-policy','Digital Privacy Policy',text)]);return k

    def test_procedure_is_not_completed_identity_verification(self):
        a=self.privacy().answer('Does reading the public correction instructions mean the bank must change an account without verifying its owner? Give the online route, phone and stated verification limitation.')
        self.assertTrue(a.confident,a.text)
        for v in ['SecurePortal','800-555-0173','may not accommodate','identity and account ownership']:self.assertIn(v,a.text)

    def test_missing_qualification_condition_is_unknown(self):
        a=self.privacy(False).answer('Under the policy, can a bank decline an information correction when ownership cannot be verified?')
        self.assertFalse(a.confident,a.text);self.assertNotIn('may not accommodate',a.text)

    def test_expiry_anchor_comes_from_source_not_offer_default(self):
        k=build();p=page('/personal/credit-cards','Personal Credit Cards','''# Credit Cards
## Platinum Visa
- Lower ongoing rate: 13.17%–19.13% APR.
- New cardmember transfer introductory APR: 1.813% for eleven months.
The balance transfer introductory APR expires eleven months from card opening. Transfers must post during the first 41 days following the opening of the card.
''')
        ingest(k,'different-anchor','2037-10-09',[p]);a=k.answer('Explain the Platinum transfer offer APR and its expiry clock.')
        self.assertTrue(a.confident,a.text);self.assertIn('1.813%',a.text);self.assertIn('card opening',a.text)
        self.assertNotIn('from the first balance transfer',a.text)

    def test_posted_is_the_same_conditional_clock_as_posts(self):
        a=self.card().answer('A new-card transfer posted on day 38. Can it qualify under the advertised transfer offer?')
        self.assertTrue(a.confident,a.text);self.assertIn('No.',a.text)

    def test_both_dates_without_api_uses_upper_history_endpoint(self):
        a=self.auto().answer('Give the 60-month auto APR for a 2035 model on March 17, 2037 and October 9, 2037, showing both dates.')
        self.assertTrue(a.confident,a.text);self.assertIn('2.817%',a.text);self.assertIn('4.133%',a.text)

    def test_actual_account_verification_cannot_be_confirmed_by_public_policy(self):
        a=self.privacy().answer('Has my identity and account ownership been verified and my profile correction completed?')
        self.assertFalse(a.confident,a.text)

    def test_conditional_policy_question_is_not_private_completion_status(self):
        a=self.privacy().answer('What is the privacy policy if my identity and account ownership cannot be verified?')
        self.assertTrue(a.confident,a.text);self.assertIn('may not accommodate',a.text)
        self.assertTrue(a.sources)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runtime',type=Path,default=RUNTIME);p.add_argument('--out',type=Path)
    args=p.parse_args();RUNTIME=args.runtime.resolve()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LimitedMechanisms))
    report={'total':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors),
            'failures':[{'test':str(t),'traceback':e} for t,e in result.failures+result.errors]}
    if args.out:args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,indent=2)+'\n')
    sys.exit(not result.wasSuccessful())
