"""One-omission historical service-fee evidence; no rate-authority composition.

Original-1 is an optional fee-row selector. Failure preserves Parent. Source
values are parsed only from complete unconditional money rows on one older fee
document. Its public answer/ingest/conflicts and rate winners are never called.
"""
from datetime import date
import importlib.util
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit


_REQUEST_UNSAFE = re.compile(
    r'\b(?:my|me|i|your|actual|charged|billed|paid|refund|will|would|should|private|'
    r'account-specific|personal|business|commercial|members?|nonmembers?|eligib\w*|'
    r'qualif\w*|if|when|unless|except|without|not|no|after|before|already|waiv\w*|'
    r'latest|current|snapshot|crawl|page|source|according|only|exactly|'
    r'and|or|plus|versus|compare|comparison|both|all|each|every|separately|'
    r'history|historical|previously|formerly|changed?|changes|increased|decreased|'
    r'used to|track|across|between|timeline|apr|apy|rates?|interest|dividend|yield|'
    r'loan|mortgage|credit union|bank|institution|cu)\b|n[\x27’]t|[$%\d;\n]|https?://', re.I)
_SOURCE_CONDITIONAL = re.compile(
    r'\b(?:if|unless|except|without|only|members?|non[- ]?members?|business|commercial|'
    r'personal|eligib\w*|qualif\w*|waiv\w*|may|might|varies|variable|up to|minimum|'
    r'maximum|after|before|first|additional|per|each|tax\w*|promotion\w*|special|'
    r'expired|ended|discontinued|scheduled|introductory)\b', re.I)
_IGNORED = set('a an the what is how much does to for of published base standard fee fees '
               'cost costs charge charges please'.split())
_MONEY = r'\$\s*\d+(?:,\d{3})*(?:\.\d{1,2})?'
_DATE = r'(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|[A-Za-z]+\.?\s+\d{1,2},?\s+\d{4})'
_TIME_MARKER = re.compile(
    r'\b(effective(?:\s+as of)?|valid from|valid until|valid through|starts?|begins?|'
    r'expires?|ends?|available from|available through)\b\s*(?:on\s+)?', re.I)
_FEE_HEADING = re.compile(
    r'(?:(?:rate|rates)\s+and\s+)?(?:(?:service|miscellaneous|published|base|standard)\s+)?'
    r'(?:fees?|fee\s+schedule|service\s+charges?)(?:\s+schedule)?', re.I)
_LABEL = re.compile(r"[A-Za-z][A-Za-z'-]*(?:\s+[A-Za-z][A-Za-z'-]*){1,7}")
_LABEL_RESTRICTION = re.compile(
    r'\b(?:for|from|within|residents?|residency|exclusive\w*|restricted|limited|'
    r'available|availability|requires?|required|approved|permitted|customers?|'
    r'clients?|holders?|geographic|county|counties|state|states|country|countries)\b', re.I)


def _source_text(page):
    # Markdown includes every heading. Keep Page.title as a separate supplied
    # surface rather than treating it only as a document-classification hint.
    return str(page.title) + '\n' + page.markdown


def _without_validity(text, donor):
    pieces, end = [], 0
    for marker in _TIME_MARKER.finditer(text):
        match = re.match(_DATE, text[marker.end():])
        if not match or not _parse_day(match[0], donor):
            return None
        pieces.append(text[end:marker.start()])
        end = marker.end() + match.end()
    pieces.append(text[end:])
    return ' '.join(pieces).strip(' .,:;-')


def _unconditional_label(label):
    return bool(_LABEL.fullmatch(label) and not _SOURCE_CONDITIONAL.search(label)
                and not _LABEL_RESTRICTION.search(label))


