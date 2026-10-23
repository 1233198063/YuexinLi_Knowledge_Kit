"""Loan and Visa answers extracted solely from the selected website snapshot.

Tables retain their product, loan-purpose, amount, model-year and term qualifiers.
Product pages and the official rate sheet beat incidental calculator/promo copies;
within those authoritative pages a later effective date wins.
"""
import re
from datetime import date
from urllib.parse import urlsplit

from common import clean, term_months, requested_metrics
from evidence import currently_valid,explicit_effective_date


_PATHS = {
    'auto': ['/personal/loans/auto-motorcycle-loans', '/personal/loans/auto-loans'],
    'mortgage_purchase': ['/personal/loans/home-loans'],
    'mortgage_refinance': ['/personal/loans/home-loans'],
    'mortgage_relief': ['/personal/loans/home-loans'],
    'equity_refinance': ['/personal/loans/home-equity', '/personal/loans/home-loans'],
    'heloc': ['/personal/loans/home-equity', '/personal/loans/home-equity-line-of-credit'],
    'equity_fixed': ['/personal/loans/home-equity', '/personal/loans/home-equity-loan'],
    'improvement': ['/personal/loans/home-improvement-loan', '/personal/loans/home-loans'],
    'personal': ['/personal/loans/personal-loans', '/personal/loans/debt-consolidation'],
    'boat': ['/personal/loans/recreational-loans', '/personal/loans/boat-rv-loans'],
    'atv': ['/personal/loans/recreational-loans', '/personal/loans/boat-rv-loans'],
    'Platinum Visa': ['/personal/credit-cards'],
    'Rewards Visa': ['/personal/credit-cards'],
    'Business Platinum Visa': ['/business/credit-cards', '/business/rates'],
    'Business Rewards Visa': ['/business/credit-cards', '/business/rates'],
}
_PERCENT = re.compile(r'\d+(?:\.\d+)?\s*%')
_TABLE = re.compile(r'(?m)^\|[^\n]*(?:\n\|[^\n]*)+')


def _path(page):
    return urlsplit(page.url).path.rstrip('/')


def _percents(text):
    return [re.sub(r'\s+', '', m.group()) for m in _PERCENT.finditer(text)]


def _range(text):
    p = _percents(text)
    return '–'.join(p[:2]) if p else None


def _effective(text):
    return explicit_effective_date(clean(text))


def _amount_bounds(text):
    # Only dollar amounts are accepted here; a mortgage term is never a balance.
    vals = re.findall(r'\$\s*(\d[\d,]*(?:\.\d+)?)', text)
    if not vals:
        return None
    nums = [float(v.replace(',', '')) for v in vals]
    if len(nums) > 1:
        return min(nums), max(nums)
    # Amount ranges in table cells often omit the second dollar sign.
    tail = re.search(r'\$\s*\d[\d,]*(?:\.\d+)?\s*[-–—]\s*(\d[\d,]*(?:\.\d+)?)', text)
    if tail:
        return nums[0], float(tail[1].replace(',', ''))
    if '+' in text or re.search(r'or\s+(?:more|greater)|and\s+(?:up|over)', text, re.I):
        return nums[0], float('inf')
    return 0, nums[0]


def _question_amount(q):
    m = re.search(r'\$\s*(\d[\d,]*(?:\.\d+)?)\s*([km])?\b', q, re.I)
    if not m:
        m = re.search(r'\b(\d[\d,]*(?:\.\d+)?)\s*([km])\b', q, re.I)
    if not m:
        m = re.search(r'\b(\d[\d,]*(?:\.\d+)?)\s+(?:dollars|dollar)\b', q, re.I)
        if m:
            return float(m[1].replace(',', ''))
        return None
    return float(m[1].replace(',', '')) * {'k': 1000, 'm': 1000000, None: 1, '': 1}.get((m[2] or '').lower(), 1)


def _years(text):
    # Both 2024-27 and the reverse-order 2026-23 ATV labels occur on the site.
    m = re.search(r'\b((?:19|20)\d{2})\s*[-–—]\s*(\d{2,4})\b', text)
    if m:
        lo, hi = int(m[1]), int(m[2])
        if hi < 100:
            hi += (lo // 100) * 100
        return min(lo, hi), max(lo, hi)
    m = re.search(r'\b((?:19|20)\d{2})\b', text)
    if m:
        yr = int(m[1])
        return (0, yr) if re.search(r'older|earlier', text, re.I) else (yr, yr)
    return None


def _question_year(q):
    years = _question_years(q)
    return years[0] if years else None


def _question_years(q):
    # A date year is not the vehicle's model year. Strip named dates with or
    # without a day, numeric dates, and explicit "as of YEAR" qualifiers.
    months = r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)'
    q = re.sub(r'\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}/\d{1,2}/\d{4}\b', '', q)
    q = re.sub(r'\b' + months + r'\.?\s+(?:\d{1,2}(?:st|nd|rd|th)?[\s,]+)?(?:19|20)\d{2}\b', '', q, flags=re.I)
    q = re.sub(r'\b\d{1,2}(?:st|nd|rd|th)?\s+' + months + r'\.?[\s,]+(?:19|20)\d{2}\b', '', q, flags=re.I)
    q = re.sub(r'\b(?:as of|on|in|during|since|before|after)\s+(?:19|20)\d{2}\b', '', q, flags=re.I)
    years = [int(m[1]) for m in re.finditer(r'(?<!\$)\b((?:19|20)\d{2})\b',q)]
    for m in re.finditer(r'\b(?:19|20)\d{2}\s*[-–—]\s*\d{2,4}\b',q):
        bounds = _years(m[0])
        if bounds and bounds[1]-bounds[0] <= 30:
            years.extend(range(bounds[0],bounds[1]+1))
    return list(dict.fromkeys(years))


def _term(q):
    n = term_months(q)
    if n is not None:
        return n
    words = {'two': 2, 'three': 3, 'four': 4, 'five': 5, 'seven': 7,
             'eight': 8, 'fifteen': 15, 'twenty': 20, 'forty-eight': 48,
             'seventy-two': 72, 'eighty-four': 84, 'thirty-six': 36,
             'one hundred twenty': 120}
    for word, value in words.items():
        m = re.search(r'\b' + word + r'\s*[- ]?\s*(years?|yrs?|months?|mos?)\b', q)
        if m:
            return value * (12 if m[1].startswith(('year', 'yr')) else 1)
    return None


