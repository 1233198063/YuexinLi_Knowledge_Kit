"""Dated institutional facts extracted only from the supplied full snapshot.

Financial reporting periods, program status headings and organizational scope
are retained separately from crawl time. ``claims`` exposes provenance-bearing
observations to the conflict collector; ``answer`` renders only the winner for
the question's metric. No evaluation data or filesystem is consulted.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlsplit

from common import clean


_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
           'July', 'August', 'September', 'October', 'November', 'December']
_MONTH = {m.lower(): i for i, m in enumerate(_MONTHS, 1)}
_MONTH.update({m[:3].lower(): i for i, m in enumerate(_MONTHS, 1)})
_MONTH['sept'] = 9
_DATE = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+20\d{2})?'
_NUM = r'\d[\d,]*(?:\.\d+)?'
_COUNT = r'(?:more than|over|nearly|approximately|about)?\s*' + _NUM + r'\+?'
_MONEY = r'\$\s*' + _NUM + r'(?:\s*(?:billion|million|thousand))?'


def _path(page):
    return urlsplit(page.url).path.rstrip('/').lower()


def _body(page):
    text = page.markdown
    return re.split(r'(?im)^#{1,3}\s+Handpicked for You\b', text)[0]


def _iso(value, year=None):
    value = clean(value).strip(' |.')
    m = re.search(r'\b(20\d{2})-(\d{2})-(\d{2})\b', value)
    if m:
        try:
            return date(*map(int, m.groups())).isoformat()
        except ValueError:
            return None
    m = re.search(r'([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?', value)
    if m and m[1].lower() in _MONTH and (m[3] or year):
        try:
            return date(int(m[3] or year), _MONTH[m[1].lower()], int(m[2])).isoformat()
        except ValueError:
            return None
    return None


def _pretty(day):
    if not day:
        return ''
    y, m, d = map(int, day.split('-'))
    return f'{_MONTHS[m - 1]} {d}, {y}'


def _number(value):
    m = re.search(_NUM, value)
    if not m:
        return None
    n = float(m[0].replace(',', ''))
    if 'billion' in value.lower():
        n *= 1_000_000_000
    elif 'million' in value.lower():
        n *= 1_000_000
    elif 'thousand' in value.lower():
        n *= 1_000
    return n


def _doc_date(page, text):
    """Use report/as-of or publication metadata, never unrelated footer dates."""
    matches = re.findall(r'\bAs of\s*:?\s*(' + _DATE + r'|20\d{2}-\d{2}-\d{2})', clean(text), re.I)
    dates = [_iso(s) for s in matches]
    dates = [s for s in dates if s]
    if dates:
        return max(dates)
    if '/newsroom/' in _path(page) or '/learn/blog/' in _path(page):
        m = re.search(_DATE, clean('\n'.join(text.splitlines()[:12])), re.I)
        return _iso(m[0]) if m else None
    m = re.search(r'(winter|spring|summer|fall|autumn)[-_ ]*(20\d{2})',
                  page.url + ' ' + page.title, re.I)
    if m:
        month = {'winter': 1, 'spring': 3, 'summer': 6, 'fall': 9, 'autumn': 9}[m[1].lower()]
        return f'{m[2]}-{month:02d}-01'
    return None


def _publication_date(page, text):
    """An as-of label for a different table is not an insight-count date."""
    if '/newsroom/' in _path(page) or '/learn/blog/' in _path(page):
        m = re.search(_DATE, clean('\n'.join(text.splitlines()[:12])), re.I)
        return _iso(m[0]) if m else None
    m = re.search(r'(winter|spring|summer|fall|autumn)[-_ ]*(20\d{2})',
                  page.url + ' ' + page.title, re.I)
    if m:
        month = {'winter': 1, 'spring': 3, 'summer': 6, 'fall': 9, 'autumn': 9}[m[1].lower()]
        return f'{m[2]}-{month:02d}-01'
    return None


def _authority(page, panel=False):
    path = _path(page)
    if panel:
        return 5.0
    if path == '/about':
        return 4.0
    if path.startswith('/newsroom/'):
        return 2.0
    if path.endswith('.pdf'):
        return 3.0
    return 1.0


def _claim(ctx, metric, value, page, quote, entity='institution', scope='current',
           report_date=None, authority=None, invalid=False, **extra):
    return {'key': (metric, entity, scope), 'metric': metric, 'entity': entity,
            'scope': scope, 'value': value, 'numeric': _number(value),
            'observed_at': ctx.date, 'report_date': report_date,
            'report_year': report_date[:4] if report_date else None,
            'authority': authority if authority is not None else _authority(page),
            'invalid': invalid, 'page': page, 'quote': quote,
            'snapshot_id': ctx.sid, **extra}


def _metric_claims(ctx, page):
    text = _body(page)
    body = clean(text)
    path = _path(page)
    # Consumer balances, arbitrary blog examples and recommendation links are
    # not institutional financial reports.
    if not (path == '/about' or path.startswith('/newsroom/') or
            (path.endswith('.pdf') and re.search(r'financial\s+strength|members\s*:', body, re.I))):
        return []
    docdate = _doc_date(page, text)
    records = []
    labels = {'members': 'Members', 'assets': 'Assets', 'deposits': 'Deposits',
              'loans': 'Loans', 'reserves': 'Reserves',
              'regulatory_net_worth': 'Regulatory Net Worth Ratio'}
    for metric, label in labels.items():
        value_pattern = _COUNT if metric == 'members' else _NUM + r'\s*%' if metric == 'regulatory_net_worth' else _MONEY
        for m in re.finditer(r'\b' + label + r'\s*:\s*(' + value_pattern + ')', body, re.I):
            value = m[1].strip()
            start = max(0, m.start() - 350)
            local = list(re.finditer(r'\bAs of\s*:?\s*(' + _DATE + ')', body[start:m.start()], re.I))
            observed = _iso(local[-1][1]) if local else docdate
            records.append(_claim(ctx, metric, value, page, m[0], report_date=observed,
                                  authority=_authority(page, panel=True)))
    # Official newsroom organizational profiles contain dated rounded counts.
    profiles = re.split(r'ABOUT\s+DUPACO\s+COMMUNITY\s+CREDIT\s+UNION', body, flags=re.I)
    profile = profiles[-1] if len(profiles) > 1 else body if path == '/about' else ''
    if profile:
        patterns = {
            'members': [r'membership\s+(?:has grown|grew)\s+to\s+(' + _COUNT + ')',
                        r'(' + _COUNT + r')\s+members\b'],
            'assets': [r'assets\s+(?:exceeding|of|totaling|totalling|at)\s+(' + _MONEY + ')',
                       r'(' + _MONEY + r')\s+(?:in\s+)?assets\b'],
            'counties': [r'\b(' + _NUM + r')\s+counties\b'],
        }
        for metric, pats in patterns.items():
            for pattern in pats:
                for m in re.finditer(pattern, profile, re.I):
                    value = m[1].strip() + (' counties' if metric == 'counties' else '')
                    records.append(_claim(ctx, metric, value, page, m[0], report_date=docdate))
    # Preserve malformed rendered counters as invalid evidence; never answer
    # with a zero or NaN when the live widget failed in the crawl.
    if path == '/about':
        for m in re.finditer(r'(?m)^#\s*(NaN|0\+?|[\d,]+)\s*\n\s*\n?#{1,6}\s*(Members|Total Assets|Branches)\b', text, re.I):
            metric = {'members': 'members', 'total assets': 'assets', 'branches': 'branches'}[m[2].lower()]
            records.append(_claim(ctx, metric, m[1], page, m[0], invalid=m[1].lower() == 'nan' or _number(m[1]) == 0))
    return records


def _insight_claims(ctx, page):
    text = _body(page)
    if not re.search(r'bright\s*track', clean(text), re.I):
        return []
    records = []
    pattern = r'Bright\s*Track(?:\s+has)?(?:\s+already)?\s+(?:has\s+)?delivered\s+((?:more\s+than\s+)?' + _NUM + r'\s*million\+?)\s+personalized\s+insights'
    for m in re.finditer(pattern, clean(text), re.I):
        records.append(_claim(ctx, 'bright_track_insights', m[1] + ' personalized insights', page,
                              m[0], entity='Bright Track', scope='cumulative',
                              report_date=_publication_date(page, text),
                              date_precision='publication'))
    return records


def _sections(page):
    """Retain complete topical sections, including paragraph and list children."""
    text = _body(page)
    result = []
    headings = list(re.finditer(r'(?m)^(#{1,6})\s+([^\n]+)$', text))
    for i, m in enumerate(headings):
        end = len(text)
        for n in headings[i + 1:]:
            if len(n[1]) <= len(m[1]):
                end = n.start()
                break
        result.append((clean(m[2]), text[m.start():end]))
    return result


def _leadership(ctx, page):
    results = []
    for title, section in _sections(page):
        if title.lower() not in ('senior leadership', 'board of directors'):
            continue
        scope = 'senior leadership' if 'senior' in title.lower() else 'board of directors'
        pairs = re.finditer(r'(?m)^####\s+([^\n]+)\n\s*\n######\s+([^\n]+)', section)
        for m in pairs:
            name = clean(m[1]); role = clean(m[2])
            if name.startswith('!') or role.startswith('!'):
                continue
            name = re.sub(r',\s*CCUV\b', '', name)
            results.append(_claim(ctx, 'governance_role', role, page, m[0], entity=name,
                                  scope=scope, authority=4.0))
    return results


def _program(ctx, page):
    """Extract status anchors and dates in canonical application instructions."""
    path = _path(page)
    if not re.search(r'scholarship|non-?profit.*grant|gift-of-innovation', path):
        return None, []
    if '/newsroom/' in path or '/learn/blog/' in path or path.endswith('.pdf'):
        return None, []
    text = _body(page); body = clean(text)
    name = ('Gift of Innovation' if 'gift-of-innovation' in path else
            'Nonprofit Grant' if re.search(r'non-?profit', path) else 'Scholarship')
    record = {'name': name, 'page': page, 'body': text, 'start': None,
              'end': None, 'banner': None, 'next_year': None}
    claims = []
    year = int(ctx.date[:4])
    for line in text.splitlines():
        line_text = clean(line.lstrip('# '))
        if re.search(r'Application period\s+(?:begins|opens|starts)', line_text, re.I):
            m = re.search(_DATE, line_text, re.I)
            if m:
                record['start'] = _iso(m[0], year)
                record['banner'] = line_text
        elif re.search(r'Application period\s*:', line_text, re.I):
            found = re.findall(_DATE, line_text, re.I)
            explicit_year = re.search(r'\b(20\d{2})\b', line_text)
            if len(found) >= 2:
                yy = int(explicit_year[1]) if explicit_year else year
                record['start'], record['end'] = _iso(found[0], yy), _iso(found[1], yy)
                record['banner'] = line_text
        elif re.search(r'Application opens\s*:', line_text, re.I) and not record['start']:
            m = re.search(_DATE, line_text, re.I)
            if m:
                record['start'] = _iso(m[0], year)
        elif re.search(r'Applications?\s+(?:due|deadline)\s*:', line_text, re.I):
            m = re.search(_DATE, line_text, re.I)
            if m:
                record['end'] = _iso(m[0], year)
        m = re.search(r'next\s+(?:grant|application)\s+cycle\s+begins\s+in\s+(20\d{2})', line_text, re.I)
        if m:
            record['next_year'] = m[1]
            record['next_quote'] = line_text
    # An expired lower-body deadline cannot overrule the newer status heading.
    if name == 'Scholarship' and not record['banner']:
        m = re.search(r'deadline date\s*:\s*(' + _DATE + ')', body, re.I)
        if m:
            record['end'] = _iso(m[1], year)
    for metric, value in (('application_start', record['start']), ('application_end', record['end'])):
        if value:
            claims.append(_claim(ctx, metric, value, page, record.get('banner') or
                                 next((clean(l) for l in text.splitlines() if _pretty(value) in clean(l)), ''),
                                 entity=name, scope=value[:4], authority=4.5 if record['banner'] else 3.0))
    status = 'not yet open' if record['start'] and ctx.date < record['start'] else 'closed' if record['end'] and ctx.date > record['end'] else 'open' if record['start'] else None
    if status:
        record['status'] = status
        claims.append(_claim(ctx, 'application_status', status, page,
                             record.get('banner') or record.get('next_quote') or '', entity=name,
                             scope='current', authority=4.5))
    return record, claims


def _calculator(ctx, page):
    if not re.search(r'certificate[- ]calculator', _path(page) + ' ' + page.title.lower()):
        return None, []
    body = clean(_body(page))
    pattern = r'After\s+(' + _NUM + r')\s+months?\s+your account balance would increase by\s+(' + _MONEY + r')\s+reaching a total of\s+(' + _MONEY + ')'
    m = re.search(pattern, body, re.I)
    if not m:
        return None, []
    deposit = re.search(r'Initial deposit.*?starting balance[^$]*(' + _MONEY + ')', body, re.I)
    item = {'page': page, 'months': m[1], 'gain': m[2], 'total': m[3],
            'deposit': deposit[1] if deposit else None, 'quote': m[0]}
    records = [_claim(ctx, metric, value, page, m[0], entity='certificate calculator',
                      scope='captured default', report_date=ctx.date, authority=4.0)
               for metric, value in [('calculator_gain', m[2]), ('calculator_total', m[3])]]
    return item, records


def _rank(claim):
    # Current About geography is a charter profile, not a cumulative report.
    if claim['metric'] in ('counties', 'governance_role'):
        return (claim['authority'], claim['report_date'] or '', _number(claim['value']) or 0)
    return (claim['report_date'] or '', claim['authority'], _number(claim['value']) or 0)


def prepare(ctx):
    if 'facts' in ctx.cache:
        return ctx.cache['facts']
    data = {'claims': [], 'resolved': {}, 'programs': [], 'calculators': [],
            'about': None, 'about_sections': []}
    for page in ctx.pages:
        if urlsplit(page.url).query or urlsplit(page.url).fragment:
            continue
        data['claims'].extend(_metric_claims(ctx, page))
        data['claims'].extend(_insight_claims(ctx, page))
        program, observations = _program(ctx, page)
        data['claims'].extend(observations)
        if program:
            data['programs'].append(program)
        calculator, observations = _calculator(ctx, page)
        data['claims'].extend(observations)
        if calculator:
            data['calculators'].append(calculator)
        if _path(page) == '/about':
            data['about'] = page
            data['about_sections'] = _sections(page)
            data['claims'].extend(_leadership(ctx, page))
    for claim in data['claims']:
        if claim['invalid']:
            continue
        key = claim['key']
        old = data['resolved'].get(key)
        if old is None or _rank(claim) > _rank(old):
            data['resolved'][key] = claim
    ctx.cache['facts'] = data
    return data


def claims(ctx):
    """All typed observations, including invalid captured widget values."""
    return list(prepare(ctx)['claims'])


def _words(n):
    small = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight',
             'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen',
             'sixteen', 'seventeen', 'eighteen', 'nineteen']
    if 0 <= n < 20:
        return small[n]
    if 20 <= n < 100:
        tens = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']
        return tens[n // 10] + ('-' + small[n % 10] if n % 10 else '')
    return str(n)


def _metric_answer(ctx, data, q):
    # Institutional totals are distinct from eligibility, account balances
    # and the number of awards in a named grant/scholarship program.
    if re.search(r'scholarship|\bgrant\b|credit card|account balance|who.*eligible|which counties.*(?:eligible|qualif)', q):
        return None
    metric = None
    if re.search(r'bright\s*track', q) and re.search(r'count|how many|insights|cumulative|delivered', q):
        metric = 'bright_track_insights'
    elif re.search(r'county[- ]based|county.*footprint|service footprint|county count|counties', q) and not re.search(r'which counties|list.*counties', q):
        metric = 'counties'
    elif re.search(r'\btotal assets?\b|\basset (?:figure|size|count)|\bassets?\b', q) and not re.search(r'insurance|pledge|collateral|personal financial', q):
        metric = 'assets'
    elif re.search(r'(?:membership|member|members)\s+(?:count|base|total|number)|how many\s+(?:people|members)|number of\s+members', q):
        metric = 'members'
    elif re.search(r'financial strength|institution.*(?:deposits|loans|reserves|net worth)', q):
        requested = [k for k in ('members', 'assets', 'deposits', 'loans', 'reserves', 'regulatory_net_worth') if k.replace('_', ' ') in q]
        metric = requested[0] if len(requested) == 1 else None
        if not metric:
            selected = [data['resolved'].get((k, 'institution', 'current')) for k in requested or ('members', 'assets', 'deposits', 'loans', 'reserves', 'regulatory_net_worth')]
            selected = [c for c in selected if c]
            if selected:
                return _render_claims(ctx, selected)
    if not metric:
        return None
    entity, scope = ('Bright Track', 'cumulative') if metric == 'bright_track_insights' else ('institution', 'current')
    selected = data['resolved'].get((metric, entity, scope))
    if selected is None:
        return ctx.reply("I don't know. This snapshot does not establish that institutional figure.", confident=False)
    return _render_claims(ctx, [selected])


def _render_claims(ctx, selected):
    sentences = []
    for c in selected:
        label = {'members': 'Dupaco membership', 'assets': 'Dupaco total assets',
                 'counties': 'Dupaco current county footprint',
                 'bright_track_insights': 'Bright Track has delivered',
                 'regulatory_net_worth': 'Regulatory Net Worth Ratio'}.get(c['metric'], c['metric'].title())
        text = label + ': ' + c['value']
        if c['report_date']:
            if c.get('date_precision') == 'publication':
                text += ' (from the newer dated publication)'
            else:
                text += ' (as of ' + _pretty(c['report_date']) + ')'
        sentences.append(text + '.')
    reason = 'The newer explicitly dated financial publication is used for current reporting figures; invalid dynamic counters and historical article boilerplate are not current observations.'
    if all(c['metric'] == 'counties' for c in selected):
        reason = 'The current institutional profile is used for the charter footprint; historical news profiles describe older footprints.'
    return ctx.reply(' '.join(sentences), [c['page'] for c in selected], note=reason,
                     quote='\n'.join(c['quote'] for c in selected))


def _program_answer(ctx, data, q):
    name = 'Gift of Innovation' if re.search(r'gift of innovation', q) else 'Nonprofit Grant' if re.search(r'non[- ]?profit.*grant', q) else 'Scholarship' if 'scholarship' in q else None
    if not name:
        return None
    program = next((r for r in data['programs'] if r['name'] == name), None)
    if not program:
        return None
    page = program['page']
    status_intent = re.search(r'application|apply|open|closed|period|window|deadline|cycle|when|dates?|still', q)
    if status_intent and (program['start'] or program['end'] or program['next_year']):
        start, end = program['start'], program['end']
        quote = program.get('banner') or program.get('next_quote')
        if program.get('next_year') and end and ctx.date > end:
            cycle = end[:4]
            text = (f'{name} is not currently open: the {cycle} application window has passed. '
                    f'The page directs applicants to the next grant cycle in {program["next_year"]}.')
        elif start and ctx.date < start:
            text = f'{name} applications are not yet open. The next application period begins {_pretty(start)}'
            if end:
                text += ' and ends ' + _pretty(end)
            text += '.'
        elif end and ctx.date > end:
            text = f'{name} applications are closed for the published cycle.'
        else:
            text = f'{name} application period'
            if start:
                text += ' begins ' + _pretty(start)
            if end:
                text += ' and ends ' + _pretty(end)
            text += '.'
        if program.get('banner'):
            text += ' Current page banner: ' + program['banner']
        return ctx.reply(text, page, note='The current status instruction or top application-period banner takes precedence over the older detailed cycle retained below.', quote=quote)
    # Non-numeric eligibility/about questions use the complete relevant page
    # section rather than one isolated bullet or a historical announcement.
    labels = [('eligib|who.*(?:apply|qualif)|requirements?', 'eligibility'),
              ('community pillars|focus areas|supported', 'community pillars'),
              ('session|value|what.*(?:offer|provide|program)', 'how the sessions work')]
    for pattern, heading in labels:
        if re.search(pattern, q):
            for title, section in _sections(page):
                if heading in title.lower():
                    return ctx.reply(clean(section)[:6000], page, quote=clean(section)[:600])
    return None


def _about_answer(ctx, data, q):
    page = data['about']
    if page is None:
        return None
    body = clean(_body(page))
    if re.search(r'mission|vision|stockholders?|cooperative ownership|return.*earnings', q):
        parts = []
        mission = re.search(r'Our mission is\s+(.+?)\.\s*Our vision is\s+(.+?)\.', body, re.I)
        ownership = re.search(r'As a cooperative, we (?:don.t|do not) have stockholders\.\s*We return earnings to you through\s+(.+?)\.', body, re.I)
        if mission:
            parts.append('Dupaco’s mission is ' + mission[1] + '. Its vision is ' + mission[2] + '.')
        if ownership:
            parts.append('As a cooperative, Dupaco has no stockholders and returns earnings to members through ' + ownership[1] + '.')
        if parts:
            quote = '\n'.join(m[0] for m in (mission, ownership) if m)
            return ctx.reply(' '.join(parts), page, quote=quote)
    if re.search(r'origin|found(?:ed|ing|ers)|organized|established|formed|started|start it|our story|workers|meatpacking|contribution|pool', q) and not re.search(r'grant|loan|interest|savings account', q):
        m = re.search(r'(?:Our story started|Founded)\s+in\s+(\d{4})\s+when\s+(' + _NUM + r')\s+(.+?)\s+pooled\s+(' + _MONEY + r')\s+each', body, re.I)
        if m:
            n = int(float(m[2].replace(',', ''))); amount = _number(m[4])
            dollars = _words(int(amount)) + ' dollars' if amount is not None and amount.is_integer() else m[4]
            text = (f'Dupaco began in {m[1]}: {_words(n).capitalize()} ({n}) {m[3]} '
                    f'pooled {m[4]} each—{dollars} apiece.')
            return ctx.reply(text, page, quote=m[0])
    governance = [c for c in data['claims'] if c['metric'] == 'governance_role']
    if re.search(r'senior leadership|executive (?:role|team)|chief (?:executive|people|operating|information|financial|marketing|member services) officer|\b(?:ceo|cfo|coo|cio|cmo)\b', q):
        selected = [c for c in governance if c['scope'] == 'senior leadership']
        if not re.search(r'every|all|list|each|team|senior leadership', q):
            matched = [c for c in selected if c['value'].lower() in q or c['entity'].lower() in q]
            titles = {'ceo': 'chief executive officer', 'cfo': 'chief financial officer',
                      'coo': 'chief operating officer', 'cio': 'chief information officer',
                      'cmo': 'chief marketing officer'}
            matched.extend(c for c in selected if any(re.search(r'\b' + k + r'\b', q) and v in c['value'].lower()
                                                      for k, v in titles.items()) and c not in matched)
            if matched:
                selected = matched
        if selected:
            return ctx.reply('; '.join(c['entity'] + ': ' + c['value'] for c in selected) + '.', page,
                             quote='\n'.join(c['quote'] for c in selected))
    if re.search(r'board of directors|elected board|officer positions|\b(?:chair|secretary|treasurer)\b', q) and not re.search(r'foundation', q):
        selected = [c for c in governance if c['scope'] == 'board of directors']
        if re.search(r'officer|chair|secretary|treasurer', q):
            selected = [c for c in selected if re.search(r'chair|secretary|treasurer', c['value'], re.I)]
        if selected:
            lead = ''
            m = re.search(r'Board of Directors is elected[^.]+\.', body, re.I)
            if m and re.search(r'elect|govern|how', q):
                lead = 'Dupaco’s ' + m[0] + ' '
            return ctx.reply(lead + '; '.join(c['entity'] + ': ' + c['value'] for c in selected) + '.', page,
                             quote='\n'.join(c['quote'] for c in selected))
    return None


def answer(ctx, question):
    q = question.lower().replace('–', '-').replace('‑', '-').replace('’', "'")
    data = prepare(ctx)
    if 'calculator' in q and re.search(r'certificate|\bcd\b', q):
        if not re.search(r'default|captur|example|output|result|show|increase|total|resolve', q):
            return None
        if not data['calculators']:
            return ctx.reply("I don't know. This snapshot does not contain a captured certificate-calculator result.", confident=False)
        calc = max(data['calculators'], key=lambda c: ('/calculators/' in _path(c['page']), len(c['page'].markdown)))
        months = int(float(calc['months']))
        text = 'The captured default certificate-calculator example'
        if calc['deposit']:
            text += ' starts with ' + calc['deposit']
        text += f' runs for {_words(months)} months ({months} months): ' if not calc['deposit'] else f' and runs for {_words(months)} months ({months} months): '
        text += 'the balance increases by ' + calc['gain'] + ' to ' + calc['total'] + '.'
        text += ' This is a captured illustrative calculator output, not a currently offered certificate rate.'
        return ctx.reply(text, calc['page'], quote=calc['quote'])
    for handler in (_metric_answer, _program_answer, _about_answer):
        result = handler(ctx, data, q)
        if result is not None:
            return result
    return None