def _source_grammar(page, donor):
    """Reject every unrecognized source line instead of discarding qualifiers.

    Understood forms are fee-document titles/headings, explicit absolute
    validity metadata, simple money fee statements, and two-column fee tables.
    Unknown restriction/availability prose is never interpreted as eligibility.
    """
    title = _without_validity(donor.clean(page.title), donor)
    if title is None or not _FEE_HEADING.fullmatch(title):
        return False
    in_table, monetary_rows = False, 0
    for raw in page.markdown.splitlines():
        if not raw.strip():
            continue
        if raw.lstrip().startswith('|'):
            cells = [donor.clean(c) for c in raw.strip().strip('|').split('|')]
            if len(cells) != 2:
                return False
            if cells[0].lower() in {'service', 'item', 'description'} and cells[1].lower() in {'fee', 'base fee', 'service fee', 'charge'}:
                in_table = True
                continue
            if in_table and all(re.fullmatch(r':?-{3,}:?', c) for c in cells):
                continue
            if not in_table or not _unconditional_label(cells[0]) or not re.fullmatch(_MONEY, cells[1]):
                return False
            monetary_rows += 1
            continue
        in_table = False
        heading = raw.lstrip().startswith('#')
        text = donor.clean(raw.lstrip('# ').strip() if heading else raw)
        remainder = _without_validity(text, donor)
        if remainder is None:
            return False
        if not remainder or _FEE_HEADING.fullmatch(remainder):
            continue
        if heading:
            return False
        match = re.fullmatch(r'(.{3,110}?)\s+(?:fees?|charges?)\s*:\s*(' + _MONEY + r')\.?', text, re.I)
        if not match or not _unconditional_label(match[1]):
            return False
        monetary_rows += 1
    return monetary_rows > 0


def _helper():
    name = '_fee_compatibility_original1'
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parent / 'original1_runtime' / 'solution.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def _terms(text, donor):
    # No entity expansion. Use donor's language normalization within the fee lane.
    return set(donor.tokens(text)) - _IGNORED


def _fee_document(page):
    labels = page.title + ' ' + urlsplit(page.url).path.replace('-', ' ').replace('_', ' ')
    headings = ' '.join(line.lstrip('# ').strip() for line in page.markdown.splitlines()
                        if line.lstrip().startswith('#'))
    return bool(re.search(r'\bfees?\b|\bservice charges?\b', labels + ' ' + headings, re.I))


def _current_fee_evidence(ctx):
    # Conservative: any newer fee-bearing text blocks borrowing, including a
    # renamed or empty fee schedule and fee statements on non-schedule pages.
    return any(_fee_document(p) or re.search(r'\bfees?\b|\bservice charges?\b', p.markdown, re.I)
               for p in ctx.pages)


def _parse_day(raw, donor):
    raw = raw.rstrip('.').strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw):
        return date.fromisoformat(raw).isoformat()
    if '/' in raw:
        month, day, year = map(int, raw.split('/'))
        return date(year, month, day).isoformat()
    found = donor.dates(raw)
    return found[0][0] if len(found) == 1 else None


def _eligible_time(page, older, cutoff, donor):
    fetched = str(getattr(page, 'fetched_at', ''))[:10]
    if not fetched or date.fromisoformat(fetched).isoformat() > older.date[:10]:
        return False
    text = donor.clean(_source_text(page))
    starts, ends = [], []
    for marker in _TIME_MARKER.finditer(text):
        match = re.match(_DATE, text[marker.end():])
        if not match:
            return False
        day = _parse_day(match[0], donor)
        if not day:
            return False
        if re.search(r'until|through|expire|end', marker[1], re.I):
            ends.append(day)
        else:
            starts.append(day)
    # Validity is checked at the containing snapshot observation, independently
    # of the earlier page fetch timestamp. Future fetches remain unsupported.
    if len(set(starts)) > 1 or len(set(ends)) > 1:
        return False
    if starts and starts[0] > older.date[:10]:
        return False
    if ends and ends[0] < cutoff:
        return False
    return True