def _terms(q):
    """All requested terms, so a comparison does not silently drop its second term."""
    found = []
    unit = r'\s*[- ]?\s*(years?|yrs?|months?|mos?)\b'
    for m in re.finditer(r'\b(\d+)' + unit, q):
        found.append((m.start(), int(m[1]) * (12 if m[2].startswith(('year', 'yr')) else 1)))
    # Suspended units: "48-, 60-, 72-, and 84-month" and "60 and 120 months".
    for m in re.finditer(r'\b((?:\d+\s*-?\s*,\s*)+)(?:and\s+)?(\d+)' + unit, q):
        scale = 12 if m[3].startswith(('year', 'yr')) else 1
        for value in re.findall(r'\d+', m[1]) + [m[2]]:
            found.append((m.start(), int(value)*scale))
    for m in re.finditer(r'\b(\d+)\s*-?\s*(?:and|or)\s+(\d+)' + unit, q):
        scale = 12 if m[3].startswith(('year', 'yr')) else 1
        found.extend([(m.start(), int(m[1])*scale), (m.start(), int(m[2])*scale)])
    words = {'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7,
             'eight': 8, 'ten': 10, 'twelve': 12, 'fifteen': 15, 'twenty': 20,
             'thirty': 30, 'thirty-six': 36, 'forty-eight': 48, 'sixty': 60,
             'seventy-two': 72, 'eighty-four': 84, 'one hundred twenty': 120}
    for word, value in words.items():
        for m in re.finditer(r'(?<![\w-])' + re.escape(word) + unit, q):
            found.append((m.start(), value * (12 if m[1].startswith(('year', 'yr')) else 1)))
    if not found:
        first = _term(q)
        return [first] if first is not None else []
    return list(dict.fromkeys(value for _, value in sorted(found)))


def _term_span(q):
    m = re.search(r'\b(?:from|between)\s+(\d+)\s*(?:(months?|years?)\s*)?(?:through|to|and)\s+(\d+)\s*[- ]?\s*(months?|years?)\b', q)
    if m:
        scale = 12 if m[4].startswith('year') else 1
        return min(int(m[1]),int(m[3]))*scale, max(int(m[1]),int(m[3]))*scale
    return None


def _money(text):
    m = re.search(r'\$\s*(\d[\d,]*(?:\.\d+)?)', text or '')
    if m:
        return '$' + format(float(m[1].replace(',', '')), ',.2f')
    return None


def _date_label(iso):
    if not iso:
        return ''
    parsed = date.fromisoformat(iso)
    return parsed.strftime('%B ') + str(parsed.day) + parsed.strftime(', %Y') + ' (' + iso + ')'


def _amounts(q):
    amounts = []
    for m in re.finditer(r'\$\s*\d[\d,]*(?:\.\d+)?\s*[km]?\b|\b\d[\d,]*(?:\.\d+)?\s*[km]\b', q, re.I):
        amount = _question_amount(m[0])
        if amount is not None and amount not in amounts:
            amounts.append(amount)
    if not amounts:
        amount = _question_amount(q)
        if amount is not None:
            amounts.append(amount)
    return amounts


def _table_family(header, before, page, rows):
    h, b, p = ' '.join(header).lower(), before.lower(), _path(page)
    first = ' '.join(rows[0]).lower() if rows else ''
    context = b[-650:] + ' ' + h
    if 'points' in h and 'apr' in h:
        if 'refinance:' in first:
            if re.search(r'cash.?out refinance|home equity refinance', context):
                return 'equity_refinance'
            return 'mortgage_refinance'
        return 'mortgage_purchase'
    if len(header) == 2 and re.search(r'card|visa|apr|annual percentage rate', h):
        card_names = re.findall(r'business platinum visa|business rewards visa|platinum visa|rewards visa', context + first)
        if card_names:
            return {'business platinum visa': 'Business Platinum Visa', 'business rewards visa': 'Business Rewards Visa',
                    'platinum visa': 'Platinum Visa', 'rewards visa': 'Rewards Visa'}[card_names[-1]]
    if 'heloc' in first or 'home equity line of credit' in first:
        return 'heloc'
    if ('home equity loan' in context or p.endswith('/home-equity')) and len(header) == 2:
        return 'equity_fixed'
    if 'model year' in first:
        return 'atv' if re.search(r'atv|snowmobile|jet ski', context) else 'auto'
    if len(header) == 3 and 'term' in h and '$' in first:
        if 'home improvement' in context or p.endswith('/home-improvement-loan'):
            return 'improvement'
        if re.search(r'\bboat\b|\brv\b', context) or p.endswith('/recreational-loans'):
            return 'boat'
    if len(header) == 2 and ('month' in first) and ('personal loan' in context or p.endswith('/personal-loans')):
        return 'personal'
    return None


def _extract_tables(page):
    text = page.markdown
    result = []
    matches = list(_TABLE.finditer(text))
    for ix, m in enumerate(matches):
        lines = m[0].splitlines()
        cells = [[clean(c) for c in line.strip('|').split('|')] for line in lines]
        if len(cells) < 3 or not all(re.fullmatch(r'\s*:?-+:?\s*', c) for c in cells[1]):
            continue
        header, rows = cells[0], cells[2:]
        if not any('%' in ' '.join(r) for r in rows):
            continue
        before = clean(text[max(0, m.start()-900):m.start()])
        family = _table_family(header, before, page, rows)
        if not family:
            continue
        after_end = matches[ix+1].start() if ix+1 < len(matches) else len(text)
        after = text[m.end():min(after_end, m.end()+2200)]
        eff = _effective(after)
        for row in rows:
            percentages = _percents(' '.join(row))
            if not percentages:
                continue
            name = row[0]
            row_family = 'mortgage_relief' if 'mortgage rate relief' in name.lower() else family
            item = {'family': row_family, 'name': name, 'page': page, 'effective': eff,
                    'term': _term(' '.join(row[:-1]).lower()), 'bounds': _amount_bounds(name),
                    'years': _years(name), 'quote': ' | '.join(row),
                    'intro': bool(re.search(r'intro|balance transfer', name, re.I)),
                    'details': clean(after), 'apr': percentages[0], 'rate': None}
            if family.startswith('mortgage') or family == 'equity_refinance':
                if len(row) < 4:
                    continue
                rate, apr = _percents(row[1]), _percents(row[3])
                if not rate or not apr:
                    continue
                item.update(rate=rate[0], apr=apr[0], points=row[2], payment=row[4] if len(row)>4 else None)
            elif 'Visa' in family:
                item['apr'] = _range(row[-1]) if not item['intro'] else percentages[0]
            elif family == 'heloc' and item['intro']:
                item['apr'] = percentages[0]
            result.append(item)
    return result


