"""Qualified, provenance-preserving contradictions in dated website snapshots.

The extractor deliberately compares a product's *same* measure and qualifiers.
Different balance tiers, loan amounts, terms, consumer/business accounts, IRA
types, introductory phases, and nominal rates versus APY/APR are separate facts.
No evaluation files, network resources, or external state are consulted.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlsplit

from common import clean
from evidence import canonical_identity,raw_spans,currently_valid,explicit_effective_date


@dataclass(frozen=True)
class Claim:
    key: tuple
    topic: str
    value: str
    url: str
    sid: str
    observed: str
    effective: str
    quote: str
    authority: int

    @property
    def identity(self):
        return canonical_identity(*self.key) if len(self.key)==6 else self.key

    def source(self):
        return {'url': self.url, 'snapshot_id': self.sid, 'quote': self.quote}


def _norm(text):
    text = clean(text).lower().replace('–', '-').replace('—', '-')
    text = text.replace('’', "'").replace('‑', '-').replace('\u00a0', ' ')
    text = re.sub(r'(?<=\d),(?=\d)', '', text)
    text = re.sub(r'(?<=\d)\.00\b', '', text)
    text = re.sub(r'\s*-\s*', '-', text)
    return re.sub(r'\s+', ' ', text).strip()


def _percent(text):
    m = re.search(r'(\d+(?:\.\d+)?)\s*%', text)
    if not m:
        return None
    values = re.findall(r'(\d+(?:\.\d+)?)\s*%', text)
    # Preserve a quoted variable range as a single fact.
    return ' - '.join(f'{float(x):g}%' for x in values[:2])


def _effective(text):
    return explicit_effective_date(clean(text))


def _authority(url):
    path = urlsplit(url).path.rstrip('/').lower()
    if path in ('/rates', '/business-rates'):
        return 5
    if path.startswith(('/personal/', '/business/')) or path in ('/checking', '/earn-more'):
        return 4
    if '/newsroom/' in path or '/learn/blog/' in path or re.match(r'/20\d\d/', path):
        return 1
    return 2


def _tables(markdown):
    lines = markdown.splitlines()
    heading = ''
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('|') and i + 1 < len(lines) and re.match(r'^\s*\|[\s:|\-]+\|\s*$', lines[i + 1]):
            headers = [clean(x) for x in line.strip('|').split('|')]
            start = i
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                cells = [clean(x) for x in lines[i].strip().strip('|').split('|')]
                if len(cells) == len(headers):
                    rows.append((cells, clean(lines[i])))
                i += 1
            # Effective dates immediately following a rate table govern it.
            tail = []
            j = i
            while j < len(lines) and j < i + 14:
                if lines[j].strip().startswith('|'):
                    break
                tail.append(lines[j])
                j += 1
            yield headers, rows, heading, _effective('\n'.join(tail)), start
            continue
        text = clean(line.lstrip('# '))
        # Rate widgets use bare short labels, as well as Markdown headings.
        if text and len(text) < 110 and not line.startswith(('[', '!', '|', '- ', '_')) and not re.search(r'[.!?%]', text):
            heading = text
        i += 1


def _product(headers, row, heading, path):
    hs = [_norm(h) for h in headers]
    account = next((row[i] for i, h in enumerate(hs) if h == 'account type'), None)
    name = account or heading
    lower = _norm(name)
    first = _norm(row[0])
    scope = 'business' if path.startswith('/business') or 'business' in lower else 'personal'
    ti = next((i for i, h in enumerate(hs) if h in ('term', 'loan term')), None)
    term_text = _norm(row[ti]) if ti is not None else first
    # The word "Model Year" is metadata, never a loan-duration unit.
    month = re.search(r'(\d+)\s*(?:-\s*)?(months?|mo\b|years?)\b', term_text) if 'model year' not in term_text else None
    if month:
        term = int(month[1]) * (12 if month[2].startswith('year') else 1)
    else:
        term = None
    if any('apy' in h or 'annual percentage yield' in h for h in hs):
        if 'roth:' in first or 'traditional:' in first:
            typ = 'roth' if 'roth:' in first else 'traditional'
            kind = 'jumbo special' if 'jumbo' in first else 'special' if 'special' in first else 'regular' if term else 'variable'
            return 'ira', scope, f'{typ} IRA {kind}', (term, _norm(row[-1])) if term else (first,), f'{term}-month {typ.title()} IRA {kind}' if term else f'{typ.title()} variable IRA {row[0]}'
        if term:
            kind = 'jumbo special' if 'jumbo' in first else 'special' if 'special' in first else 'regular'
            return 'certificate', scope, f'certificate {kind}', (term, _norm(row[-1])), f'{term}-month {scope} certificate {kind}'
        products = [('1st rate', '1st Rate Checking'), ('free checking', 'Free Checking'),
                    ('share savings', 'Share Savings'), ('bright', 'Bright Savings'),
                    ('you name it', 'You Name It Savings'), ('you-name-it', 'You Name It Savings'),
                    ('holiday', 'Holiday Club Savings'), ('launchpad', 'Launchpad Savings'),
                    ("investor", "Investor's Choice Money Market"), ('high-yield', 'High-Yield Savings'),
                    ('high yield', 'High-Yield Savings'), ('achieve', 'Achieve Money Market'),
                    ('health savings', 'Health Savings Account')]
        product = next((v for k, v in products if k in lower), None)
        if not product:
            # Explicit account labels are valid identities even when the
            # institution renames a product beyond the starter vocabulary.
            product=name if account else None
            if not product:return None
        bi = next((i for i, h in enumerate(hs) if h in ('balance', 'balance tier')), None)
        balance = _norm(row[bi]) if bi is not None else ''
        if not balance and product == 'Launchpad Savings':
            nums = [_norm(row[i]) for i, h in enumerate(hs) if 'min. balance' in h or 'max. balance' in h]
            balance = ' - '.join(nums)
        return 'deposit', scope, product, (balance,), f'{scope} {product} {row[bi] if bi is not None else ""}'.strip()
    if 'apr' not in ' '.join(hs) and 'annual percentage rate' not in ' '.join(hs):
        return None
    if 'points' in hs and term:
        kind = 'refinance' if 'refinance' in first else 'purchase' if 'purchase' in first else 'other'
        amount = re.search(r'\$\s*([\d,.]+)', first)
        amount = _norm(amount[0]) if amount else ''
        return 'mortgage', scope, f'{kind} fixed mortgage', (term, amount), f'{term // 12}-year fixed {kind} mortgage {amount}'.strip()
    if 'model year' in first and term:
        years = re.findall(r'\b(?:20)?\d{2}\b', first)
        years = [int(x) if len(x) == 4 else 2000 + int(x) for x in years]
        yrange = tuple(sorted(years[:2])) if years else (first,)
        # Model years are part of the identity: a moved year band is not itself
        # proof of a rate conflict, although overlapping years can be checked.
        product = 'ATV loan' if 'atv' in _norm(heading) else 'auto loan'
        return 'auto', scope, product, (term, yrange), f'{product} {term}-month model years {first}'
    if term:
        if 'home equity' in _norm(heading) or 'home-equity' in path:
            product = 'home equity loan'
        elif 'home improvement' in _norm(heading) or 'home-improvement' in path:
            product = 'home improvement loan'
        elif '$' in first and ('boat' in _norm(heading) or 'recreational' in path or path == '/switch-and-earn'):
            product = 'boat and RV loan'
        elif 'personal' in _norm(heading) or 'personal-loan' in path:
            product = 'personal loan'
        else:
            return None
        amount = first if '$' in first else ''
        return 'loan', scope, product, (term, amount), f'{product} {term}-month {amount}'.strip()
    return None


def _extract(ctx):
    claims = []
    for page in ctx.pages:
        path = urlsplit(page.url).path.rstrip('/').lower()
        if '/learn/blog/' in path or '/newsroom/' in path or re.match(r'/20\d\d/', path):
            continue  # Dated articles describe history, not current promises.
        # Some pages place contractual disclosures below recommendations;
        # tables and explicit product statements remain available there.
        md = page.markdown
        expired = re.search(r'\b(?:offer ended|offer expired|promotion ended|promotion expired)\s*[: ]\s*(20\d\d-\d{2}-\d{2})', clean(md), re.I)
        if expired and expired[1] < ctx.date[:10]:
            continue
        for headers, rows, heading, effective, _ in _tables(md):
            hs = [_norm(h) for h in headers]
            for row, quote in rows:
                identity = _product(headers, row, heading, path)
                if not identity:
                    continue
                category, scope, product, qualifier, topic = identity
                for i, h in enumerate(hs):
                    metric = 'APY' if 'apy' in h or 'annual percentage yield' in h else 'APR' if 'apr' in h or 'annual percentage rate' in h else 'rate' if h == 'rate' or h.startswith('dividend rate') else None
                    if not metric:
                        continue
                    # Keep standard Achieve and introductory Achieve phases apart.
                    phase = 'introductory' if '1st 6' in h or 'first 6' in h else 'standard' if 'after' in h or product == 'Achieve Money Market' else ''
                    value = _percent(row[i])
                    if value is None:
                        continue
                    qualifiers = [qualifier]
                    if category == 'auto' and isinstance(qualifier[1], tuple) and all(isinstance(y, int) for y in qualifier[1]):
                        years = qualifier[1]
                        if len(years) == 2 and 0 <= years[1] - years[0] < 15:
                            qualifiers = [(qualifier[0], (year, year)) for year in range(years[0], years[1] + 1)]
                    for qualified in qualifiers:
                        key = category, scope, product, qualified, metric, phase
                        qualified_topic = topic
                        if category == 'auto' and len(qualified[1]) == 2:
                            qualified_topic = f'{product} {qualified[0]}-month model year {qualified[1][0]}'
                        claims.append(Claim(key, qualified_topic + f' {phase} {metric}'.replace('  ', ' '), value,
                                            page.url, ctx.sid, ctx.date, effective, quote[:500], _authority(page.url)))
        # Small snapshots may use simple labelled facts rather than tables.
        for line in md.splitlines():
            text = clean(line)
            m = re.search(r'(\d+)\s*[- ]?\s*month\s+certificate\s+(APY|dividend rate|rate)\s*:?\s*(\d+(?:\.\d+)?)\s*%', text, re.I)
            if m and not re.search(r'\b(?:ended|expired|example|illustrat)\b', text, re.I):
                term, metric = int(m[1]), 'APY' if m[2].lower() == 'apy' else 'rate'
                key = 'certificate', 'personal', 'certificate regular', (term, ''), metric, ''
                claims.append(Claim(key, f'{term}-month certificate {metric}', f'{float(m[3]):g}%', page.url,
                                    ctx.sid, ctx.date, _effective(text), text[:500], _authority(page.url)))
            # A current standard APR disclosed in prose can contradict a summary.
            if 'platinum' in text.lower() and re.search(r'current standard APR', text, re.I):
                m = re.search(r'current standard APR.*?variable rate (?:from|of)\s*(\d+(?:\.\d+)?)\s*%(?:\s*APR)?\s*(?:to|-)\s*(\d+(?:\.\d+)?)\s*%', text, re.I)
                if m:
                    key = 'card', 'personal', 'Platinum Visa', (), 'APR', 'standard'
                    value = f'{float(m[1]):g}% - {float(m[2]):g}%'
                    claims.append(Claim(key, 'Platinum Visa standard APR', value, page.url, ctx.sid, ctx.date,
                                        _effective(text), text[max(0,m.start()-45):m.end()+100], _authority(page.url)))
            if path in ('/personal/credit-cards', '/rates'):
                m = re.search(r'(?:Platinum Visa Rate|Lower ongoing rate[^:]*:)\s*\|?\s*(\d+(?:\.\d+)?)\s*%\s*[–-]\s*(\d+(?:\.\d+)?)\s*%', text, re.I)
                if m:
                    key = 'card', 'personal', 'Platinum Visa', (), 'APR', 'standard'
                    value = f'{float(m[1]):g}% - {float(m[2]):g}%'
                    claims.append(Claim(key, 'Platinum Visa standard APR', value, page.url, ctx.sid, ctx.date,
                                        '', text[:500], _authority(page.url)))
    return [c for c in claims if currently_valid(c.effective,ctx.date)]


def _rank(claim):
    return claim.effective, claim.authority, claim.observed, claim.url


def _canonical(claims):
    """Use product/table authority only after respecting local effective dates."""
    best_authority = max(c.authority for c in claims)
    eligible = [c for c in claims if c.authority >= best_authority - 1]
    # This excludes generic landing copies from dictating the current quote;
    # among official product/rate widgets their explicit dates decide.
    # A savings table whose nominal dividend exceeds its published APY is
    # internally inconsistent; use a corroborating valid row for that exact
    # account/balance instead of elevating a copied rate-sheet typo.
    consistent = []
    for c in eligible:
        if c.key[0] == 'deposit' and c.key[4] == 'rate':
            numeric = [float(x) for x in re.findall(r'(\d+(?:\.\d+)?)\s*%', c.quote)]
            if len(numeric) == 2 and numeric[0] > numeric[1]:
                continue
        consistent.append(c)
    return max(consistent or eligible, key=_rank)


def _row_value(claim):
    if claim.key[0] != 'mortgage':
        return claim.value
    cells = [s.strip() for s in claim.quote.strip('|').split('|')]
    if len(cells) >= 5:
        rates = re.findall(r'\d+(?:\.\d+)?\s*%', cells[1])
        aprs = re.findall(r'\d+(?:\.\d+)?\s*%', cells[3])
        if rates and aprs:
            return rates[0] + ' / ' + aprs[0]
    return claim.value


def _raw_apy(claim):
    # The extractor has already selected the column by its metric header.
    # Re-reading a fixed cell index conflates dividend and APY when a balance
    # or account-name column is added. Preserve the typed measure instead.
    return claim.value


def _group(key):
    category, scope, product, qualifier, metric, phase = key
    # One conflict per repeated product/term; qualified values retain labels.
    # Do not inflate the report with one entry for nominal rate and one for APY.
    if category == 'auto':
        return category, scope, product, None, phase
    if category == 'loan':
        return category, scope, product, qualifier[0], phase
    if category == 'mortgage':
        return category, scope, product, None, phase
    if category == 'certificate':
        return category, scope, 'certificate special' if 'special' in product else product, qualifier[0], phase
    if category == 'ira' and 'special' in product:
        return category, scope, 'IRA certificate special', qualifier[0], phase
    return category, scope, product, qualifier, phase


def _term_label_conflicts(contexts, by_snapshot):
    """Find an IRA term mislabelled on a copy of the same rate table.

    Require a missing term, matching same-type APY and minimum, and corroboration
    from the other IRA type in the same widget. Merely sharing a rate is not
    enough to infer that two genuinely different certificates conflict.
    """
    out = {}
    for ctx in contexts:
        local = by_snapshot[ctx.sid]
        canonical = [c for cs in local.values() for c in cs
                     if c.key[0] == 'ira' and c.key[4] == 'APY'
                     and urlsplit(c.url).path.rstrip('/') == '/rates']
        others = [c for cs in local.values() for c in cs
                  if c.key[0] == 'ira' and c.key[4] == 'APY'
                  and urlsplit(c.url).path.rstrip('/') == '/personal/retirement']
        for claim in others:
            if any(c.key == claim.key for c in canonical):
                continue
            candidates = [c for c in canonical if c.key[:3] == claim.key[:3]
                          and c.key[3][1:] == claim.key[3][1:] and c.value == claim.value
                          and c.key[3][0] != claim.key[3][0]]
            if len({c.key for c in candidates}) != 1:
                continue
            winner = max(candidates, key=_rank)
            typ = 'traditional' if 'traditional' in claim.key[2] else 'roth'
            sibling = 'roth' if typ == 'traditional' else 'traditional'
            sibling_product = claim.key[2].replace(typ, sibling)
            if not any(c.key[2] == sibling_product and c.key[3] == winner.key[3]
                       and c.value == claim.value for c in others):
                continue
            key = claim.key[:3], winner.key[3]
            old_term, term = claim.key[3][0], winner.key[3][0]
            out[key] = {'topic': f'{typ.title()} IRA certificate special term label',
                        'values': [f'{old_term} months', f'{term} months'],
                        'sources': [claim.source(), winner.source()],
                        'resolution': f'{term} months',
                        'reason': f'The same {typ} IRA special and minimum balance have a {old_term}-month label on the copied retirement widget, '
                                  f'but the official table identifies {term} months for its matching APY. '
                                  'The other IRA type in the same widget corroborates that term; this is a copied term-label inconsistency, not a comparison of different IRA products.'}
    return list(out.values())


def _published_date(markdown):
    months = {name: i for i, name in enumerate(('January', 'February', 'March', 'April', 'May', 'June',
                                               'July', 'August', 'September', 'October', 'November', 'December'), 1)}
    match = re.search(r'\b(' + '|'.join(months) + r')\s+(\d{1,2}),\s*(20\d\d)\b', markdown[:1200])
    return f'{int(match[3]):04d}-{months[match[1]]:02d}-{int(match[2]):02d}' if match else ''


def _branch_conflicts(contexts):
    """One entity-level conflict for retained present-tense branch totals.

    Only count an explicit "has ... branch office locations" statement about
    the credit union. Historical event statistics, widgets, and biographies
    are excluded. Publication time resolves old organization boilerplate.
    """
    ctx = contexts[-1]
    observations = []
    for page in ctx.pages:
        path = urlsplit(page.url).path.lower()
        if not ('/newsroom/' in path or path in ('/about', '/about/what-is-dupaco')):
            continue
        for sentence in re.split(r'(?<=[.!?])\s+', clean(page.markdown)):
            match = re.search(r'\b(?:It|Dupaco) has\s+(?:[^.!?]{0,80}?\s+and\s+)?(\d+)\s+branch office locations\b', sentence, re.I)
            if not match:
                continue
            published = _published_date(page.markdown)
            observations.append(Claim(('entity', 'branch count'), 'Dupaco branch office count',
                                      f'{int(match[1])} branches', page.url, ctx.sid, ctx.date,
                                      published, sentence[:500], _authority(page.url)))
    if len({c.value for c in observations}) <= 1:
        return []
    winner = max(observations, key=lambda c: (c.effective, c.authority, c.url))
    representatives = {}
    for c in sorted(observations, key=lambda c: (c.effective, c.url)):
        representatives[c.value] = c
    sources = [c.source() for c in representatives.values()]
    return [{'topic': 'Dupaco current branch office count', 'values': list(representatives),
             'sources': sources, 'resolution': winner.value,
             'reason': 'Retained organization descriptions state different branch totals in the present tense. '
                       f'Use the latest explicit publication, {winner.effective}, in {winner.url}; '
                       'older releases and their boilerplate describe the organization before later branch changes. '
                       'Their totals remain historical and should not be assembled into a current answer.'}]


def _calendar_date(text):
    months = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December')
    aliases = {m.lower(): i for i, m in enumerate(months, 1)}
    aliases.update({m[:3].lower(): i for i, m in enumerate(months, 1)})
    match = re.search(r'\b(' + '|'.join(sorted(aliases, key=len, reverse=True)) + r')\.?\s+(\d{1,2}),?\s+(20\d\d)\b', text, re.I)
    if not match:
        return None
    month, day, year = aliases[match[1].lower()], int(match[2]), int(match[3])
    return f'{year:04d}-{month:02d}-{day:02d}', f'{months[month-1]} {day}, {year}'


def _source_local_conflicts(contexts):
    out = {}
    for ctx in contexts:
        for page in ctx.pages:
            path = urlsplit(page.url).path.rstrip('/')
            md = page.markdown
            # A table-local date and a repeated footnote date are competing
            # metadata for the same table, even if its rates did not change.
            lines = md.splitlines()
            for headers, rows, heading, effective, start in _tables(md):
                if not rows or not any('apy' in h.lower() for h in headers):
                    continue
                end = start + len(rows) + 2
                tail = []
                for line in lines[end:end+12]:
                    if line.strip().startswith('|'):
                        break
                    tail.append(line)
                raw_dates = re.findall(r'(?:effective(?:\s+as\s+of)?)\s*(\d{1,2}/\d{1,2}/\d{2,4})', clean('\n'.join(tail)), re.I)
                dates = list(dict.fromkeys(raw_dates))
                if len(dates) < 2:
                    continue
                name = rows[0][0][0] if _norm(headers[0]) == 'account type' else heading
                key = _norm(name), 'effective date'
                quote = clean('\n'.join(tail))[:600]
                source = {'url': page.url, 'snapshot_id': ctx.sid, 'quote': quote}
                if key in out and out[key]['values'] == dates:
                    if source not in out[key]['sources']:
                        out[key]['sources'].append(source)
                    continue
                out[key] = {'topic': f'{name} table effective date', 'values': dates,
                            'sources': [source],
                            'resolution': dates[0], 'reason': f'The date immediately attached to the table governs its rates in {ctx.sid}. '
                            'A different date in the following duplicated general footnote is stale metadata; source locality takes priority.'}
            if '/newsroom/' in path or '/learn/blog/' in path:
                continue
            # Current banner and older operational body, qualified by cycle.
            banner = re.search(r'Application period begins\s+([^\n]+)', clean(md[:2200]), re.I)
            if banner:
                startdate = _calendar_date(banner[1])
                deadline = re.search(r'(?:deadline date|applications? (?:must be submitted|are due)|deadline)\s*:?\s*([^\n]+)', clean(md), re.I)
                enddate = _calendar_date(deadline[1]) if deadline else None
                if startdate and enddate and enddate[0] < startdate[0]:
                    out[path, 'banner'] = {'topic': f'{clean(page.title)} application period status',
                                          'values': [startdate[1], enddate[1]],
                                          'sources': [{'url': page.url, 'snapshot_id': ctx.sid, 'quote': banner[0][:400]},
                                                      {'url': page.url, 'snapshot_id': ctx.sid, 'quote': deadline[0][:400]}],
                                          'resolution': startdate[1],
                                          'reason': 'The current application banner identifies the forthcoming cycle. The earlier deadline in the body belongs to the elapsed cycle and must not be interpreted as the next opening.'}
            nextcycle = re.search(r'next grant cycle begins in\s+(20\d\d)', clean(md), re.I)
            elapsed = re.search(r'Applications due:\s*([A-Za-z]+\s+\d{1,2},\s*20\d\d)', clean(md), re.I)
            if nextcycle and elapsed:
                due = _calendar_date(elapsed[1])
                if due and due[0] < ctx.date and int(nextcycle[1]) > int(ctx.date[:4]):
                    program = clean(page.title) if 'grant' in page.title.lower() else 'Nonprofit Grant'
                    out[path, 'cycle'] = {'topic': f'{program} grant cycle application status',
                                         'values': [nextcycle[0], due[1]],
                                         'sources': [{'url': page.url, 'snapshot_id': ctx.sid, 'quote': nextcycle[0]},
                                                     {'url': page.url, 'snapshot_id': ctx.sid, 'quote': elapsed[0]}],
                                         'resolution': nextcycle[0],
                                         'reason': 'The elapsed annual timeline remains valid history. The current How to Apply instruction refers to a future cycle; applications are not currently open merely because the old schedule remains on the page.'}
    return list(out.values())


def _branch_closure_conflicts(contexts):
    ctx = contexts[-1]
    forms = [p for p in ctx.pages if 'Select a Branch' in p.markdown]
    out = []
    for page in ctx.pages:
        text = clean(page.markdown)
        if '/newsroom/' not in page.url:
            continue
        sentence = re.search(r'[^.!?]*(?:last day of service|(?:location|branch) will close)[^!?(]*?(?:20\d\d)\.', text, re.I)
        if not sentence:
            continue
        action = re.search(r'(?:last day of service|(?:location|branch) will close)(.*)', sentence[0], re.I)
        date = _calendar_date(action[1]) if action else None
        if not date or date[0] > ctx.date:
            continue
        # Match branch identities from visible selectors to the announcement;
        # this is an operational claim, even when the hosting article is old.
        for form in forms:
            selector = re.search(r'Select a Branch([^\n]+)', form.markdown)
            if not selector:
                continue
            options = re.findall(r'([A-Z][a-z]+(?: [A-Z][a-z]+)?:.*?)(?=[A-Z][a-z]+(?: [A-Z][a-z]+)?:|$)', selector[1])
            for option in options:
                words = re.findall(r'[a-z]+', option.lower())
                distinctive = [w for w in words if len(w) >= 3 and w not in ('road', 'street', 'dubuque', 'select')]
                # Identify the location being closed, before any paragraph that
                # recommends alternative branches. Otherwise an alternative
                # such as Key West can be falsely labelled as closed.
                closure_end = text.lower().find(action[0].lower()) if action else -1
                target_text = text[:closure_end+len(action[0])] if closure_end >= 0 else sentence[0]
                matches = [w for w in distinctive if re.search(r'\b'+re.escape(w)+r'\b', target_text, re.I)]
                if len(matches) < 2:
                    continue
                topic = option.replace('So.', 'South').replace('Rd.', 'Road').strip() + ' branch closure status'
                if any(c['topic'] == topic for c in out):
                    continue
                out.append({'topic': topic, 'values': [f'Closed {date[1]}', f'Selectable branch: {option}'],
                            'sources': [{'url': page.url, 'snapshot_id': ctx.sid, 'quote': sentence[0][:500]},
                                        {'url': form.url, 'snapshot_id': ctx.sid, 'quote': option}],
                            'resolution': f'Closed {date[1]}',
                            'reason': 'The dated closure announcement is effective before the selected snapshot. A retained selectable branch in a live contact form is stale operational content and does not establish that the branch is still operating.'})
    return out


def _typed_fact_conflicts(contexts):
    try:
        import facts
    except ImportError:
        return []
    records = facts.claims(contexts[-1])
    groups = defaultdict(list)
    for claim in records:
        if claim.get('metric') in ('members', 'assets', 'counties', 'bright_track_insights', 'branches'):
            groups[claim['key']].append(claim)
    out = []
    for key, claims in groups.items():
        valid = [c for c in claims if not c.get('invalid')]
        if not valid or len({str(c['value']) for c in claims}) < 2:
            continue
        metric = valid[0]['metric']
        if metric == 'counties':
            winner = max(valid, key=lambda c: (c.get('authority', 0), c.get('report_date') or ''))
        else:
            winner = max(valid, key=lambda c: (c.get('report_date') or '', c.get('authority', 0)))
        values, sources = [], []
        for c in claims:
            value = str(c['value'])
            if value not in values:
                values.append(value)
                p = c['page']
                sources.append({'url': p.url, 'snapshot_id': c.get('snapshot_id', contexts[-1].sid), 'quote': c.get('quote')})
        titles = {'members': 'membership member count', 'assets': 'total assets financial strength',
                  'counties': 'county footprint counties', 'bright_track_insights': 'Bright Track personalized insights',
                  'branches': 'branch count branch office locations'}
        out.append({'topic': titles[metric], 'values': values, 'sources': sources, 'resolution': str(winner['value']),
                    'reason': 'Current-state resolution among retained source copies. Prefer the newest explicitly dated financial/report panel, with source authority and precise entity attribution; current charter descriptions outrank historical boilerplate. '
                              'Dated cumulative totals remain valid history, and invalid zero/NaN counters are render artifacts rather than valid measurements.'})
    return out


def _version_conflicts(contexts):
    groups = defaultdict(list)
    for ctx in contexts:
        for page in ctx.pages:
            path = urlsplit(page.url).path.rstrip('/')
            if '/newsroom/' in path or '/learn/blog/' in path or '/about/' in path:
                continue
            text = clean(page.markdown)
            # Version history belongs to a single application program. Hub
            # pages containing several programs need section-specific claims.
            if len(re.findall(r'Application period', text, re.I)) > 1:
                continue
            window = re.search(r'Application period:\s*((?:[A-Za-z]+\.?\s+\d{1,2})\s*[–-]\s*(?:[A-Za-z]+\.?\s+\d{1,2}),\s*20\d\d)', text, re.I)
            if window:
                value = window[1].replace('–', '-')
                groups[path, 'application period'].append((ctx, page, value, window[0]))
            if 'calculator' in path:
                example = re.search(r'After\s+(\d+)\s+months\s+your account balance would increase by\s*(\$[\d,]+)\s+reaching a total of\s*(\$[\d,]+)', text, re.I)
                if example:
                    groups[path, 'calculator default result', int(example[1])].append((ctx, page, example[2]+' / '+example[3], example[0]))
    out = []
    for key, points in groups.items():
        if len({p[2] for p in points}) < 2:
            continue
        values = list(dict.fromkeys(p[2] for p in points))
        latest = points[-1]
        topic = clean(latest[1].title) + ' ' + key[1] + ' version history'
        out.append({'topic': topic, 'values': values,
                    'sources': [{'url': p.url, 'snapshot_id': c.sid, 'quote': q[:500]} for c, p, _, q in points],
                    'resolution': latest[2] + '; ' + '; '.join(f'As of {c.date}: {v}' for c, _, v, _ in points),
                    'reason': 'Normal version history, not a simultaneous contradiction. The landing-page cycle or illustrative calculator output changed between captures; preserve the value for each requested snapshot. Calculator results are examples rather than offered product rates.'})
    return out


def collect(contexts):
    """Return snapshot-qualified disputes and explicitly identified histories.

    A dispute observed in August is resolved using August's pages. Later
    normal rate changes never retroactively replace that resolution.
    """
    if not contexts:
        return []
    contexts = sorted(contexts, key=lambda c: (c.date, c.sid))
    by_snapshot = {}
    for ctx in contexts:
        local = defaultdict(list)
        for claim in _extract(ctx):
            local[claim.key].append(claim)
        by_snapshot[ctx.sid] = local
    events = defaultdict(list)
    history = defaultdict(list)
    for ctx in contexts:
        for key, local in by_snapshot[ctx.sid].items():
            winner = _canonical(local)
            if len({c.value for c in local}) > 1:
                events[_group(key)].append((ctx, key, local, winner))
            if key[0] == 'certificate' and key[1] == 'personal':
                history[_group(key)].append((ctx, key, winner))
    results = []
    for group, observations in sorted(events.items(), key=lambda x: repr(x[0])):
        values, sources, resolutions = [], [], []
        seen_rows = set()
        for ctx, key, disputed, winner in observations:
            # Different measures of the same mortgage row are bundled only
            # after comparison. Rate/APR pairs preserve the source formatting.
            for claim in disputed:
                row = ctx.sid, _norm(claim.quote), claim.key[0]
                if claim.key[0] in ('auto', 'mortgage') and row in seen_rows:
                    continue
                seen_rows.add(row)
                topic = re.sub(r'\s+(rate|APR)$', ' rate / APR', claim.topic) if key[0] == 'mortgage' else claim.topic
                label = f'{ctx.date} {topic}: {_row_value(claim)}'
                if label not in values:
                    values.append(label)
                if claim.source() not in sources:
                    sources.append(claim.source())
            winner_topic = re.sub(r'\s+(rate|APR)$', ' rate / APR', winner.topic) if key[0] == 'mortgage' else winner.topic
            # Model-year expansion proves overlap; report each winning physical
            # row once, keeping its original qualification in the excerpt.
            if key[0] == 'auto':
                winner_topic = winner.quote.split('|')[1].strip() + f' {key[3][0]}-month auto loan APR'
            eligible=[c for c in disputed if c.authority>=max(d.authority for d in disputed)-1]
            top_rank=(_canonical(eligible).effective,_canonical(eligible).authority,_canonical(eligible).observed)
            tied=[c for c in eligible if (c.effective,c.authority,c.observed)==top_rank]
            unresolved=len({c.value for c in tied})>1 and len({c.authority for c in tied})==1
            resolution = (f'As of {ctx.date}, unresolved equal-authority disagreement for {winner_topic}' if unresolved else
                          f'As of {ctx.date}, {winner_topic}: {_row_value(winner)}')
            if resolution not in resolutions:
                resolutions.append(resolution)
        winner = observations[-1][3]
        category, scope, product, qualifier, phase = group
        if category == 'mortgage':
            kind = 'refinance' if 'refinance' in product else 'purchase'
            topic = f'{kind} mortgage rate / APR, matching term and loan amount tiers'
        elif category == 'auto':
            topic = f'{scope} {product} APR by term and matching model year'
        elif category in ('certificate', 'ira'):
            topic = f'{qualifier}-month {scope} {product} APY, same qualifying account'
        else:
            topic = re.sub(r'\s+(?:rate|APY|APR)$', '', winner.topic)
        reason = ('Contemporaneous pages disagree about matching product, term, balance, model year and measure. '
                  'Each dated resolution uses only that snapshot: the most recent local effective date among official product/rate tables outranks a stale embedded copy. '
                  'A corroborated valid dividend/APY row outranks an internally inconsistent copied row. '
                  'The timeline retains separately valid resolutions; subsequent ordinary rate changes do not overwrite an earlier dispute.')
        if any('unresolved' in item for item in resolutions):reason+=' Unresolved ties have no arbitrary URL-based winner.'
        results.append({'topic': topic, 'values': values, 'sources': sources,
                        'resolution': '; '.join(resolutions), 'reason': reason})
    # The contract also asks for across-snapshot versions. These are reported
    # as history, with an explicit explanation that normal changes are valid.
    for group, points in sorted(history.items(), key=lambda x: repr(x[0])):
        if group in events:
            continue
        qualified = defaultdict(list)
        for ctx, key, claim in points:
            qualified[key].append((ctx, claim))
        if not any(len({c.value for _, c in ps}) > 1 for ps in qualified.values()):
            continue
        category, scope, product, months, phase = group
        values, sources, resolutions = [], [], []
        for ctx in contexts:
            local = [(key, c) for cctx, key, c in points if cctx.sid == ctx.sid and key[4] == 'APY']
            if not local:
                continue
            local.sort(key=lambda x: ('jumbo' in x[0][2], x[0][3]))
            joined = ' / '.join(_raw_apy(c) for _, c in local)
            if joined not in values:
                values.append(joined)
            resolutions.append(f'As of {ctx.date}: {joined}')
            for _, c in local:
                if c.source() not in sources:
                    sources.append(c.source())
        if len(values) < 2:
            continue
        results.append({'topic': f'{months}-month {product} APY version history',
                        'values': values, 'sources': sources,
                        'resolution': 'Latest: ' + values[-1] + '. ' + '; '.join(resolutions),
                        'reason': 'Normal published rate change across dated snapshots, not a simultaneous contradiction. '
                                  'The APY schedule preserves separate standard and jumbo conditions in that order; apply the value for the requested snapshot.'})
    results.extend(_term_label_conflicts(contexts, by_snapshot))
    results.extend(_source_local_conflicts(contexts))
    results.extend(_branch_closure_conflicts(contexts))
    results.extend(_typed_fact_conflicts(contexts))
    results.extend(_version_conflicts(contexts))
    if not any('branch count' in c['topic'] for c in results):
        results.extend(_branch_conflicts(contexts))
    return results