class FeeFallback:
    def __init__(self):
        self._cache = {}

    def clear(self):
        self._cache.clear()

    def _rows(self, ctx, page, donor):
        key = (ctx.sid, ctx.date, page.url, page.title, page.markdown)
        if key not in self._cache:
            rows, table_header = [], False
            for raw in page.markdown.splitlines():
                text = donor.clean(raw)
                if raw.lstrip().startswith('|'):
                    cells = [donor.clean(c) for c in raw.strip().strip('|').split('|')]
                    if len(cells) != 2:
                        table_header = False
                        continue
                    if cells[1].lower() in {'fee', 'base fee', 'service fee', 'charge'}:
                        table_header = True
                        continue
                    if all(re.fullmatch(r':?-{3,}:?', c) for c in cells):
                        continue
                    if not table_header or not re.fullmatch(_MONEY, cells[1]):
                        continue
                    label, amount = cells
                else:
                    table_header = False
                    match = re.fullmatch(r'(.{3,110}?)\s+(?:fees?|charges?)\s*:\s*(' + _MONEY + r')\.?', text, re.I)
                    if not match:
                        continue
                    label, amount = match[1], match[2]
                if _SOURCE_CONDITIONAL.search(label) or len(_terms(label, donor)) < 2:
                    continue
                # A complete raw row is retained; no synthesized source URL or quote.
                rows.append(donor.Row('fee', label, '', {'fee': amount}, page.url, ctx.sid,
                                      ctx.date, getattr(page, 'fetched_at', ctx.date), '', raw, 0))
            self._cache[key] = rows
        return self._cache[key]

    def answer(self, contexts, ctx, q, as_of=None):
        if _REQUEST_UNSAFE.search(q):
            return None
        if not re.match(r'^(?:please\s+)?(?:what is|what\x27s|how much is|how much does)\b', q, re.I):
            return None
        if not re.search(r'\b(?:fees?|charges?|costs?)\b|^how much\b', q, re.I):
            return None
        if _current_fee_evidence(ctx):
            return None
        try:
            donor = _helper()
            subject = _terms(q, donor)
            if len(subject) < 2:
                return None
            # Original-1's bounded bridge: only the immediately prior full
            # snapshot, only one omission, and no more than 90 observed days.
            prior = [c for c in contexts if c.date < ctx.date]
            if not prior:
                return None
            latest_date = max(c.date for c in prior)
            candidates = [c for c in prior if c.date == latest_date]
            if len(candidates) != 1:
                return None
            older = candidates[0]
            cutoff = str(as_of or ctx.date)[:10]
            age = (date.fromisoformat(cutoff) - date.fromisoformat(older.date[:10])).days
            if not 0 <= age <= 90:
                return None
            pages = [p for p in older.pages if _fee_document(p)]
            if len(pages) != 1:
                return None
            page = pages[0]
            if ctx.pages and urlsplit(page.url).netloc not in {urlsplit(p.url).netloc for p in ctx.pages}:
                return None
            if not _source_grammar(page, donor):
                return None
            if not _eligible_time(page, older, cutoff, donor):
                return None
            rows = self._rows(older, page, donor)
            exact = [r for r in rows if _terms(r.entity, donor) == subject]
            if len(exact) != 1:
                return None
            # Fee-only selector: no registry, rate winner, authority comparison,
            # answer dispatcher, history carry or conflict list from Original-1.
            view = SimpleNamespace(family_rows={'fee': exact})
            selected = donor.Knowledge._select_rows(donor.Knowledge(), view, q, 'fee')
            if len(selected) != 1 or selected[0] is not exact[0]:
                return None
            row = selected[0]
            if row.quote not in page.markdown:
                return None
            text = ('The most recently available published base fee for ' + row.entity +
                    ' was ' + row.cells['fee'] + ', contained in the snapshot dated ' + older.date[:10] +
                    '. This published fee does not determine a particular customer\x27s charge.')
            return older.reply(text, [page], quote=row.quote)
        except Exception:
            # Weak-dependency or unsupported-source failures preserve Parent.
            return None
