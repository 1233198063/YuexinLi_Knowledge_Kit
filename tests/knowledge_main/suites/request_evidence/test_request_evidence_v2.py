"""Public developer controls: complete Answer evidence, not token inclusion.

Run directly; do not discover reviewer-only tests. Runtime is never modified.
The semantic oracle is source-invented and independent of selected renderers.
"""
import argparse
import dataclasses
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from types import SimpleNamespace as NS
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
BASELINE = '2d6b8d6e15cbf78a6e6552904f127b6d6e9856ea68db769ca103c61b768d1115'
FAMILIES = ['Business Platinum Visa', 'Business Rewards Visa', 'Platinum Visa', 'Rewards Visa']


def canonical_hash(runtime):
    runtime = Path(runtime).resolve()
    record = ''.join(p.relative_to(runtime).as_posix()+'\0'+hashlib.sha256(p.read_bytes()).hexdigest()+'\n'
                     for p in sorted(runtime.rglob('*.py')))
    return hashlib.sha256(record.encode()).hexdigest()


def load_runtime(runtime):
    runtime = Path(runtime).resolve()
    sys.path.insert(0, str(runtime))
    spec = importlib.util.spec_from_file_location('_request_evidence_candidate', runtime/'solution.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def norm(text):
    return ' '.join(str(text).lower().replace('–', '-').replace('—', '-').replace('’', "'").split())


def numeric_inventory(text):
    text = re.sub(r'\bpart\s+\d+\s*:', '', norm(text))
    return set(re.findall(r'(?<![a-z])\d+(?:[.,]\d+)*(?:\s*%)?', text))


def tokens(text):
    return set(re.findall(r'[a-z]+', norm(text)))


def card_spans(text):
    pattern = re.compile(r'\b(?:Business\s+)?(?:Platinum|Rewards)\s+Visa\b', re.I)
    matches = list(pattern.finditer(text))
    return [(norm(m[0]), norm(text[m.start(): matches[i+1].start() if i+1<len(matches) else len(text)]))
            for i, m in enumerate(matches)]


def claim_relation(atom, text):
    """Return explicit, inspectable relation checks for a requested atomic slot."""
    t = norm(text)
    kind = atom['kind']
    if kind == 'routing':
        number = re.escape(atom['value'])
        return bool(re.search(r'(?:routing(?: number)?|aba(?: number| identifier)?)\D{0,80}'+number, t)
                    or re.search(number+r'\D{0,40}(?:routing|aba)', t))
    if kind == 'setup':
        # Three actual transitions, with the correct payroll counterparty,
        # rather than a source sentence that merely says "three steps".
        actor = re.escape(norm(atom['payroll']))
        obtain = re.search(r'(?:obtain|request|ask|collect|get|receive).{0,70}(?:packet|form|authorization|enrollment).{0,90}'+actor, t)
        enter = re.search(r'(?:enter|fill|complete|provide).{0,70}(?:routing|aba).{0,70}account', t)
        send = re.search(r'(?:return|submit|send|deliver).{0,35}signed.{0,35}(?:packet|form|authorization).{0,90}'+actor, t)
        return bool(obtain and enter and send)
    if kind == 'use':
        return bool(re.search(r'direct deposit.{0,60}(?:supports|used|use|receive|receiving|for).{0,70}(?:wages|salary|payroll)', t)
                    and re.search(r'(?:recurring\s+)?pension|retirement', t)
                    and norm(atom['payroll']) in t)
    if kind == 'timing':
        return bool(re.search(r'(?:funds|deposit).{0,50}availab.{0,40}(?:scheduled )?payday', t)
                    and re.search(r'(?:ask|contact|consult).{0,40}'+re.escape(norm(atom['payroll'])), t)
                    and re.search(r'absent|missing|not received', t))
    if kind == 'benefits':
        return bool(re.search(r'personal.{0,40}card.{0,70}purchase protection', t)
                    and re.search(r'transaction alerts|transaction notifications', t))
    if kind == 'card_rate':
        # A rate must occur in its own labelled product span. A matching number
        # under Business Rewards cannot fulfill personal Rewards or Platinum.
        family = norm(atom['family'])
        for label, span in card_spans(text):
            if label == family and all(norm(v) in span for v in atom['values']):
                if re.search(r'\b(?:apr|annual percentage rate)\b', span) and norm(atom['phase']) in span:
                    return True
        return False
    if kind in ('heloc_rate', 'heloc_intro'):
        value = re.escape(norm(atom['value']))
        label = r'(?:heloc|home equity line(?: of credit)?)'
        phase = r'(?:standard|variable|ongoing)' if kind == 'heloc_rate' else r'introductory|intro|offer'
        # Preserve relation and phase; a number merely present in a source
        # or a neighboring fixed-home-equity clause does not satisfy this.
        return bool(re.search(label+r'.{0,160}(?:'+phase+r').{0,80}'+value, t)
                    or re.search(label+r'.{0,160}'+value+r'.{0,50}(?:'+phase+r')', t)
                    or kind == 'heloc_intro' and re.search(r'(?:introductory|intro).{0,70}'+value, t)
                    and re.search(label, t))
    if kind == 'effective_date':
        return bool(re.search(r'effective.{0,35}'+re.escape(atom['value']), t)
                    and re.search(r'heloc|home equity line', t))
    if kind in ('credit', 'cltv'):
        value = re.escape(norm(atom['value']))
        label = r'credit[- ]score|credit score|score' if kind == 'credit' else r'cltv|combined loan[- ]to[- ]value(?: ratio)?'
        ops = {'>=': r'at least|not less than|no less than|>=|≥|minimum(?: of)?',
               '>': r'greater than|above|more than|>|exceeds?',
               '<=': r'no more than|not more than|at most|<=|≤|maximum(?: of)?',
               '<': r'less than|below|<'}
        right = bool(re.search(r'(?:'+label+r').{0,45}(?:'+ops[atom['operator']]+r')\s*'+value, t))
        # Word operators are checked separately from symbols to avoid a '<'
        # matching the prefix of '<='.
        if atom['operator'] in ('>', '<'):
            inclusive = ops['>='] if kind == 'credit' else ops['<=']
            if re.search(r'(?:'+label+r').{0,45}(?:'+inclusive+r')\s*'+value, t):
                return False
        if atom['operator'] == '>=' and re.search(r'(?:'+label+r').{0,45}(?:greater than|above|more than)\s*'+value, t):
            return False
        if atom['operator'] == '<=' and re.search(r'(?:'+label+r').{0,45}(?:less than|below)\s*'+value, t):
            return False
        return right and bool(re.search(r'heloc|home equity line', t))
    if kind == 'card_intro':
        intro = re.escape(norm(atom['value']))
        return bool(re.search(r'(?<!business )platinum visa.{0,80}'+intro+r'.{0,60}introductory', t)
                    and re.search(re.escape(atom['duration'])+r' months.{0,45}(?:after|from).{0,25}first balance transfer', t)
                    and re.search(r'(?:post|posting).{0,60}first\s+'+re.escape(atom['window'])+r'\s+days.{0,60}(?:opening|opened|open)', t))
    raise AssertionError('Unspecified oracle kind: '+kind)


# Ordinary rendering and refusal vocabulary. New unsupported substantive nouns
# are audited as residual body terms instead of silently accepting an arbitrary
# sentence because it happens to include the expected numbers.
NEUTRAL = tokens("""the a an and or either both all of for to in on from with by as is are was were be has have
this that these those it its their your our you I me my we bank institution credit union published stated
standard purchase variable ongoing annual percentage APR rate rates home equity line HELOC credit card cards must
personal business commercial consumer information condition conditions qualification qualifications
require requires required requirement requirements applies applicable when while only current introductory
intro offer offers eligible eligibility minimum maximum score combined loan value CLTV ratio at least
no not more less than greater above below inclusive exclusive threshold thresholds after before first
part known unknown missing absent available snapshot snapshots source sources selected website public
cannot could unable confirm verify know don't do doesn't does not publish published contact please details
specific requested individually underwriting approval approved final depend depends qualified qualify
private account authenticated online mobile banking use number identifier ABA routing needed used needs
direct deposit setup procedure steps enrollment enrolled enroll obtain request ask collect get receive
packet form authorization enter fill complete provide return submit send deliver signed supports wages
salary payroll receiving recurring pension retirement payments funds become scheduled payday transaction
alerts notifications benefits include purchase protection expired expires earlier period window timing
transfers transfer post posted posting within opening opened months days applies applies follows outside
now also then respectively following without excluding omit skip quote quotes explain describe give list
state standard conditions limitation limitations unavailable stated source rule predicates lower upper bound effective publication date dates low s supplied detail listed matching named service amount limit
and credit score combined loan to value only is at no more than at least standard APR variable""")


def audit(case, answer):
    expected = case['expected']
    payload = dataclasses.asdict(answer) if dataclasses.is_dataclass(answer) else answer
    errors, checks = [], []
    if not isinstance(payload, dict) or set(payload) != {'text', 'sources', 'confident', 'conflict_note'}:
        return {'pass': False, 'errors': ['Answer schema is not the public complete dictionary'], 'checks': []}
    text = payload['text']
    if not isinstance(text, str) or not isinstance(payload['confident'], bool) or not isinstance(payload['sources'], list):
        return {'pass': False, 'errors': ['Invalid public Answer field types'], 'checks': []}
    if payload['conflict_note'] is not None:
        errors.append('Unexpected conflict_note in an unambiguous invented fixture')
    if payload['confident'] != expected['confident']:
        errors.append('Confidence does not match complete/unknown request contract')
    pages = {(s['snapshot_id'], p['url']): p for s in case['snapshots'] for p in s['pages']}
    validated_sources = []
    for source in payload['sources']:
        if not isinstance(source, dict) or set(source) != {'url', 'snapshot_id', 'quote'}:
            errors.append('Invalid Source schema'); continue
        p = pages.get((source['snapshot_id'], source['url']))
        if not p:
            errors.append('Source is not a visible invented observation'); continue
        quote = source['quote']
        if quote is not None and (not isinstance(quote, str) or quote not in p['markdown']):
            errors.append('Source quote is not a real raw span'); continue
        validated_sources.append((source, p))
    for atom in expected['atoms']:
        relation = claim_relation(atom, text)
        supporting = [(s, p) for s, p in validated_sources
                      if s['url']==atom['url'] and s['snapshot_id']==atom['snapshot_id']
                      and all(norm(raw) in norm(p['markdown']) for raw in atom['support'])]
        # Source.quote is optional in the public API and one Source can cite a
        # page with multiple rows. Independently prove each body claim from its
        # real same-observation row/section; a legal quote alone is insufficient.
        raw_evidence = bool(supporting)
        if atom['kind']=='card_rate' and supporting:
            family = re.escape(atom['family'])
            local = re.search(r'^##\s+'+family+r'\s*$([\s\S]*?)(?=^##\s|\Z)', supporting[0][1]['markdown'], re.M)
            raw_evidence = raw_evidence and bool(local and all(v in local[1] for v in atom['values']))
        if atom['kind'] in ('credit', 'cltv') and supporting:
            section = supporting[0][1]['markdown'].split('\n## Fixed Home Equity Loan')[0]
            raw_evidence = raw_evidence and all(norm(v) in norm(section) for v in atom['support']) and claim_relation(atom, section)
        checks.append({'kind': atom['kind'], 'family': atom.get('family'), 'body_relation': relation,
                       'bound_source': bool(supporting), 'raw_evidence': raw_evidence})
        if not relation:
            errors.append('Missing/incorrect body relation for '+atom.get('family', atom['kind']))
        if not raw_evidence:
            errors.append('Missing bound raw evidence for '+atom.get('family', atom['kind']))
    if expected['conjunction'] and len([a for a in expected['atoms'] if a['kind'] in ('credit','cltv')])==2:
        t = norm(text)
        conditions = re.search(r'(?:credit[- ]score|credit score|score|cltv|combined loan[- ]to[- ]value).{0,260}', t)
        clause = conditions[0] if conditions else ''
        join = expected['conjunction']
        if join=='AND' and (not re.search(r'\band\b|\bboth\b|\bAND\b', clause) or re.search(r'\bor\b|\beither\b', clause)):
            errors.append('Credit-score/CLTV AND relation is incomplete or reversed')
        if join=='OR' and (not re.search(r'\bor\b|\beither\b', clause) or re.search(r'\bboth\b', clause)):
            errors.append('Credit-score/CLTV OR relation is incomplete or reversed')
    if expected['unknowns']:
        t = norm(text)
        if not re.search(r"don't know|do not know|cannot|can't|not publish|not stated|unknown|unable|missing|no .*published|not available|no .*snapshot|expired", t):
            errors.append('Unknown requested slot is not explicitly stated in the body')
        if expected['atoms']:
            # An unknown must be scoped; a global refusal after known facts does
            # not certify which requested field remains unresolved.
            for unknown in expected['unknowns']:
                words = tokens(unknown)-{'current','apr'}
                if words and not words & tokens(text):
                    errors.append('Unknown field is not identified: '+unknown)
    permitted_numbers = set()
    for atom in expected['atoms']:
        for value in ([atom['value']] if 'value' in atom else atom.get('values', [])):
            permitted_numbers |= numeric_inventory(value)
        for field in ('duration', 'window'):
            if field in atom:
                permitted_numbers |= numeric_inventory(atom[field])
    for day in expected['allowed_dates']:
        permitted_numbers |= numeric_inventory(day)
    extra_numbers = sorted(numeric_inventory(text)-permitted_numbers)
    if extra_numbers:
        errors.append('Extra/excluded/misbound body numbers: '+', '.join(extra_numbers))
    requested_identities = {(a['kind'], a.get('family')) for a in expected['atoms']}
    excluded_relations = set()
    for atom in expected['universe']:
        identity = (atom['kind'], atom.get('family'))
        if identity not in requested_identities and claim_relation(atom, text):
            excluded_relations.add(atom.get('family', atom['kind']))
    if excluded_relations:
        errors.append('Extra/excluded semantic slot claims in body: '+', '.join(sorted(excluded_relations)))
    requested_families = {norm(a['family']) for a in expected['atoms'] if a['kind']=='card_rate'}
    if any(a['kind']=='card_intro' for a in expected['atoms']):
        requested_families.add('platinum visa')
    for label, span in card_spans(text):
        # Unknown product mention is allowed only in an explicit refusal, not
        # with an unrelated published rate taken from another requested slot.
        if label not in requested_families and re.search(r'\d(?:[.,]\d+)*\s*%', span):
            errors.append('Extra card family claim in body: '+label)
    actors = {a['actor'] for a in expected['universe']}
    if 'Dupaco' not in actors and re.search(r'\bdupaco\b', norm(text)):
        errors.append('Body substituted a different institution for source-invented actor')
    source_terms = set().union(*(tokens(' '.join(a['support'])) | tokens(a.get('family','')) | tokens(a['actor'])
                                 | tokens(a.get('payroll','')) for a in expected['atoms'])) if expected['atoms'] else set()
    allowed_terms = source_terms | NEUTRAL | tokens(case['question'])
    leftovers = sorted(tokens(text)-allowed_terms)
    if leftovers:
        errors.append('Unmapped substantive body terms require evidence: '+', '.join(leftovers))
    return {'pass': not errors, 'errors': errors, 'checks': checks,
            'numeric_inventory': sorted(numeric_inventory(text)), 'unmapped_body_terms': leftovers,
            'extra_semantic_slot_claims': sorted(excluded_relations),
            'source_count': len(validated_sources), 'requested_atom_count': len(expected['atoms']),
            'complete': not errors and expected['confident'],
            'honest_partial': not errors and not expected['confident'],
            'incorrect_confident': bool(errors and payload['confident'])}


def execute_suite(runtime, controls):
    module = load_runtime(runtime)
    results = []
    for case in controls['cases']:
        knowledge = module.build()
        for source in case['snapshots']:
            knowledge.ingest(NS(snapshot_id=source['snapshot_id'], taken_on=source['taken_on'],
                                pages=[NS(**p) for p in source['pages']]))
        try:
            answer = knowledge.answer(case['question'], case['as_of'])
            payload = dataclasses.asdict(answer)
            result = audit(case, payload)
        except Exception as exc:
            payload = None
            result = {'pass': False, 'errors': [type(exc).__name__+': '+str(exc)], 'checks': [],
                      'complete': False, 'honest_partial': False, 'incorrect_confident': False}
        results.append({'id': case['id'], 'group': case['group'], 'relation': case['relation'],
                        'question': case['question'], 'as_of': case['as_of'],
                        'request_contract': case['request_contract'], 'answer': payload, 'audit': result})
    return results


def summary(results):
    return {'cases': len(results), 'pass': sum(r['audit']['pass'] for r in results),
            'fail': sum(not r['audit']['pass'] for r in results),
            'complete': sum(r['audit'].get('complete', False) for r in results),
            'honest_partial': sum(r['audit'].get('honest_partial', False) for r in results),
            'incorrect_confident': sum(r['audit'].get('incorrect_confident', False) for r in results)}


class RequestEvidenceDeveloper(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controls = json.loads((ROOT/'developer_controls.json').read_text())
        cls.results = execute_suite(os.environ['REQUEST_EVIDENCE_RUNTIME'], cls.controls)

    def test_complete_answer_evidence_contracts(self):
        for result in self.results:
            with self.subTest(case=result['id'], question=result['question']):
                self.assertTrue(result['audit']['pass'], result['audit']['errors'])

    def test_mutation_pair_and_fixture_freeze_integrity(self):
        for group in self.controls['groups']:
            relations = {c['relation'] for c in self.controls['cases'] if c['group']==group['id']}
            self.assertEqual(relations, set(group['required_relations']))
        # Input fixtures are owned snapshots; response audit never mutates them.
        self.assertEqual(self.controls, json.loads((ROOT/'developer_controls.json').read_text()))

    def test_public_answer_and_input_ownership(self):
        module = load_runtime(os.environ['REQUEST_EVIDENCE_RUNTIME'])
        c = next(c for c in self.controls['cases'] if c['id']=='developer-routing-private-positive')
        source = c['snapshots'][-1]
        pages = [NS(**p) for p in source['pages']]
        snapshot = NS(snapshot_id=source['snapshot_id'], taken_on=source['taken_on'], pages=pages)
        k = module.build(); k.ingest(snapshot)
        before = dataclasses.asdict(k.answer(c['question']))
        returned = k.answer(c['question']); returned.sources.clear()
        next(p for p in pages if p.url.endswith('/contact')).markdown = '# Mutated caller-owned input\n'
        self.assertEqual(dataclasses.asdict(k.answer(c['question'])), before)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--capture-baseline', action='store_true')
    parser.add_argument('--runtime', default=os.environ.get('REQUEST_EVIDENCE_RUNTIME'))
    args, remaining = parser.parse_known_args()
    if not args.runtime:
        parser.error('REQUEST_EVIDENCE_RUNTIME or --runtime is required')
    os.environ['REQUEST_EVIDENCE_RUNTIME'] = str(Path(args.runtime).resolve())
    if args.capture_baseline:
        actual_hash = canonical_hash(args.runtime)
        if actual_hash != BASELINE:
            raise SystemExit('Baseline capture requires exact2d6; observed '+actual_hash)
        target = ROOT/'BASELINE_FULL_ANSWERS.json'
        if target.exists():
            raise SystemExit('Refusing to overwrite frozen baseline full answers')
        controls = json.loads((ROOT/'developer_controls.json').read_text())
        results = execute_suite(args.runtime, controls)
        data = {'runtime_canonical_sha256': actual_hash, 'synthetic_only': True, 'lane': 'developer',
                'fixture_sha256': hashlib.sha256((ROOT/'developer_controls.json').read_bytes()).hexdigest(),
                'summary': summary(results), 'results': results}
        target.write_text(json.dumps(data, indent=2)+'\n')
        print(json.dumps(data['summary']))
    else:
        unittest.main(argv=[sys.argv[0]]+remaining)


if __name__ == '__main__':
    main()