def _authority(item):
    paths = _PATHS.get(item['family'], [])
    p = _path(item['page'])
    if p in paths:
        return len(paths) + 2 - paths.index(p)
    if p == '/rates':
        return 2
    return 0


def _pick(items):
    if not items:
        return None
    # Incidental pages are not promoted merely because their crawl is fresh.
    authoritative = [x for x in items if _authority(x)]
    candidates=authoritative or items
    rank=lambda x:(x['effective'],_authority(x),x['page'].fetched_at)
    top=max(map(rank,candidates))
    tied=[x for x in candidates if rank(x)==top]
    values=lambda x:tuple(tuple(float(v[:-1]) for v in _percents(x.get(k) or '')) for k in ('rate','apr'))+(x.get('points'),_money(x.get('payment')),x.get('limit'))
    winner=dict(min(tied,key=lambda x:x['page'].url))
    if len({values(x) for x in tied})>1:
        winner['unresolved']=True
        winner['conflicting_pages']=sorted({x['page'].url:x['page'] for x in tied}.values(),key=lambda p:p.url)
    return winner


def _card_prose(page):
    """The consumer card page has product bullets rather than markdown tables."""
    result = []
    text = page.markdown
    for name in ('Platinum Visa', 'Rewards Visa', 'Business Platinum Visa', 'Business Rewards Visa'):
        m = re.search(r'(?m)^#{2,5}\s+' + re.escape(name) + r'\s*$', text)
        if not m:
            continue
        rest = text[m.end():]
        end = re.search(r'(?m)^#{2,5}\s+', rest)
        block = rest[:end.start()] if end else rest[:1800]
        limit = re.search(r'minimum credit limit\s+of\s+(\$\s*\d[\d,]*)', block, re.I)
        for line in block.splitlines():
            if '%' not in line or not re.search(r'APR|rate', line, re.I):
                continue
            intro = bool(re.search(r'new cardmember|intro|transferred balances', line, re.I))
            apr = _percents(line)[0] if intro else _range(line)
            result.append({'family': name, 'name': 'Introductory Balance Transfer Rate' if intro else 'Standard',
                           'page': page, 'effective': '', 'term': None, 'bounds': None, 'years': None,
                           'quote': clean(line), 'intro': intro, 'details': clean(text), 'apr': apr, 'rate': None,
                           'limit': limit[1].rstrip(',') if limit else None, 'limit_quote': clean(limit[0]) if limit else None})
    return result


def prepare(ctx):
    if 'loans' in ctx.cache:
        return ctx.cache['loans']
    accepted = {'/rates', '/business/rates'}
    for paths in _PATHS.values():
        accepted.update(paths)
    alias_pages={id(page) for paths in _PATHS.values() for path in paths
                 for page in [ctx.find(path)] if page is not None}
    all_items = []
    for page in ctx.pages:
        if _path(page) in accepted or id(page) in alias_pages:
            all_items.extend(_extract_tables(page))
            if _path(page) in ('/personal/credit-cards', '/business/credit-cards'):
                all_items.extend(_card_prose(page))
    all_items=[item for item in all_items if currently_valid(item.get('effective'),ctx.date,item['page'].markdown)]
    families = {}
    for item in all_items:
        families.setdefault(item['family'], []).append(item)
    data = {'families': families, 'items': all_items}
    ctx.cache['loans'] = data
    return data


def _rows(data, family, intro=False):
    rows = [r for r in data['families'].get(family, []) if r['intro'] == intro]
    # Keep one current row per qualified fact, not all competing page copies.
    keys = {}
    for row in rows:
        key = (row['term'], row['bounds'], row['years'])
        if 'Visa' in family or family == 'heloc':
            key = ('intro' if intro else 'standard',)
        keys.setdefault(key, []).append(row)
    return [_pick(v) for v in keys.values()]


def _source_reply(ctx, text, rows, note=None):
    uncertainty=_unresolved(ctx,rows)
    if uncertainty:return uncertainty
    # Corroboration requires the same qualified fact and values. Every source
    # receives its own actual excerpt, never another page's row.
    def signature(row):
        values = tuple(tuple(float(v[:-1]) for v in _percents(row.get(k) or '')) for k in ('rate','apr'))
        point = re.search(r'\d+(?:\.\d+)?',row.get('points') or '')
        return (row['family'],row['term'],row['bounds'],row['years'],row['intro'],values,
                float(point[0]) if point else None,_money(row.get('payment')),row.get('limit'))
    references = {}
    for row in rows:
        candidates = [row]
        for candidate in prepare(ctx)['families'].get(row['family'], []):
            if (_authority(candidate) and signature(candidate)==signature(row) and
                (not row['effective'] or not candidate['effective'] or row['effective']==candidate['effective'])):
                candidates.append(candidate)
        for candidate in candidates:
            extra = row.get('extra_evidence')
            if extra and extra not in clean(candidate['page'].markdown):
                continue
            url = candidate['page'].url
            refs = references.setdefault(url, {'page':candidate['page'],'quotes':[]})
            # Newlines delimit noncontiguous supporting excerpts. Joining
            # separate rows with punctuation would invent a nonexistent quote.
            for quote in (candidate['quote'],extra,candidate.get('limit_quote')):
                if quote and quote not in refs['quotes']:
                    refs['quotes'].append(quote)
    reply = ctx.reply(text, note=note)
    for refs in references.values():
        validated = ctx.reply('',pages=[refs['page']],quote='\n'.join(refs['quotes']))
        reply['sources'].extend(validated['sources'])
    return reply


def _unpublished(ctx, kind, page=None):
    lender = 'mortgage lender' if re.search(r'mortgage|construction|home equity', kind, re.I) else 'lender'
    return ctx.reply('I don\'t know the ' + kind + ' rate: the selected snapshot does not publish a rate for this product. Please contact a Dupaco ' + lender + ' for a quote.', pages=page or (), confident=False)


def _unresolved(ctx,rows):
    disputed=[r for r in rows if r.get('unresolved')]
    if not disputed:return None
    pages={p.url:p for r in disputed for p in r.get('conflicting_pages',[])}
    return ctx.reply("I don't know which published loan value is correct: equally authoritative sources disagree for the requested product and qualifiers.",
                     [pages[url] for url in sorted(pages)],confident=False,
                     note='Unresolved loan-source tie at equal authority, effective date and observation time; no value selected by page order.')


def _mortgage(ctx, data, q, family='mortgage_purchase'):
    page = ctx.find('/personal/loans/home-loans', '/rates')
    positive = re.sub(r'\b(?:not|excluding|without|ignore)\s+(?:the\s+)?(?:purchase|refinance|apr|interest rate|payment|points)\b', '', q)
    families = [family]
    if family.startswith('mortgage') and re.search(r'purchase',positive) and re.search(r'refinanc',positive):
        families = ['mortgage_purchase','mortgage_refinance']
    if 'rate relief' in positive:
        families = ['mortgage_relief']
        if re.search(r'conventional|purchase',positive):
            families.append('mortgage_purchase')
    rows = [row for group in families for row in _rows(data, group)]
    if not rows:
        return _unpublished(ctx, 'mortgage', page)
    amounts = _amounts(q)
    jumbo_limit = None
    jumbo_evidence = ''
    threshold_texts = [row['details'] for row in rows] + [clean(row['page'].markdown) for row in rows]
    for threshold_text in threshold_texts:
        threshold = re.search(r'jumbo[^$]{0,650}(\$\s*\d[\d,]*)',threshold_text,re.I)
        if threshold:
            jumbo_limit = _question_amount(threshold[1])
            jumbo_evidence = threshold[0]
            break
    jumbo_explanation = ''
    if 'jumbo' in q:
        if not amounts or not jumbo_limit or any(amount > jumbo_limit for amount in amounts):
            return _unpublished(ctx, 'jumbo mortgage', page)
        jumbo_explanation = 'A mortgage was jumbo only when its amount exceeded $' + format(jumbo_limit, ',.0f') + '; this amount is in the conventional tier. '
    if re.search(r'\b(?:fha|va|usda|physician|doctor|bridge|7\s*/\s*1|arm|adjustable)\b', q):
        kind = '7/1 adjustable-rate mortgage' if re.search(r'7\s*/\s*1', q) else 'requested specialized mortgage'
        return _unpublished(ctx, kind, page)
    terms = _terms(q)
    if terms:
        rows = [r for r in rows if r['term'] in terms or r['family']=='mortgage_relief']
    if amounts:
        matched = []
        for amount in amounts:
            for group in families:
                available = [r for r in rows if r['family']==group and (not r['bounds'] or r['bounds'][0]<=amount<=r['bounds'][1])]
                limit = min((r['bounds'][1] for r in available if r['bounds']), default=None)
                for row in available:
                    if (not row['bounds'] or row['bounds'][1]==limit) and row not in matched:
                        matched.append(row)
        rows = matched
    if not rows:
        return _unpublished(ctx, 'requested mortgage term or loan-amount tier', page)
    uncertainty=_unresolved(ctx,rows)
    if uncertainty:return uncertainty
    if jumbo_explanation:
        rows = [dict(row,extra_evidence=jumbo_evidence) for row in rows]
    # An unspecified amount leads with the smallest published mortgage amount.
    rows.sort(key=lambda r: (families.index(r['family']), -(r['term'] or 0), r['bounds'][1] if r['bounds'] else float('inf')))
    listing = bool(re.search(r'\bevery\b|\ball\b|complete|list|each (?:amount|tier|row)|entire', q))
    if not terms and not amounts and not listing:
        headline = []
        seen = set()
        for r in rows:
            key = (r['family'],r['term'])
            if key not in seen:
                headline.append(r); seen.add(key)
        rows = headline
    elif not amounts and len(terms)==1 and len(rows)>2 and not listing and len(families)==1:
        # Keep the two endpoints explicit when the member requests one term.
        rows = [rows[0], rows[-1]]
    parts = []
    metric_query = q.replace('rate relief', 'relief')
    metrics = requested_metrics(metric_query, 'mortgage')
    payment = bool(re.search(r'payment|monthly (?:cost|amount)',positive))
    if payment and not re.search(r'\b(?:rate|apr|interest|quote)\b',metric_query):
        metrics = set()
    if payment and not metrics and not any(_money(r.get('payment')) for r in rows):
        return _unpublished(ctx,'mortgage payment example',page)
    points = bool(re.search(r'points|compar|quotes|versus',positive))
    for r in rows:
        purpose = 'cash-out refinance' if r['family']=='equity_refinance' else ('refinance' if r['family'].endswith('refinance') else 'purchase')
        label = r['name'] if r['family']=='mortgage_relief' else purpose + ' ' + str(r['term']//12) + '-year fixed conventional'
        if r['bounds']:
            label += ' for loans up to $' + format(r['bounds'][1], ',.0f')
        values = []
        if 'rate' in metrics:
            values.append(r['rate'] + ' interest rate')
        if 'apr' in metrics:
            values.append(r['apr'] + ' APR')
        if points and r.get('points'):
            point_number = re.search(r'\d+(?:\.\d+)?',r['points'])
            values.append('zero points' if point_number and float(point_number[0])==0 else r['points'] + ' points')
        if payment:
            amount = _money(r.get('payment'))
            values.append('published monthly payment example ' + amount if amount else 'no published payment example')
        parts.append(label + ': ' + ' / '.join(values))
    eff = max((r['effective'] for r in rows), default='')
    tail = (' Effective ' + _date_label(eff) + '.') if eff else ''
    if payment:
        tail += ' Payment examples describe the published rows and are not personalized payment quotes.'
        if any(re.search(r'not include taxes and insurance',r['details']) for r in rows):
            tail += ' The examples exclude taxes and insurance.'
    if re.search(r'authoritative|which.{0,60}(?:page|quote)|ignore.{0,40}page',q):
        tail += ' The dated home-loan page and official rate sheet take precedence over older embedded copies.'
    return _source_reply(ctx, jumbo_explanation + 'Published mortgage quotes: ' + '; '.join(parts) + '.' + tail + ' Rates are as low as quoted and subject to approval; other loan amounts require a lender quote.', rows)


def _installment(ctx, data, q, family, label):
    rows = _rows(data, family)
    page = ctx.find(*_PATHS.get(family, []), '/rates')
    if not rows:
        return _unpublished(ctx, label, page)
    terms, amounts, years = _terms(q), _amounts(q), _question_years(q)
    span = _term_span(q)
    if span:
        rows = [r for r in rows if r['term'] is not None and span[0]<=r['term']<=span[1]]
    elif terms:
        rows = [r for r in rows if r['term'] in terms]
    if amounts and family in ('boat','improvement'):
        rows = [r for r in rows if r['bounds'] and any(r['bounds'][0]<=amount<=r['bounds'][1] for amount in amounts)]
    if years and family in ('auto','atv'):
        rows = [r for r in rows if r['years'] and any(r['years'][0]<=year<=r['years'][1] for year in years)]
    if not rows:
        return _unpublished(ctx, label + ' for the requested term, amount or model year', page)
    uncertainty=_unresolved(ctx,rows)
    if uncertainty:return uncertainty
    if family == 'auto' and not years and re.search(r'\bnew\b|newest|latest model', q):
        latest = max(r['years'][1] for r in rows if r['years'])
        rows = [r for r in rows if r['years'] and r['years'][1] == latest]
    rows.sort(key=lambda r: (-(r['years'][1] if r['years'] else 0), r['bounds'][0] if r['bounds'] else 0, r['term'] or 0))
    if re.search(r'shortest.{0,30}longest|longest.{0,30}shortest|endpoints',q):
        endpoint_terms = {min(r['term'] for r in rows),max(r['term'] for r in rows)}
        rows = [r for r in rows if r['term'] in endpoint_terms]
    parts = []
    for r in rows:
        qualifier = r['name'] + ', ' if family in ('auto', 'atv', 'boat', 'improvement') else ''
        if years and family in ('auto','atv'):
            qualifier = ', '.join(str(year) + ' vehicle' for year in years if r['years'][0]<=year<=r['years'][1]) + ' (' + r['name'] + '), '
        term = str(r['term'])
        adjective = bool(re.search(r'\b'+term+r'-months?\b',q))
        if family in ('auto','atv') and re.search(r'what term|which term',q):
            adjective = True
        parts.append(qualifier + term + ('-month term: ' if adjective else ' months: ') + r['apr'] + ' APR')
    eff = max((r['effective'] for r in rows), default='')
    suffix = (' Effective ' + _date_label(eff) + '.') if eff else ''
    note = None
    if re.search(r'checking[- ](?:page|table)|authorit|product.specific|stale|\bsource\b|\bcontrol\b|which.{0,60}(?:page|quote)',q):
        suffix += ' These product-specific loan tables take precedence over incidental embedded copies.'
        incidental = ctx.find('/personal/checking-accounts') if 'checking' in q else None
        if incidental:
            for old in _extract_tables(incidental):
                for row in rows:
                    same_year = (not row['years'] and not old['years']) or (row['years'] and old['years'] and max(row['years'][0],old['years'][0])<=min(row['years'][1],old['years'][1]))
                    if years and row['years'] and old['years']:
                        same_year = any(row['years'][0]<=year<=row['years'][1] and old['years'][0]<=year<=old['years'][1] for year in years)
                    different_apr = tuple(float(v[:-1]) for v in _percents(old['apr'])) != tuple(float(v[:-1]) for v in _percents(row['apr']))
                    if old['family']==family and old['term']==row['term'] and same_year and different_apr:
                        note = 'An embedded checking-page table quotes a different APR for this qualified term and model year. The product-specific loan source supplies the authoritative quote.'
                        break
                if note:
                    break
    return _source_reply(ctx, label + ' rates as low as: ' + '; '.join(parts) + '.' + suffix + ' Approval and the final APR depend on credit qualification and the applicable loan tier.', rows,note=note)


def _cards(ctx, data, q):
    names = ['Platinum Visa', 'Rewards Visa', 'Business Platinum Visa', 'Business Rewards Visa']
    business = bool(re.search(r'\bbusiness\b|\bcommercial\b',q))
    personal = bool(re.search(r'\bpersonal\b|\bconsumer\b',q))
    intro_requested = bool(re.search(r'intro|balance transfer|transfer.{0,25}balance|promot|first\s+90|six.{0,5}months', q) or
                           'transfer' in q and re.search(r'offer|qualif|expiry|expiration|posting|first.transfer',q))
    if (re.search(r'after.{0,30}intro|following.{0,30}intro|ongoing|standard purchase',q) and
        not re.search(r'how long|when|first.*days|both|compar',q)):
        intro_requested = False
    if business and not personal:
        names = names[2:]
    elif personal and not business:
        names = names[:2]
    if 'platinum' in q and not re.search(r'\brewards?\b',q):
        names = [n for n in names if 'Platinum' in n]
        if not business and not re.search(r'all|both|compare', q):
            names = ['Platinum Visa']
    elif re.search(r'\brewards?\b', q) and 'platinum' not in q:
        names = [n for n in names if 'Rewards' in n]
        if not business and not re.search(r'all|both|compare', q):
            names = ['Rewards Visa']
    if intro_requested:
        if business or (re.search(r'\brewards?\b',q) and 'platinum' not in q):
            return _unpublished(ctx,'requested card introductory APR',ctx.find('/business/credit-cards' if business else '/personal/credit-cards','/rates'))
        # Only Platinum has this published transfer offer; a generic intro
        # question is not a request to enumerate unrelated standard cards.
        names = ['Platinum Visa']
    selected = []
    limit_requested = bool(re.search(r'(?:minimum|credit|borrowing) limit',q))
    for name in names:
        r = _pick(_rows(data, name))
        if r:
            if limit_requested:
                with_limit = [x for x in data['families'].get(name,[]) if x.get('limit') and
                              tuple(float(v[:-1]) for v in _percents(x['apr']))==tuple(float(v[:-1]) for v in _percents(r['apr'])) and not x['intro']]
                match = _pick(with_limit)
                if match:
                    r = dict(match,apr=r['apr'])
            selected.append(r)
    if not selected:
        return _unpublished(ctx, 'credit card', ctx.find('/personal/credit-cards', '/business/credit-cards', '/rates'))
    uncertainty=_unresolved(ctx,selected)
    if uncertainty:return uncertainty
    parts = []
    for r in selected:
        label = r['family'] if r['family'].startswith('Business') or not business else 'personal ' + r['family']
        part = label + ': ' + r['apr'] + (' variable APR' if r['family'].startswith('Business') else ' standard purchase APR')
        if limit_requested:
            part += '; minimum credit limit ' + r['limit'] if r.get('limit') else '; no minimum credit limit published'
        parts.append(part)
    text = '' if intro_requested else '; '.join(parts) + '.'
    if intro_requested:
        selected = []
        intro = _pick(_rows(data, 'Platinum Visa', intro=True))
        if intro:
            disclosure_page = ctx.find('/personal/credit-cards', '/rates')
            disclosure = clean(disclosure_page.markdown) if disclosure_page else intro['details']
            eligibility = re.search(r'first\s+(\d+)\s+days', disclosure, re.I)
            expiry = re.search(r'(?:expires|ends)\s+(\w+|\d+)\s+months\s+(from|after)\s+([^.;]+)',disclosure,re.I)
            duration=expiry
            if not duration:
                duration = re.search(r'for\s+(\d+|[a-z]+)\s+(?:months|mos)', intro['quote'], re.I)
            text += ' Platinum Visa offers ' + intro['apr'] + ' introductory APR on eligible balance transfers'
            if duration:
                text += ' for ' + duration[1] + ' months'
                if expiry:
                    anchor=re.split(r',?\s+at which time|,?\s+when|,?\s+then',expiry[3],maxsplit=1,flags=re.I)[0].strip()
                    text+=' '+expiry[2].lower()+' '+anchor
                elif re.search(r'anchor|expiry|clock|timing|measured',q):
                    text+='; the source does not state the expiry anchor'
            text += '.'
            if eligibility:
                text += ' Transfers must post within the first ' + eligibility[1] + ' days after opening the card.'
                posting=re.search(r'\b(?:posts?|posted|posting)\b.{0,25}\bday\s+(\d+)\b',q)
                if not posting:
                    posting=re.search(r'\b(?:posts?|posted|posting)\b.{0,15}?(\d+)\s+days?\s+(?:after|following)\b',q)
                if posting:
                    fits=int(posting[1])<=int(eligibility[1])
                    text=('The stated posting day meets this timing requirement. ' if fits else
                          'No. The stated posting day falls outside the published qualification window. ') + text
                    text+=' This compares the stated timing only; it does not verify an actual transfer.'
            standard = _pick(_rows(data, 'Platinum Visa'))
            asks_standard=bool(re.search(r'\bstandard\b|\bongoing\b|\brevert\b|after.{0,30}(?:intro|promo|expiry)|(?:range|rate|apr).{0,12}\bfollows\b',q))
            if standard and asks_standard and not re.search(r'not (?:the )?standard|excluding (?:the )?standard|intro (?:apr )?only',q):
                text += ' After the introductory period, the standard ' + standard['apr'] + ' variable APR applies.'
                selected.append(standard)
            # Add the actual offer disclosure to the product source, including
            # its qualifying window and duration, rather than padding sources.
            offer = re.search(r'The \d+(?:\.\d+)?% annual percentage rate \(APR\) balance transfer introductory rate[^_]+',disclosure,re.I)
            if disclosure_page and offer:
                offer_quote = re.split(r',?\s+at which time|,?\s+after that',offer[0],maxsplit=1,flags=re.I)[0]
                intro = dict(intro,page=disclosure_page,quote=offer_quote[:1200])
            selected.append(intro)
        else:
            return _unpublished(ctx,'Platinum Visa introductory APR',ctx.find('/personal/credit-cards','/rates'))
    reply=_source_reply(ctx,text.strip(),selected)
    if intro_requested and not expiry and re.search(r'anchor|expiry|clock|timing|measured',q):
        reply['confident']=False
    return reply


def _student(ctx, q):
    page = ctx.find('/personal/loans/student-loans')
    if not page:
        return ctx.reply('I do not have a published student loan offer in this snapshot.', confident=False)
    t = clean(page.markdown)
    if re.search(r'\brate|\bapr|interest', q):
        # The page links out to the partner's rates; a link is not a quoted rate.
        return _unpublished(ctx, 'student loan', page)
    patterns = []
    if re.search(r'partner|contact|call|phone|telephone', q):
        patterns.extend([r'Dupaco partners with[^.]+\.', r'you can contact[^.]+\.'])
    if re.search(r'eligib|qualif|citizen|resident|school|university', q):
        patterns.append(r'Applicants must be a U\.S\. citizen[^.]+\.')
    if re.search(r'refinanc|consolidat|limit|maximum|how much', q):
        patterns.extend([r'You can refinance up to[^.]+\.', r'You must be a graduate[^.]+\.', r'If you refinance federal loans[^.]+\.'])
    if re.search(r'fee|prepay|early|cost', q):
        patterns.append(r'(?:Benefit from|No\. There is)[^.]+(?:origination|prepayment)[^.]+\.')
    if re.search(r'flexib|defer|(?:repay|payment).{0,20}(?:option|term|plan|choice)|school|university', q) or not patterns:
        patterns.extend([r'Defer full payments[^.]+\.', r'Benefit from[^.]+\.', r'Cover costs that federal aid[^.]+\.', r'Apply just once[^.]+\.'])
    details = []
    for pat in patterns:
        m = re.search(pat, t, re.I)
        if m and m[0] not in details:
            details.append(m[0][0].upper() + m[0][1:])
    headline = 'Dupaco offers private student loans'
    if re.search(r'Apply for Refinancing|Student Debt Refinance', t):
        headline += ' and student loan refinancing'
    if 'CU Student Choice' in t:
        headline += ' through CU Student Choice'
    return ctx.reply(headline + '. ' + ' '.join(details), pages=page, quote=' '.join(details)[:900])


def _credit_coach(ctx):
    page = ctx.find('/personal/loans/personal-loans')
    if page:
        # Use the product description, not its application form or payment example.
        for line in page.markdown.splitlines():
            t = clean(line)
            if 'Credit Coach Loan' not in t or 'APR' not in t:
                continue
            amount = re.search(r'(?:loans?|borrow)\s+up\s+to\s+(\$\s*\d[\d,]*(?:\.\d+)?)', t, re.I)
            rate = _percents(t)
            if amount and rate:
                text = 'A Credit Coach Loan is available up to ' + amount[1].rstrip(',') + ' at ' + rate[0] + ' APR.'
                feature = re.search(r'It[’\']s a short-term[^.]+\.', t)
                if feature:
                    text += ' ' + feature[0]
                return ctx.reply(text, pages=page, quote=t)
            return ctx.reply(t, pages=page, quote=t)
    return ctx.reply('I do not have published Credit Coach Loan details in this snapshot. Please contact Dupaco.', pages=page or (), confident=False)


def _personal_info(ctx, q):
    page = ctx.find('/personal/loans/personal-loans')
    if not page:
        return None
    text = clean(page.markdown)
    excerpts = []
    repayment = re.search(r'Choose repayment terms from[^.]+\.',text,re.I)
    if repayment and re.search(r'personal|repay|term|range|compar',q):
        excerpts.append(repayment[0])
    if re.search(r'share.?secured|collateral|available balance',q):
        for line in page.markdown.splitlines():
            if 'share-secured loan' in line.lower() and 'collateral' in line.lower():
                excerpts.append(clean(line)); break
    return ctx.reply(' '.join(excerpts),pages=page,quote=' '.join(excerpts)) if excerpts else None


def _loan_overview(ctx):
    page = ctx.find('/personal-loans','/personal/loans')
    if not page:
        return None
    start = re.search(r'(?m)^###\s+',page.markdown)
    if not start:
        return None
    body = page.markdown[start.start():]
    end = re.search(r'(?m)^#{1,2}\s+',body)
    if end:
        body = body[:end.start()]
    sections = re.findall(r'(?m)^###\s+([^\n]+)',body)
    if not sections:
        return None
    return ctx.reply('The personal-loans overview presents: ' + '; '.join(clean(s) for s in sections) + '.',pages=page,quote='; '.join(sections))


def _recreational_info(ctx, q):
    page = ctx.find('/personal/loans/recreational-loans')
    if not page:
        return None
    paragraphs = [clean(line) for line in page.markdown.splitlines() if re.search(r'boats.*RVs.*ATVs.*jet skis.*snowmobiles',line,re.I)]
    text = paragraphs[0] if paragraphs else ''
    if re.search(r'link|apply|application',q):
        link = re.search(r'\[(?:Apply)[^\]]*\]\(([^)]+)\)',page.markdown,re.I)
        if link:
            text += ' Apply online: ' + link[1] + '.'
    return ctx.reply(text,pages=page,quote=paragraphs[0] if paragraphs else None) if text else None


def _debt_consolidation_info(ctx):
    page = ctx.find('/personal/loans/debt-consolidation')
    if not page:
        return None
    first = re.search(r'(?m)^####\s+',page.markdown)
    if not first:
        return None
    body = page.markdown[first.start():]
    following_section = re.search(r'(?m)^#{1,2}\s+',body)
    if following_section:
        body = body[:following_section.start()]
    parts = []
    for m in re.finditer(r'(?ms)^####\s+([^\n]+)\n(.*?)(?=^#{1,6}\s|\Z)',body):
        paragraphs = [clean(line) for line in m[2].splitlines() if line.strip() and not line.lstrip().startswith(('![','[','#'))]
        if paragraphs:
            parts.append(clean(m[1]) + ': ' + ' '.join(paragraphs))
    return ctx.reply(' '.join(parts),pages=page,quote=' '.join(parts)) if parts else None


def _card_fee(ctx, q):
    business = bool(re.search(r'\bbusiness\b|\bcommercial\b', q))
    page = ctx.find('/business/credit-cards' if business else '/personal/credit-cards')
    if not page:
        return ctx.reply('I cannot confirm that credit card fee from this snapshot. Please contact Dupaco.', confident=False)
    t = clean(page.markdown)
    label = 'Business Visa' if business else 'Personal Visa'
    if 'platinum' in q:
        label = 'Business Platinum Visa' if business else 'Platinum Visa'
    elif re.search(r'\brewards?\b', q):
        label = 'Business Rewards Visa' if business else 'Rewards Visa'
    if label not in ('Business Visa', 'Personal Visa'):
        named = r'(?:Rewards Visa|Visa Rewards)' if label == 'Rewards Visa' else re.escape(label)
        disclosure = re.search(named + r'\s+Rates?:', t, re.I)
        if disclosure:
            t = t[disclosure.start():]
            following = re.search(r'(?:Business Platinum Visa|Business Rewards Visa|Platinum Visa|Rewards Visa|Visa Rewards)\s+Rates?:', t[disclosure.end()-disclosure.start():], re.I)
            if following:
                t = t[:following.start()+disclosure.end()-disclosure.start()]
    match = None
    if re.search(r'foreign|international|overseas', q):
        match = re.search(r'foreign transaction fee\s*[-—–:]?\s*(\d+(?:\.\d+)?%\s+of\s+each\s+transaction\s+in\s+US\s+[Dd]ollars)', t, re.I)
        if match:
            return ctx.reply(label + ' foreign transaction fee: ' + match[1] + '.', pages=page, quote=match[0])
    elif re.search(r'cash advance|advances|withdraw cash', q):
        match = re.search(r'(?:cash advance fee\s*[-—–:]?|fee for advances is)\s*(\$\s*\d[\d,]*(?:\.\d+)?\s+or\s+\d+(?:\.\d+)?%\s+[^;]*?whichever is greater)', t, re.I)
        if match:
            return ctx.reply(label + ' cash advance fee: ' + match[1] + '.', pages=page, quote=match[0])
    elif re.search(r'annual|yearly', q) and re.search(r'no annual fee', t, re.I):
        return ctx.reply(label + ' has no annual fee.', pages=page, quote='There is no annual fee.')
    elif re.search(r'balance transfer', q) and re.search(r'no balance transfer fee', t, re.I):
        return ctx.reply(label + ' has no balance transfer fee.', pages=page, quote='There is no balance transfer fee.')
    elif re.search(r'late|returned payment', q):
        kind = 'returned payment' if 'returned payment' in q else 'late payment'
        match = re.search(re.escape(kind) + r' fee\s*[-—–:]?\s*([^;]+)', t, re.I)
        if match:
            return ctx.reply(label + ' ' + kind + ' fee: ' + match[1].rstrip('._') + '.', pages=page, quote=match[0])
    return ctx.reply('I cannot confirm that specific credit card fee from this snapshot. Please contact Dupaco.', pages=page, confident=False)


def _grant(ctx, q):
    home_start = bool(re.search(r'home\s*[$s]?\s*tart|fhlb|federal home loan bank', q))
    if home_start:
        page = ctx.find('/newsroom/first-time-homebuyers-get-a-boost-dupaco-offers-fhlb-hometart-grants')
        if page:
            t = clean(page.markdown)
            m = re.search(r'This initiative provides[^.]+\.', t)
            if m:
                return ctx.reply('Home$tart is Dupaco\'s first-time homebuyer assistance program with the Federal Home Loan Bank (FHLB) of Des Moines. ' + m[0], pages=page, quote=m[0])
    page = ctx.find('/first-time-homebuyer-grant')
    if page:
        t = clean(page.markdown)
        m = re.search(r'The First-Time Homebuyer Grant is[^.]+\.', t)
        if m:
            text = m[0]
            if re.search(r'eligib|qualif|income|require|apply', q):
                for pat in (r'You are at least[^.]+\.', r'You are a first-time homebuyer[^.]+\.', r'Your household income is[^.]+\.'):
                    match = re.search(pat, t)
                    if match:
                        text += ' ' + match[0]
            if home_start:
                return ctx.reply('The snapshot does not publish Home$tart details; the Foundation grant is a separate program. ' + text, pages=page, confident=False)
            return ctx.reply(text, pages=page, quote=m[0])
    return ctx.reply('I do not have published details for that homebuyer grant in this snapshot.', confident=False)


def answer(ctx, question):
    q = clean(question).lower().replace('‑', '-').replace('–', '-').replace('’', "'")
    q = re.sub(r'\b(personal|unsecured|signature|student|credit|construction|auto|home)-loan\b', r'\1 loan', q)
    q = re.sub(r'\b(credit|debit)-card\b', r'\1 card', q)
    data = prepare(ctx)
    # The fee-schedule's scope and referral language belongs to that source,
    # not a Visa product fee that happens to contain the word "late".
    if re.search(r'fee schedule',q):
        return None
    if 'business' not in q and re.search(r'loan',q) and re.search(r'overview|top.level|every.*categor|all.*categor',q):
        return _loan_overview(ctx)
    if re.search(r'\bcredit coach\b', q):
        return _credit_coach(ctx)
    if re.search(r'debt.consolidation',q) and not re.search(r'\bapr\b|\brate\b|interest rate|\bcost\b|\bcharge\b',q):
        return _debt_consolidation_info(ctx)
    if re.search(r'share.?secured|collateral|available balance',q):
        if re.search(r'\brate|\bapr',q):
            return _unpublished(ctx,'share-secured loan',ctx.find('/personal/loans/personal-loans'))
        return _personal_info(ctx,q)
    if re.search(r'home\s*[$s]?\s*tart|first.{0,8}(?:time )?home.?buyer.{0,25}grant|home.?buyer.{0,25}assistance|fhlb.{0,25}grant', q):
        return _grant(ctx, q)
    if re.search(r'\bstudent\b|college|university', q) and re.search(r'loan|borrow|fund|financ|option|flexib', q):
        return _student(ctx, q)
    card = bool(re.search(r'credit cards?|\bvisa\b|\bplatinum\b|\bcard(?:member|holder)\b', q))
    generic_transfer=bool('transfer' in q and re.search(r'offer|intro|promot|posting|qualif|expiry',q))
    if generic_transfer and not card:
        offered=[name for name,rows in data['families'].items() if 'Visa' in name and any(row['intro'] for row in rows)]
        if len(offered)==1:
            q=offered[0].lower()+': '+q;card=True
        else:
            return _unpublished(ctx,'unambiguously identified card transfer offer',ctx.find('/personal/credit-cards','/rates'))
    card_intent = bool(re.search(r'\brate|\bapr|interest|offer|available|compar|quot|which|what.{0,30}cards|intro|balance transfer', q))
    if card and re.search(r'fee|charge|cost', q) and not re.search(r'interest|\bapr|\brate', q):
        return _card_fee(ctx, q)
    if card and card_intent and not re.search(r'mobile wallet|apple pay|google pay|samsung pay|lost|stolen|replacement|fee|charge|cost', q):
        return _cards(ctx, data, q)
    rate_intent = bool(re.search(r'\brate|\bapr|interest|\bcost\b|\bcharge\b|\bquot(?:e[ds]?|ation)\b|payment|points|compar|versus', q))
    if 'construction' in q and rate_intent:
        page = ctx.find('/business/loans/construction-loans') if 'business' in q else ctx.find('/personal/loans/home-loans')
        return _unpublished(ctx, 'construction loan', page)
    if re.search(r'\bheloc\b|home equity line', q) and rate_intent:
        rows = _rows(data, 'heloc')
        if not rows:
            return _unpublished(ctx, 'home equity line of credit', ctx.find('/personal/loans/home-equity', '/rates'))
        r = _pick(rows)
        text = 'The home equity line of credit (HELOC) standard variable APR is as low as ' + r['apr'] + '.'
        selected = [r]
        if re.search(r'intro|promot|special', q):
            intro = _pick(_rows(data, 'heloc', intro=True))
            if intro:
                expiry = re.search(r'(?:expires|expire)\s+(\d{1,2})/(\d{1,2})/(\d{2,4})', intro['details'], re.I)
                expired = False
                if expiry:
                    mo, dy, yr = map(int, expiry.groups()); yr += 2000 if yr<100 else 0
                    try:
                        expired = date(yr,mo,dy).isoformat() < ctx.date
                    except ValueError:
                        pass
                if not expired:
                    text += ' The published introductory offer is ' + intro['quote'] + '.'
                    selected.append(intro)
                else:
                    text += ' The earlier introductory offer has expired.'
            else:
                text += ' No current introductory offer is published in this snapshot.'
        return _source_reply(ctx, text, selected)
    if re.search(r'home equity|cash.?out refinanc', q) and rate_intent:
        if re.search(r'refinanc|cash.?out', q):
            return _mortgage(ctx, data, q, 'equity_refinance')
        return _installment(ctx, data, q, 'equity_fixed', 'Fixed home equity loan')
    if re.search(r'home improvement|renovation', q) and rate_intent:
        return _installment(ctx, data, q, 'improvement', 'Home improvement loan')
    mortgage_implied = (bool(re.search(r'\bpurchase\b|\brefinanc', q)) and
                        any(n >= 180 for n in _terms(q)) and
                        not re.search(r'auto|motorcycle|\bcar\b|vehicle|\bboat\b|\brv\b|personal|student', q))
    if (re.search(r'\bmortgage\b|home loan|7\s*/\s*1|adjustable.?rate', q) or mortgage_implied) and rate_intent:
        return _mortgage(ctx, data, q, 'mortgage_refinance' if re.search(r'refinanc', q) else 'mortgage_purchase')
    if re.search(r'\bauto\b|motorcycle|\bcar\b|vehicle|\btruck\b', q) and rate_intent and not re.search(r'insurance|fee|reposses|for sale|bid', q):
        return _installment(ctx, data, q, 'auto', 'Auto and motorcycle loan')
    if re.search(r'\bboat\b|\brv\b|recreational vehicle|camper|motor.?home', q) and rate_intent:
        return _installment(ctx, data, q, 'boat', 'Boat and RV loan')
    if re.search(r'\batv\b|snowmobile|jet ski|personal watercraft', q) and rate_intent:
        return _installment(ctx, data, q, 'atv', 'ATV, snowmobile and jet ski loan')
    if re.search(r'recreational',q):
        if rate_intent:
            rows = _rows(data,'boat') + _rows(data,'atv')
            return _source_reply(ctx,'Published recreational APRs: ' + '; '.join(r['name'] + ', ' + str(r['term']) + ' months: ' + r['apr'] + ' APR' for r in rows) + '.',rows) if rows else _unpublished(ctx,'recreational loan',ctx.find('/personal/loans/recreational-loans'))
        return _recreational_info(ctx,q)
    if re.search(r'personal loan|unsecured loan|signature loan|debt consolidation loan', q) and rate_intent:
        return _installment(ctx, data, q, 'personal', 'Personal loan')
    if re.search(r'personal loan|unsecured loan',q):
        return _personal_info(ctx,q)
    return None
