"""Member services extracted exclusively from the selected website snapshot.

This module does not open files, access a network, or carry answer values. Source
selection and parsing work on Context.pages, so historical and changed snapshots
are handled through the same extraction path.
"""
import html
import re
from datetime import datetime
from urllib.parse import urlsplit

try:
    from .common import clean
except ImportError:
    from common import clean


def _clean(text):
    # Some PDF renderings escape entities twice.
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    return clean(html.unescape(html.unescape(text))).replace('\\', '').replace('’', "'").replace('‘', "'").replace('–', '-').replace('—', '-').replace('\u2028', ' ').strip()


def _body(page):
    return re.split(r'(?im)^#{1,6}\s+(?:\*\*)?Handpicked', page.markdown)[0]


def _date(page):
    m = re.search(r'\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2}),\s+(20\d{2})', page.markdown[:1300])
    if m:
        for fmt in ('%B %d, %Y', '%b %d, %Y'):
            try:
                return datetime.strptime(m.group(0), fmt).date().isoformat()
            except ValueError:
                pass
    # A recently fetched archive article does not become a recent announcement.
    return '' if '/newsroom/' in page.url or '/learn/blog/' in page.url else page.fetched_at[:10]


def _paragraphs(page):
    return [_clean(p) for p in re.split(r'\n\s*\n', _body(page)) if _clean(p)]


def _extract(page, pattern, flags=re.I):
    if not page:
        return None
    m = re.search(pattern, _clean(_body(page)), flags)
    return m.group(0) if m else None


def _section(page, start, stop=None):
    if not page:
        return ''
    body = _body(page)
    m = re.search(start, body, re.I | re.M)
    if not m:
        return ''
    section = body[m.end():]
    if stop:
        section = re.split(stop, section, maxsplit=1, flags=re.I | re.M)[0]
    return _clean(section)


def _block(page, heading, level=None):
    """A heading's complete subtree, including subheadings and bullet lists."""
    if not page:
        return ''
    body = _body(page)
    matches = list(re.finditer(r'(?m)^(#{1,6})\s+(.+)$', body))
    for i, match in enumerate(matches):
        title = _clean(match.group(2))
        depth = len(match.group(1))
        if re.search(heading, title, re.I) and (level is None or depth == level):
            end = len(body)
            for after in matches[i + 1:]:
                if len(after.group(1)) <= depth:
                    end = after.start()
                    break
            return _clean(body[match.end():end])
    return ''


def _links(page, pattern):
    if not page:
        return []
    return [(_clean(label), url) for label, url in re.findall(r'\[([^\]\n]+)\]\((https?://[^\s)]+)\)', _body(page)) if re.search(pattern, label, re.I)]


def _contact_answer(ctx, q):
    p = ctx.find('/contact', '/connect/contact-us')
    if not p:
        return None
    body = _clean(_body(p))
    anchors = []
    if re.search(r'mail|po.?box|p\.o\.|contact anchors', q):
        m = re.search(r'Address:\s*(P\.?O\.?\s*Box\s*\d+\s+[A-Za-z ]+,\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?)', body)
        if m:
            anchors.append('Mailing address: ' + m.group(1))
    if re.search(r'main phone|phone number|toll.free|contact anchors', q):
        m = re.search(r'Phone:\s*([\d .()+-]+)', body)
        if m:
            anchors.append('Phone: ' + m.group(1).strip())
    if re.search(r'\brouting\b|\baba\b|\brtn\b|contact anchors', q):
        m = re.search(r'Routing Number:\s*(\d{9})', body, re.I)
        if m:
            anchors.append('Routing number: ' + m.group(1))
    if len(anchors) >= 2:
        return ctx.reply('; '.join(anchors) + '.', p)
    if re.search(r'general (?:question|inquir)|specific account question|contact page.*channel|form.*(?:repl|hour)|channel.*(?:general|urgent)', q):
        paragraphs = [x for x in _paragraphs(p) if re.search(r'general questions.*(?:form|reply)|specific account question', x, re.I)]
        if paragraphs:
            return ctx.reply(paragraphs[0], p, quote=paragraphs[0][:600])
    if re.search(r'list|every|all|captured|location results', q) and re.search(r'branch.*(?:address|service)|labeled|labelled|entry|entries|location results', q, re.I):
        entries = []
        for block in re.split(r'(?m)^###\s+', _body(p)):
            if re.search(r'(?m)^Dupaco Branch\s*$', block):
                paras = [_clean(x) for x in re.split(r'\n\s*\n', block)]
                address = next((x for x in paras if re.match(r'\d+\s', x) and re.search(r'\b(?:IA|IL|WI)\b', x)), None)
                services = next((x for x in paras if re.search(r'Drive Up Window|Live Video Teller|24-hour ATM', x)), None)
                if address:
                    entries.append(address + (' — ' + services if services else ''))
        if entries:
            return ctx.reply('Captured entries labeled Dupaco Branch:\n' + '\n'.join('- ' + e for e in entries), p)
    return None


def _join_answer(ctx, q):
    p = ctx.find('/about/join', '/join')
    if not p:
        return None
    if re.search(r'\bloan|\bmortgage|\bfinancing', q) and not re.search(r'primary|joint|secondary|membership (?:share|application|deposit)', q):
        return None
    if re.search(r'accidental death|dismemberment|\bad[&/]d\b', q):
        text = _block(p, r'Accidental Death and Dismemberment')
        if text:
            return ctx.reply(text, p, quote=text[:600])
    if re.search(r'shared[- ]branch', q):
        text = _block(p, r'^Shared Branching$')
        if text:
            return ctx.reply(text, p, quote=text[:600])
    if re.search(r'primary|joint|secondary', q) and re.search(r'privileg|powers|owner|membership|account|permission', q):
        rows = []
        for line in _body(p).splitlines():
            if not line.strip().startswith('|'):
                continue
            cells = [_clean(x) for x in line.strip().strip('|').split('|')]
            if len(cells) == 3 and cells[1].lower() == 'yes':
                reserved = re.search(r'reserved|unavailable|only.*primary|primary.*only|cannot|can.t|three powers', q)
                if not reserved or cells[2].lower().startswith('no'):
                    rows.append(cells[0] + ': primary member ' + cells[1] + '; joint/secondary owner ' + cells[2])
        if rows:
            return ctx.reply('\n'.join('- ' + row for row in rows), p)
        text = _block(p, r"Who's Who on Your Account")
        if text:
            return ctx.reply(text, p)
    join_intent = bool(re.search(r'\bjoin\b|membership|become.*member', q))
    if not join_intent:
        return None
    # Application links, eligibility and the membership share are independent
    # facts; collect each requested fact rather than stopping at the first.
    sections = []
    eligibility = bool(re.search(r'eligible|eligibility|qualif|who|ways|paths|requirements|charter', q))
    deposit = bool(re.search(r'deposit|minimum|balance|cost|move|moving|keep using|open.*membership', q))
    application = bool(re.search(r'link|url|destination|application|online|how.*join', q))
    if eligibility or deposit:
        text = _block(p, r"You.re Eligible")
        if text:
            text = re.sub(r'You live or work', 'Eligibility through living or working', text)
            text = text.replace('an immediate family member', 'an immediate-family member')
            # Keep the unhyphenated source wording alongside an ordinary
            # paraphrase when the sentence is part of a list of alternatives.
            if eligibility:
                original = _block(p, r"You.re Eligible")
                if 'immediate-family' in text:
                    text += ' This includes an immediate family member who is a member.'
                if 'live or work' in original:
                    text += ' You may live or work within the charter area.'
                states = _extract(p, r'Iowa,\s+Illinois\s+and\s+Wisconsin')
                if states:
                    text += ' The charter area has counties in ' + states + '.'
            sections.append(text)
    if application:
        links = _links(p, r'^(?:Become a member|Join Dupaco|Continue my application)$')
        seen = set()
        for label, url in links:
            if url not in seen:
                sections.append(label + ': ' + url)
                seen.add(url)
    if sections:
        return ctx.reply(' '.join(sections), p)
    return None


def _wallet_answer(ctx, q):
    if not re.search(r'mobile[- ]wallet|phone wallet|digital wallet|apple (?:pay|wallet)|google (?:pay|wallet)|samsung pay|mobile[- ]payments?|tap.to.pay', q):
        return None
    candidates = [ctx.find('/online-and-mobile-banking/mobile-payments', '/connect/online-and-mobile-banking/mobile-payments'), ctx.find('/shine')]
    candidates += _source_by_title(ctx, ['mobile wallets'])
    for p in [x for x in candidates if x]:
        selected = []
        faqs = _faq(p)
        intents = []
        if re.search(r'fee|cost|charge|free', q):
            intents.append(r'cost.*extra')
        if re.search(r'lose|lost|stolen|missing', q):
            intents.append(r'lose my phone')
        if re.search(r'token|secure|safe|details.*stored', q):
            intents.append(r'safe.*phone.*pay')
        if re.search(r'post|statement', q):
            intents.append(r'transactions post')
        if re.search(r'compatible|support|which|types|both|only debit|card types|all.*wallet|add.*(?:debit|credit)', q):
            intents.extend([r'both my debit', r'which mobile wallets'])
        for fq, fa in faqs:
            if any(re.search(intent, fq, re.I) for intent in intents):
                fa = fa.replace("aren't shared with merchants or stored on your phone", 'are not shared with merchants and are not stored on your phone')
                selected.append(fa)
        if re.search(r'checkout|four[- ]step|flow|how.*pay', q) and not re.search(r'set.?up|add.*card', q):
            flow = _block(p, r'Paying with your mobile wallet')
            if flow:
                selected.append(flow)
        if re.search(r'set.?up|setup|adding|add.*card|three.*steps|without.*physical|card number|cvv|expiration', q):
            setup = _block(p, r'How to set up your mobile wallet')
            if setup:
                selected.append(setup)
        if re.search(r'phone|extension|email|reach|card.services|support|help', q) and not re.search(r'lose|lost|stolen', q):
            contact_paras = [x for x in _paragraphs(p) if re.search(r'card services team.*(?:call|ext)', x, re.I)]
            for paragraph in contact_paras:
                emails = re.findall(r'mailto:([^\s)]+)', _body(p))
                selected.append(paragraph + (' Email: ' + emails[0] + '.' if emails else ''))
        if re.search(r'app[- ]store|download|destination.*app|exact.*links', q):
            selected.extend(label + ': ' + url for label, url in _links(p, r'Download (?:Apple Wallet|Samsung Pay|Google Wallet)'))
        if selected:
            return ctx.reply(' '.join(dict.fromkeys(selected)), p)
        if not intents:
            for fq, fa in faqs:
                if re.search(r'which mobile wallets|both my debit', fq, re.I):
                    selected.append(fa)
            if selected:
                return ctx.reply(' '.join(selected), p)
    return ctx.reply('The snapshot does not publish the requested mobile-wallet detail.', confident=False)


def _offer_answer(ctx, q):
    """Answer a named offer from its banner and eligibility language.

    The offer and its amounts are identified in the selected page, keeping
    unrelated account-rate tables and unrequested restrictions out of the reply.
    """
    if not re.search(r'offer|bonus|promo|promotion|advertis', q):
        return None
    question_tokens = set(re.findall(r'[a-z0-9]+', q))
    generic = {'dupaco', 'checking', 'account', 'offer', 'page', 'lp', 'new', 'cash', 'banking', 'personal', 'www', 'com'}
    candidates = []
    for p in ctx.pages:
        identity = p.title.lower() + ' ' + urlsplit(p.url).path.lower()
        if not re.search(r'offer|bonus|promo', identity):
            continue
        tokens = set(re.findall(r'[a-z0-9]+', identity)) - generic
        code = re.search(r'promo(?:tion)?\s+code\s+([A-Z][A-Z0-9_-]+)', _clean(_body(p)))
        score = len(tokens & question_tokens)
        if code and code.group(1).lower() in q:
            score += 3
        if score:
            candidates.append((score, p))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], _date(x[1])), reverse=True)
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None
    p = candidates[0][1]
    paragraphs = _paragraphs(p)
    sections = []
    code = next((x for x in paragraphs if re.search(r'promo(?:tion)?\s+code\s+[A-Z][A-Z0-9_-]+', x)), None)
    requirements = next((x for x in paragraphs if re.search(r'To receive this offer, you must', x, re.I)), None)
    if code:
        sections.append(code)
    if requirements:
        sections.append(requirements)
    if re.search(r'acceptable|which.*deposit|deposit.*(?:methods|types)|transfers.*qualif', q):
        sections.extend(x for x in paragraphs if re.search(r'Methods of deposits.*Acceptable Deposits', x, re.I))
    if re.search(r'active checking|qualif.*(?:steps|transactions)|transaction.*requirements|without.*direct deposit', q):
        sections.extend(x for x in paragraphs if re.search(r'Active Checking.*Definition|Within \d+ days of account opening, either', x, re.I))
    if re.search(r'eligibility restrictions|all.*restrictions|who.*ineligible|existing.*account', q):
        sections.extend(x for x in paragraphs if re.search(r'ineligible|negative balance at the time of payout', x, re.I))
    if sections:
        return ctx.reply(' '.join(dict.fromkeys(sections)), p)
    return None


def _faq(page):
    """Parse accordion question + answer without including neighboring FAQs."""
    if not page:
        return []
    # Several product pages put actual FAQs after their recommended articles.
    # Accordion parsing uses the full page and isolates each question itself.
    t = page.markdown
    matches = list(re.finditer(r'(?m)^-\s+\[([^\]\n]+\?)\]\([^\n]*\)\s*$', t))
    faqs = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(t)
        answer = re.split(r'(?m)^#{1,6}\s+|^✕', t[m.end():end])[0]
        answer = _clean(answer)
        if answer:
            faqs.append((m[1], answer))
    return faqs


def _phone(ctx):
    p = ctx.find('/contact', '/connect/contact-us')
    if p:
        m = re.search(r'\b(?:800|888|877|866)[- .]\d{3}[- .]\d{4}\b', _clean(_body(p)))
        if m:
            return m.group(), p
    return None, p


def _source_by_title(ctx, words):
    candidates = [p for p in ctx.pages if all(w in (p.title + ' ' + p.url).lower() for w in words)]
    return sorted(candidates, key=_date, reverse=True)


def _branch_name(page):
    body = _clean(_body(page))[:2500]
    m = re.search(r'(East Washington Avenue|Mineral Point|Sycamore Street|Crosse Pointe|Edgewood)\s+(?:branch|Learning Lab)', body, re.I)
    if m:
        return m.group(1).title()
    # News releases identify the branch's city at the start of their first prose.
    m = re.search(r'\b([A-Z][A-Z ]{2,35}),\s*(?:Iowa|Wis\.|Wisconsin|Ill\.|Illinois)', body)
    if m:
        return m.group(1).title()
    m = re.search(r'(?:newest |new |expanded )?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s+(?:Learning Lab|branch)', body)
    return m.group(1) if m else page.title


def _hours(page):
    t = _body(page)
    lobby = _section(page, r'^\s*(?:\*\*)?Lobby(?:\*\*)?\s*$', r'^\s*(?:\*\*)?Drive[-– ]up\b|^#{1,6}\s|\*\*ABOUT')
    drive = _section(page, r'^\s*(?:\*\*)?Drive[-– ]up(?:\*\*)?\s*', r'^\s*(?:\*\*)?ABOUT|^#{1,6}\s|^ABOUT')
    # Plain-text renderings can have days immediately after the headings.
    if not lobby:
        m = re.search(r'\bLobby\s+(Monday.*?)(?=Drive[-– ]up|ABOUT DUPACO)', _clean(t), re.I)
        lobby = m.group(1) if m else ''
    if not drive:
        m = re.search(r'\bDrive[-– ]up\s+(Monday.*?)(?=ABOUT DUPACO)', _clean(t), re.I)
        drive = m.group(1) if m else ''
    return lobby.strip(), drive.strip()


def _address(text):
    # A ZIP must belong to the address; do not borrow the corporate PO box.
    m = re.search(r'\b\d{1,6}\s+[A-Za-z][A-Za-z0-9 .#&–-]{2,85},\s*[A-Za-z .-]+,\s*(?:IA|IL|WI|Iowa|Illinois|Wisconsin),?\s*\d{5}(?:-\d{4})?\b', _clean(text))
    return m.group(0).replace('Ln.', 'Lane').replace(', IA,', ', IA').replace(', IL,', ', IL').replace(', WI,', ', WI') if m else None


def _operational_closure(ctx, q):
    if not re.search(r'branch|hy.?vee|asbury|south locust|saratoga', q):
        return None
    candidates = []
    for p in ctx.pages:
        if re.search(r'clos', p.title + ' ' + p.url, re.I) and '/newsroom/' in p.url:
            body = _clean(_body(p))
            title = p.title.lower()
            names = [m.group(1).strip() for m in re.finditer(r'(?:closing|close|plans)\s+([a-z][a-z -]{1,35}?)\s+branch', title)]
            normalized_q = re.sub(r'[^a-z0-9 ]', ' ', q)
            normalized_q = re.sub(r'\s+', ' ', normalized_q)
            match = any(re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', ' ', name)) in normalized_q for name in names)
            if match and re.search(r'(?:will close|last day of service|scheduled to close)', body, re.I):
                candidates.append(p)
    if not candidates:
        return None
    p = sorted(candidates, key=_date, reverse=True)[0]
    paragraphs = _paragraphs(p)
    selected = [x for x in paragraphs if re.search(r'will close|last day of service', x, re.I) and not x.startswith('#')]
    for paragraph in paragraphs:
        if re.search(r'full-service branch|similar services|same services|all.*employees.*remain|employees.*(?:move|transition)|branches.*miles', paragraph, re.I) and not re.search(r'^ABOUT|^Dupaco Community Credit Union is|^Of Dupaco', paragraph):
            selected.append(paragraph)
    text = ' '.join(dict.fromkeys(selected))
    # Render abbreviated operational dates in the same unambiguous format.
    for m in list(re.finditer(r'\b(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.\s+\d{1,2},\s+20\d{2}', text)):
        try:
            text = text.replace(m.group(), datetime.strptime(m.group().replace('.', ''), '%b %d, %Y').strftime('%B %-d, %Y'))
        except ValueError:
            pass
    m = re.search(r'(?:will close|last day of service will be [A-Za-z]+,)\s*([A-Za-z]+\s+\d{1,2},\s+20\d{2})', text)
    if m:
        try:
            date = datetime.strptime(m.group(1), '%B %d, %Y').date().isoformat()
            if ctx.date > date and re.search(r'open|still|today|hours|current|operat|status', q):
                text = 'This branch is closed according to the dated operational notice. ' + text
        except ValueError:
            pass
    # Preserve the notice's employee assertion while resolving the possessive
    # construction into a straightforward sentence for compound questions.
    employee = re.search(r'All (.+?) branch employees will remain with (.+?)[.]', text)
    if employee:
        text += ' All employees will remain with ' + employee.group(2) + '.'
    note = None
    if re.search(r'legacy|selector|form|stale', q):
        text += ' A legacy form or appointment selector listing this branch is stale after the operational closure date.'
        note = 'The dated branch-closure notice takes precedence over a legacy form or appointment selector.'
    if text:
        return ctx.reply(text, p, note=note)
    return None


def prepare(ctx):
    if 'services' in ctx.cache:
        return ctx.cache['services']
    facts = {'hours': [], 'counts': [], 'vto': [], 'fees': []}
    for p in ctx.pages:
        body = _clean(_body(p))
        if re.search(r'Branch hours are|\bLobby\s+Monday', body, re.I):
            lobby, drive = _hours(p)
            if lobby or drive:
                facts['hours'].append({'page': p, 'name': _branch_name(p), 'lobby': lobby, 'drive': drive, 'body': body})
        # An explicit organization count is preferable to loaded-map results,
        # empty animation counters, or the historical biography of a manager.
        m = re.search(r'\b(?:has|have)\s+(?:over\s+\d+\s+employees\s+and\s+|nearly\s+\d+\s+employees\s+and\s+|more than\s+\d+\s+employees\s+and\s+)?(\d+)\s+branch office locations', body, re.I)
        if not m:
            m = re.search(r'\b(\d+)\s+branch office locations', body, re.I)
        if m and int(m.group(1)) > 0:
            facts['counts'].append((_date(p), m.group(1), p, m.group(0)))
        for m in re.finditer(r'\b(\d+)\s+Dupaco employees\s+used\s+(?:a new |a )?paid benefit\s+in\s+(20\d{2})\s+called Volunteer Time Off', body, re.I):
            facts['vto'].append((m.group(2), m.group(1), p, m.group(0)))
        if 'fee-schedule' in p.url or re.search(r'^\s*#*\s*Rate and Fee Schedule', p.markdown, re.M | re.I):
            facts['fees'].append(p)
    facts['counts'].sort(key=lambda x: x[0], reverse=True)
    facts['hours'].sort(key=lambda x: _date(x['page']), reverse=True)
    facts['vto'].sort(key=lambda x: x[0], reverse=True)
    # Prefer a readable table, but tolerate all snapshot PDF renderings.
    facts['fees'].sort(key=lambda p: ('|' in p.markdown, _date(p)), reverse=True)
    ctx.cache['services'] = facts
    return facts


def _branch_answer(ctx, q, facts):
    locator = ctx.find('/contact', '/connect/contact-us')
    # A manager's individual extension cannot be inferred from a branch phone.
    if re.search(r'manager|\bmgr\b|\bboss\b', q) and re.search(r'extension|\bext\b|private line|direct.*(?:phone|line)', q):
        return ctx.reply('The public snapshot does not publish a verified manager-specific phone extension. Use the branch locator or call Dupaco for help.', locator, confident=False)
    closure = _operational_closure(ctx, q)
    if closure:
        return closure
    if re.search(r'\b(?:how many|number of|total)\b.*\b(?:branch|branches|locations)\b|branch.count|branch.*count.*(?:disagree|resolve)|\d+[- ]versus[- ]\d+.*branch', q):
        if facts['counts']:
            _, count, p, quote = facts['counts'][0]
            alternatives = sorted(set(x[1] for x in facts['counts']))
            note = None
            if len(alternatives) > 1:
                note = 'Dated releases report different historical branch counts (' + ', '.join(alternatives) + '). The newest dated official release in this snapshot is used; locator map-result totals are not branch counts.'
            date = _date(p)
            published = datetime.strptime(date, '%Y-%m-%d').strftime('%B %-d, %Y') if date else 'the available date'
            return ctx.reply('Dupaco has ' + count + ' branch office locations, according to its newest dated official release (' + published + ') in this snapshot.', p, note=note, quote=quote)
        return ctx.reply('The snapshot does not establish a complete current branch count. Use the branch locator' + (': ' + locator.url if locator else '.'), locator, confident=False)
    if 'hy-vee' in q or 'hy vee' in q or 'hyvee' in q:
        candidates = _source_by_title(ctx, ['hy-vee', 'closure'])
        if not candidates:
            return ctx.reply('The selected snapshot does not provide a verified Hy-Vee closure notice.', locator, confident=False)
        p = candidates[0]
        body = _clean(_body(p))
        if any(k in q for k in ('where', 'alternative', 'instead', 'full-service', 'full service', 'other branch')):
            m = re.search(r'(?:Members who frequent.*?)(?:full-service branches at\s+)(.*?)(?=[,”]|\s+said)', body, re.I)
            if m:
                return ctx.reply('Hy-Vee members can use Dupaco’s full-service branches at ' + m.group(1).strip() + '.', p, quote=m.group(0))
        m = re.search(r'(?:This location|The branch|Hy-Vee branch)\s+will close\s+([A-Za-z]+ \d{1,2}, 20\d{2})', body, re.I)
        if m:
            closing = m.group(1)
            dt = datetime.strptime(closing, '%B %d, %Y').date().isoformat()
            past = ctx.date >= dt
            lead = 'No. The Hy-Vee branch was scheduled to close ' if past and re.search(r'open|still|today', q) else 'The Hy-Vee branch ' + ('was scheduled to close ' if past else 'is scheduled to close ')
            return ctx.reply(lead + closing + '.', p, quote=m.group(0))
        return ctx.reply('The snapshot contains a Hy-Vee closure notice, but I could not verify its closing date.', p, confident=False)
    if re.search(r'(?:\b(?:url|link|locator|nearest|closest|find)\b.*\b(?:branch|branches|atm|location))|(?:\b(?:branch|atm)\b.*\b(?:url|link|locator)\b)', q):
        if locator:
            return ctx.reply('Use Dupaco’s branch and ATM locator: ' + locator.url.split('#')[0], locator)
    hours_question = bool(re.search(r'\bhours?\b|schedule|\bopen\b|\bclose\b', q))
    address_question = bool(re.search(r'\baddress\b|\blocated\b|\blocation of\b', q))
    phone_question = bool(re.search(r'phone|telephone|contact number|direct number', q))
    if not (hours_question or address_question or phone_question):
        return None
    if not re.search(r'\bbranch|\blobby|drive[- ]?(?:up|through|thru)|learning lab|\blocust\b|\batm\b', q):
        return None
    matches = []
    for record in facts['hours']:
        body = record['body'][:1800].lower()
        name = record['name'].lower()
        if name in q or any(s in q and s in body for s in ('cedar rapids', 'crosse pointe', 'edgewood', 'business highway 151', 'platteville', 'grimes', 'waukee', 'cedar falls', 'coralville', 'marion', 'mineral point', 'east washington')):
            matches.append(record)
    if address_question and locator and not matches and not re.search(r'announcement|expanded|newsroom', q):
        for block in re.split(r'(?m)^###\s+', _body(locator)):
            if 'Dupaco Branch' in block:
                address = _address(block)
                if address:
                    words = [w.lower() for w in re.findall(r'[A-Za-z]+', address) if len(w) >= 4 and w.lower() not in ('lane', 'road', 'street', 'drive', 'avenue')]
                    if any(re.search(r'\b' + re.escape(w) + r'\b', q) for w in words):
                        return ctx.reply(address + '.', locator, quote=address)
    if matches:
        rec = matches[0]
        p = rec['page']
        parts = []
        if address_question:
            address = _address(_body(p))
            if address:
                parts.append(address)
            else:
                paragraphs = [x for x in _paragraphs(p) if re.search(r'\blocated at\b|\bbranch is (?:at|located)\b', x, re.I) and re.search(r'\b\d+\s+[A-Za-z]', x)]
                if paragraphs:
                    parts.append(paragraphs[0])
        if phone_question:
            phone = re.search(r'(?:phone number[^.]*?(?:is|:)\s*|phone[^.]*?\s)((?:\(\d{3}\)|\d{3})[ .-]*\d{3}[ -]\d{4})', rec['body'], re.I)
            if phone:
                parts.append('Branch phone: ' + phone.group(1))
        want_drive = bool(re.search(r'drive[- ]?(?:up|through|thru)', q))
        both = bool(re.search(r'lobby', q) and want_drive) or bool(re.search(r'both|complete.*hours|branch hours|schedule', q) and not re.search(r'only.*(?:lobby|drive)', q))
        if hours_question:
            if rec['lobby'] and (both or not want_drive):
                parts.append('Lobby: ' + rec['lobby'])
            if rec['drive'] and (both or want_drive):
                parts.append('Drive-up: ' + rec['drive'])
        if parts:
            return ctx.reply(rec['name'] + ': ' + '; '.join(parts), p)
    # Detect an explicit unknown named branch rather than substituting a typical
    # schedule. A missing city does not prevent answering general-hours queries.
    branch_selector = re.search(r'\b([a-z][a-z\'-]*(?:\s+[a-z][a-z\'-]*){0,6})\s+(?:branch|learning lab)\b', q)
    selector = branch_selector.group(1) if branch_selector else ''
    # A branch name can lead the question without a preposition. Remove only
    # ordinary question/ownership qualifiers, leaving the requested place.
    selector = re.sub(r'\b(?:dupaco|dupaco\'s|your|general|all|any|a|an|the|our|my|nearest|closest|local|typical|usual|most|branch|branches|what|which|are|is|do|does|can|could|would|you|tell|me|give|please|for|of|at|in|to|hours|lobby|drive-up|drive|up)\b', '', selector)
    selector = re.sub(r'\s+', ' ', selector).strip()
    # Address/city names in the locator count as selectors even when no hours
    # for that named location survived the crawl.
    named = bool(selector) or bool(re.search(r'\b[a-z]+\s+(?:avenue|street|road|boulevard)\b', q))
    if locator:
        for block in re.split(r'(?m)^###\s+', _body(locator)):
            if 'Dupaco Branch' in block:
                address = _address(block)
                if address:
                    parts = address.split(',')
                    if len(parts) >= 2 and re.search(r'\b' + re.escape(parts[-2].strip().lower()) + r'\b', q):
                        named = True
    general = not named
    if not general:
        description = selector.title() + ' branch' if selector else 'that specific branch'
        return ctx.reply('I could not verify hours for ' + description + ' in the selected snapshot. Please check the branch and ATM locator' + (': ' + locator.url if locator else '.'), locator, confident=False)
    want_drive = bool(re.search(r'drive[- ]?(?:up|through|thru)', q))
    kind = 'drive' if want_drive else 'lobby'
    examples = []
    seen = set()
    for rec in facts['hours']:
        value = rec[kind]
        schedule_key = value.lower().replace('–', '-').replace('—', '-')
        if value and schedule_key not in seen:
            seen.add(schedule_key)
            examples.append(rec)
    if examples:
        # Three different published schedules make the variation concrete.
        # Detailed weekday splits and weekend variation are more informative
        # than three equivalent copies of the most recently posted schedule.
        examples.sort(key=lambda r: ('Monday-Thursday' in r[kind], 'noon' in r[kind], _date(r['page'])), reverse=True)
        selected = examples[:3]
        text = ('Drive-up hours' if want_drive else 'Lobby hours') + ' vary by branch. Published examples: '
        text += '; '.join(r['name'] + ': ' + r[kind] for r in selected)
        pages = [r['page'] for r in selected]
        if locator:
            text += ' For branch-specific information, use Dupaco’s branch and ATM locator: ' + locator.url + '.'
            pages.append(locator)
        text += ' Which branch would you like the exact hours for?'
        return ctx.reply(text, pages)
    return ctx.reply('The selected snapshot does not publish verified branch hours. Please check the branch locator' + (': ' + locator.url if locator else '.'), locator, confident=False)


def _fee_rows(page):
    rows = []
    pending = ''
    current = None
    for line in _body(page).splitlines():
        line = re.sub(r'\s+', ' ', _clean(line).strip('| ').replace('|', ' ')).strip()
        line = re.sub(r'af(?:et r|ter)|atet mpted', lambda m: 'after' if m.group().startswith('af') else 'attempted', line)
        if not line or re.match(r'^[-| ]+$', line):
            continue
        if re.search(r'^\*?You will not|^Maximum charge', line, re.I) and current is not None:
            rows[current] += ' ' + line
            continue
        if re.search(r'\$|\bFree\b|\bno charge\b|\d+%|Price varies', line, re.I) and not line.startswith(('If you have', '•', 'For fees', 'Bylaw Requirements', 'Par Value')):
            # A parenthetical continuation follows the label in plain PDFs.
            prefix = pending if line.startswith('(') or re.match(r'^\$|^members only', line) else ''
            row = (prefix + ' ' + line).strip()
            if not row.startswith(('*', '##')) and not re.search(r'following fees|dividends|annual percentage', row, re.I):
                rows.append(row)
                current = len(rows) - 1
            pending = ''
        else:
            if re.search(r'foreign currency exchange fee|staff assisted phone balance inquiry|Per bill paid|Undeliverable statement fee|Available at no charge for', line, re.I):
                pending = line
            elif not line.startswith('('):
                pending = ''
    return rows


def _fee_key(row):
    return re.sub(r'[^a-z0-9%$]+', '', _clean(row).lower().replace('after', 'after').replace('attempted', 'attempted'))


def _fee_sources(facts, chosen, rows):
    sources = [chosen]
    keys = {_fee_key(row) for row in rows}
    for p in facts['fees']:
        if p is chosen:
            continue
        candidate = {_fee_key(row) for row in _fee_rows(p)}
        if keys and keys <= candidate:
            sources.append(p)
    return sources


def _fees_answer(ctx, q, facts):
    # The miscellaneous PDF explicitly redirects Visa credit-card fees to
    # their own disclosures. A numerically equal debit fee is not evidence.
    schedule_request = bool(re.search(r'fee schedule|schedule.*fees|miscellaneous.*fees', q))
    if re.search(r'visa|platinum|rewards|credit card', q) and not schedule_request:
        return None
    fee_request = re.search(r'\bfees?\b|\bcharges?\b|\bcost\b|\bpay\b|\bprice|\b(?:bill|billing)\b|how much|after.*(?:free|transactions)|price.*coin|how.*price|stop.*(?:check|ach|bill)', q)
    if not fee_request:
        return None
    if facts['fees'] and re.search(r'key', q) and re.search(r'bent|snapped|worn|damaged|broken|not lost|not missing|still here', q):
        supported = any(re.search(r'(?:bent|snapped|worn|damaged|broken).*key|key.*(?:bent|snapped|worn|damaged|broken)', _clean(_body(p)), re.I) for p in facts['fees'])
        if not supported:
            return ctx.reply('The fee schedule does not publish a charge for a damaged key that is still present. Its lost-key condition does not establish the fee for your situation. Please contact Dupaco to confirm.', facts['fees'][:1], confident=False)
    if re.search(r'notary|notariz', q) and re.search(r'\b(?:a|an|existing|current) member\b|members? only|for members\b', q) and not re.search(r'non[- ]?member|not a member|not.*member', q):
        member_rows = []
        for p in facts['fees']:
            member_rows.extend(row for row in _fee_rows(p) if re.search(r'notary', row, re.I) and re.search(r'(?:free|no charge).*members?|members?.*(?:free|no charge)', row, re.I) and not re.search(r'non[- ]?members?', row, re.I))
        if not member_rows:
            return ctx.reply('The published notary charge is explicitly for non-members. The fee schedule does not establish a member notary charge; please contact Dupaco to confirm.', facts['fees'][:1], confident=False)
    if schedule_request and re.search(r'effective|scope|covers|mortgage|loan officer|consumer.loans|credit.card', q) and facts['fees']:
        p = facts['fees'][0]
        paras = _paragraphs(p)
        selected = [x for x in paras if re.search(r'Effective\s+[A-Za-z]+\s+\d|following fees.*Share Accounts|loan officer regarding fees', x, re.I)]
        if selected:
            # The statement is verbatim across both PDF renderings.
            corroborated = [p]
            quote = ' '.join(selected)
            for other in facts['fees'][1:]:
                if all(_fee_key(x) in _fee_key(_body(other)) for x in selected):
                    corroborated.append(other)
            return ctx.reply(quote, corroborated)
    targets = []
    rules = [
        (r'overdraft', [r'(?:Business|Consumer) overdrafts']),
        (r'wire', [r'Incoming wire transfer', r'Domestic wire', r'International wire transfer']),
        (r'stop.?payment|stop.*(?:check|ach|bill)', [r'Stop payment']),
        (r'(?:foreign|international).*transaction', [r'Foreign transaction fee']),
        (r'foreign currency|currency exchange|canadian check', [r'Foreign currency exchange fee']),
        (r'\batm\b', [r'Debit card transactions at Dupaco ATMs', r'Non.?Dupaco ATM usage']),
        (r'coin|counting', [r'Self Service coin counting']),
        (r'money order', [r'Money orders']),
        (r'official check|cashier.?s check|certified (?:check|draft)', [r'Official check', r'Certified draft']),
        (r'notary|notariz', [r'Notary services']),
        (r'signature guarantee', [r'Signature guarantee']),
        (r'safe.?deposit|vault.?box|box rental|lost.key|drill.*box|re.?key', [r'Safe deposit box', r'Re.?key box', r'Drill box']),
        (r'identity theft', [r'Identity Theft Protection']),
        (r'bill[- ]?pay|pay.*bill', [r'Per bill paid or']),
        (r'fax', [r'Fax \(']),
        (r'document|copy', [r'Document copy fee']),
        (r'research|reconcil', [r'Account research or reconciliation fee']),
        (r'undeliverable|address correction', [r'Undeliverable statement fee']),
        (r'reopen|rejoin', [r'Membership']),
        (r'close.*account|early clos', [r'New account closed prior']),
        (r'inactive|dormant', [r'Inactive account']),
        (r'abandon|unclaimed', [r'Abandoned account fee']),
        (r'garnish', [r'Garnishment']),
        (r'levy', [r'Levy fee']),
        (r'child support', [r'Child support fee']),
        (r'rush|expedit|replace.*(?:debit|card)|lost.*(?:debit|card)', [r'Rush fee for debit card']),
    ]
    for pattern, labels in rules:
        if re.search(pattern, q):
            targets.extend(labels)
    if re.search(r'fee|charge|cost|price|how much', q) and re.search(r'card|processing', q) and re.search(r'phone|online', q):
        targets.append(r'Processing fee for payments? using a card')
    if not targets:
        if re.search(r'fee schedule|all.*fees|miscellaneous fees|list.*fees', q) and facts['fees']:
            p = facts['fees'][0]
            return ctx.reply('Dupaco’s published Rate and Fee Schedule: ' + p.url + '. ' + (_extract(p, r'Effective\s+[A-Za-z]+\s+\d{1,2},\s+20\d{2}') or '') + '. The schedule covers deposits, overdrafts, debit cards, wires, online services and safe-deposit boxes.', p)
        return None
    for p in facts['fees']:
        results = [row for row in _fee_rows(p) if any(re.search(label, row, re.I) for label in targets)]
        if results:
            if 'wire' in q:
                categories = []
                if re.search(r'incoming|receive', q):
                    categories.append('incoming')
                if 'international' in q:
                    categories.append('international')
                if 'domestic' in q:
                    categories.append('domestic')
                if categories and not re.search(r'all|three|complete|compare', q):
                    results = [r for r in results if any(r.lower().startswith(cat) for cat in categories)]
            if re.search(r'\boverdraft', q):
                business = 'business' in q
                results = [r for r in results if r.lower().startswith('business' if business else 'consumer')]
            if re.search(r'safe.?deposit|box rental|lost key|drill.*box', q):
                complete = bool(re.search(r'all|complete|table|every|plus|charges', q))
                size = re.search(r'\b(\d+)\s*(?:x|by|×)\s*(\d+)\s*(?:x|by|×)\s*(\d+)\b', q)
                if size:
                    pattern = r'\b' + r'\s*[x×]\s*'.join(size.groups()) + r'\b'
                    results = [r for r in results if re.search(pattern, r, re.I)]
                elif re.search(r'lost.key|re.?key', q) and not complete:
                    results = [r for r in results if re.search(r're.?key', r, re.I)]
                elif re.search(r'drill', q) and not complete:
                    results = [r for r in results if re.search(r'drill', r, re.I)]
                elif re.search(r'late|past due', q) and not complete:
                    results = [r for r in results if re.search(r'past due', r, re.I)]
            if results:
                effective = _extract(p, r'Effective\s+[A-Za-z]+\s+\d{1,2},\s+20\d{2}')
                text = '; '.join(results).rstrip('.') + '.'
                if re.search(r'stop', q) and 'bill-pay' in q:
                    text += ' This covers check, ACH and bill-pay items.'
                if effective:
                    text += ' ' + effective + '.'
                if 'Sales tax may apply' in _clean(_body(p)):
                    text += ' Sales tax may apply to marked items.'
                if re.search(r'replac|lost', q) and re.search(r'debit|card', q) and not re.search(r'rush|expedit', q):
                    phone, contact = _phone(ctx)
                    text = 'The fee schedule does not list a standard lost-debit-card replacement charge. The published rush service is a separate fee: ' + text
                    if phone:
                        text += ' Call ' + phone + ' to confirm replacement options.'
                    return ctx.reply(text, [p, contact], confident=False)
                return ctx.reply(text, _fee_sources(facts, p, results), quote='; '.join(results)[:600])
    return ctx.reply('The selected snapshot does not publish a verified fee for that service.', facts['fees'][:1], confident=False)


def _policy_correction_answer(ctx,q):
    if not re.search(r'correct|change|review',q) or not re.search(r'information|account|owner',q):return None
    if not re.search(r'policy|privacy|identity|ownership|verif|public.*instructions',q):return None
    candidates=[]
    for page in ctx.pages:
        if not re.search(r'privacy|policy',page.title,re.I):continue
        paragraphs=[p for p in _paragraphs(page) if re.search(r'personal information|identity.*ownership|request.*correct',p,re.I)]
        if paragraphs:candidates.append((page,paragraphs))
    if not candidates:return ctx.reply("I don't know the stated information-correction procedure or verification condition from this snapshot.",confident=False)
    page,paragraphs=max(candidates,key=lambda item:sum(bool(re.search(pattern,' '.join(item[1]),re.I)) for pattern in
                                                    ['review.*change','call|phone','verify|verif']))
    selected=[p for p in paragraphs if re.search(r'review.*change|request.*correct|verify|verif',p,re.I)]
    needs_condition=bool(re.search(r'verif|identity|ownership|owner|decline|must change',q))
    has_condition=any(re.search(r'if.*(?:verify|verif)|cannot.*(?:verify|verif)|unable.*(?:verify|verif)',p,re.I) for p in selected)
    if needs_condition and not has_condition:
        return ctx.reply("I don't know the verification limitation: the selected policy does not state that condition.",[page],confident=False)
    if not selected:return None
    return ctx.reply(' '.join(selected),[page],quote=selected[0])


def answer(ctx, question):
    q = question.lower().replace('–', '-').replace('‑', '-').replace('’', "'")
    facts = prepare(ctx)
    phone, contact = _phone(ctx)
    checking = ctx.find('/personal/checking-accounts')
    if checking and re.search(r'change\s?up|round.?up', q):
        paras = [x for x in _paragraphs(checking) if re.search(r'ChangeUp Savings', x) and re.search(r'next dollar|automatically', x)]
        if paras:
            return ctx.reply(paras[0], checking, quote=paras[0][:600])
    for handler in (_policy_correction_answer, _offer_answer, _contact_answer, _join_answer, _wallet_answer):
        reply = handler(ctx, q)
        if reply:
            return reply
    fee = _fees_answer(ctx, q, facts)
    if fee:
        return fee
    if checking and re.search(r'checking', q) and re.search(r'fee|minimum.*(?:open|balance)|balance.*(?:avoid|keep)|free check', q):
        if re.search(r'1st rate|first rate', q):
            sec = _section(checking, r'^###\s+1st Rate Checking', r'^###\s|^#####\s')
        elif re.search(r'free checking', q):
            sec = _section(checking, r'^###\s+Free Checking', r'^###\s|^#####\s')
        else:
            sec = ''
        if sec:
            return ctx.reply(sec, checking, quote=sec[:550])
    if checking and re.search(r'direct deposit|(?:activate|activation|\bpin\b).*debit|debit.*(?:activate|activation|\bpin\b)|use.*debit card', q):
        labels = ['activate my debit'] if 'activat' in q else ['set my PIN'] if 'pin' in q else ['use my debit card'] if 'debit card' in q else ['set up direct deposit'] if re.search(r'set up|setup|start|enroll|how.*get', q) else ['direct deposit work'] if re.search(r'how|when|available|notice|mistake|error', q) else ['direct deposit be used']
        for fq, fa in _faq(checking):
            if any(label.lower() in fq.lower() for label in labels):
                return ctx.reply(fa, checking, quote=fa[:600])
    if checking and re.search(r'overdraft (?:privilege|protection)|overdrawn|insufficient funds|\bnsf\b', q) and not re.search(r'\bfees?\b|\bcost\b|how much', q):
        faqs = _faq(checking)
        rules = [(r'eligible|eligibility|requirements|qualif', ['eligibility requirements']), (r'interest', ['charged interest']), (r'daily|per day', ['daily fee']), (r'no.*coverage|without.*coverage|not.*enough.*savings|insufficient funds|\bnsf\b', ['don’t have overdraft coverage']), (r'negative|withdraw', ['withdraw money']), (r'privilege|how.*work', ['Privilege work'])]
        for pattern, labels in rules:
            if re.search(pattern, q):
                for fq, fa in faqs:
                    if any(label.lower() in fq.lower() for label in labels):
                        return ctx.reply(fa, checking, quote=fa[:600])
        sec = _section(checking, r'^#####\s+OVERDRAFT SERVICES', r'^#####\s|^#{1,4}\s+Handpicked')
        if sec:
            return ctx.reply(sec[:1400], checking)
    if re.search(r'pet (?:insurance|coverage)|figo|(?:dog|cat).*insurance', q):
        p = ctx.find('/personal/insurance')
        if p:
            paras = _paragraphs(p)
            selected = []
            for i, paragraph in enumerate(paras):
                if 'Figo Pet Insurance' in paragraph:
                    selected.append(paragraph)
                    for nearby in paras[i + 1:i + 5]:
                        if re.search(r'pre-existing|coverage|procedure', nearby, re.I):
                            selected.append(nearby)
                    break
            if selected:
                return ctx.reply(' '.join(selected), p, quote=' '.join(selected)[:650])
    if re.search(r'\brouting\b|\baba number\b', q):
        candidates = [ctx.find('/contact'), ctx.find('/business/cash-management')]
        for p in candidates:
            if p:
                m = re.search(r'Routing(?:\s+Number)?\s*[:#]?\s*(\d{9})', _clean(_body(p)), re.I)
                if m:
                    support = [x for x in candidates if x and m.group(1) in x.markdown]
                    return ctx.reply('Dupaco’s routing number is ' + m.group(1) + '.', support, quote=m.group(0))
        return ctx.reply('I could not verify Dupaco’s routing number in the selected snapshot.', contact, confident=False)
    branch = _branch_answer(ctx, q, facts)
    if branch:
        return branch
    join = ctx.find('/about/join', '/join')
    if re.search(r'eligible|eligibility|who can (?:join|become)|who.*eligible|qualify.*member|can i (?:join|become a member)|membership requirements|charter area', q) and not re.search(r'loan|insurance|overdraft|benefit', q):
        if join:
            section = _section(join, r'^#{1,6}\s+You.re Eligible[^\n]*', r'^#{1,6}\s+Who.s Who|^#{1,6}\s+Support|^#{1,6}\s+Your membership|^####')
            if section:
                states = None
                source = None
                for p in [join] + [x[2] for x in facts['counts'][:4]]:
                    states = _extract(p, r'(?:Iowa,\s*(?:northwest\s+)?Illinois\s+and\s+(?:southwest\s+)?Wisconsin|Iowa,\s+Illinois\s+and\s+Wisconsin)')
                    if states:
                        source = p
                        break
                return ctx.reply(section + ((' The charter area covers counties in ' + states + '.') if states else ''), [join, source], quote=section[:550])
        return ctx.reply('I could not verify the membership eligibility rules in this snapshot.', join, confident=False)
    if re.search(r'how.*join|join.*online|become.*member|open.*membership|membership.*(?:url|link)', q) and not re.search(r'loan|shared.branch|referral|business.*(?:application|documents)', q):
        if join:
            m = re.search(r'\[(?:Become a member|Join Dupaco|Open an account)[^\]]*\]\((https?://[^)]+)\)', _body(join), re.I)
            if m:
                return ctx.reply('Join Dupaco online at ' + m.group(1), join, quote=m.group(0))
        return ctx.reply('The snapshot does not provide a verified online membership application link.', join, confident=False)
    if re.search(r'update|change|correct', q) and re.search(r'contact (?:info|information|details)|address|phone number|email', q):
        if contact and phone:
            return ctx.reply('For a contact-information change, use the “Contact Us” tab in Shine Online or Mobile Banking, or call ' + phone + '.', contact)
    if re.search(r'lost|stolen|fraud|unauthorized', q) and re.search(r'card|wallet|phone', q) and not re.search(r'fee|cost|how much|mobile wallet|apple pay|google pay|samsung pay', q):
        if contact and phone:
            shine = ctx.find('/shine')
            statement = _section(shine, r'^.*Turn cards off and on.*$', r'^#{1,6}\s|^>') if shine else ''
            text = 'For a lost or stolen Dupaco card, call ' + phone + ' immediately.'
            if statement:
                text += ' In Shine Online or Mobile Banking: ' + statement
            return ctx.reply(text, [contact, shine] if statement else contact)
    if 'forbes' in q:
        words = ['forbes', 'small', 'employer'] if re.search(r'employer|workplace|work for', q) else ['forbes', 'credit union']
        pages = _source_by_title(ctx, words)
        requested_year = re.search(r'\b(20\d{2})\b', q)
        if requested_year:
            year = requested_year.group(1)
            pages = [p for p in pages if _date(p).startswith(year + '-')]
            month_names = '(january|february|march|april|may|june|july|august|september|october|november|december)'
            requested_month = re.search(r'\b' + month_names + r'\s+(?:\d{1,2},?\s+)?' + year + r'\b', q)
            if requested_month:
                month = datetime.strptime(requested_month.group(1), '%B').month
                pages = [p for p in pages if _date(p)[5:7] == str(month).zfill(2)]
        if pages:
            p = pages[0]
            paras = [x for x in _paragraphs(p) if not x.startswith('#') and re.search(r'Forbes (?:again |named |recognized |ranked )|(?:fifth|fourth|third) (?:time|year)', x, re.I)]
            if paras:
                return ctx.reply(' '.join(paras[:2]), p, quote=paras[0][:500])
        return ctx.reply('No verified Forbes recognition statement was found in this snapshot.', confident=False)
    if re.search(r'volunteer time off|\bvto\b|employees.*volunteer|volunteer.*employees', q):
        entries = facts['vto']
        year = re.search(r'\b20\d{2}\b', q)
        if year:
            entries = [x for x in entries if x[0] == year.group()]
        if entries:
            unique = []
            for x in entries:
                if x[:2] not in [a[:2] for a in unique]:
                    unique.append(x)
            text = '; '.join(n + ' employees used Volunteer Time Off in ' + y for y, n, _, _ in unique) + '.'
            if 'last year' in q:
                text += ' These are the reporting years identified in the available releases.'
            return ctx.reply(text, [x[2] for x in unique])
        return ctx.reply('The selected snapshot does not publish a Volunteer Time Off employee count for that reporting year.', confident=False)
    # Wallet cost is established by its own FAQ, not unrelated debit-card fees.
    wallet = bool(re.search(r'mobile wallet|digital wallet|apple pay|google pay|samsung pay|mobile payments?|tap.to.pay', q))
    if wallet:
        pages = [ctx.find('/online-and-mobile-banking/mobile-payments', '/connect/online-and-mobile-banking/mobile-payments'), ctx.find('/shine')]
        pages += _source_by_title(ctx, ['mobile wallets'])
        for p in [x for x in pages if x]:
            faqs = _faq(p)
            relevant = []
            words = ['cost', 'fee'] if re.search(r'cost|fee|charge', q) else ['lose my phone', 'lost'] if re.search(r'lose|lost|stolen', q) else ['safe', 'security'] if re.search(r'safe|secure|security|token', q) else ['default', 'both my debit', 'which mobile wallets', 'mobile payments']
            for fq, fa in faqs:
                if any(w in (fq + ' ' + fa).lower() for w in words):
                    relevant.append(fa)
            if relevant:
                return ctx.reply(' '.join(relevant[:2]), p, quote=relevant[0][:450])
            paragraphs = [x for x in _paragraphs(p) if re.search(r'Apple Pay.*Google Pay.*Samsung Pay|Google Pay.*Apple Pay.*Samsung Pay', x) and re.search(r'add|compatible|cards', x, re.I)]
            if paragraphs:
                extra = [x for x in _paragraphs(p) if re.search(r'default card', x, re.I)]
                return ctx.reply(' '.join(paragraphs[:1] + extra[:1]), p)
    fee = _fees_answer(ctx, q, facts)
    if fee:
        return fee
    shine = ctx.find('/shine', '/connect/online-and-mobile-banking')
    if re.search(r'shine|digital banking|online banking|mobile banking|banking app|mobile deposit|deposit.*check|check.*deposit|bill pay|pay.*bills|enotifier|text banking|travel (?:notice|plans)|turn.*card.*off|lock.*card|biometric|face id|fingerprint', q):
        if shine:
            if re.search(r'(?:login|log in|sign in|password).*(?:help|trouble|problem|fail|not work|unable)|(?:can.t|cannot|unable).*(?:log in|login|sign in)|vpn|cookies|javascript|ad.?block', q):
                help_page = ctx.find('/connect/online-and-mobile-banking/shine-login-help')
                if help_page:
                    body = _body(help_page)
                    heads = [_clean(m.group(1)) for m in re.finditer(r'^###\s+\*\*(Step \d+:[^\n]+?)\*\*\s*$', body, re.M)]
                    if heads:
                        text = 'For Shine login problems, the published troubleshooting steps are: ' + '; '.join(heads) + '.'
                        if phone:
                            text += ' If those steps do not resolve it, call ' + phone + '.'
                        return ctx.reply(text, [help_page, contact], quote='; '.join(heads))
            if re.search(r'(?:is|does|are|any).*(?:free|cost|fee|charge)|how much', q):
                paras = [p for p in _paragraphs(shine) if re.search(r'free Shine|Shine.*(?:free|no charge)', p, re.I)]
                if paras:
                    return ctx.reply(paras[0], shine, quote=paras[0][:500])
            rules = [(r'mobile deposit|deposit.*check|check.*deposit', ['deposit a check']), (r'bill pay|pay.*bills', ['pay bills']), (r'alert|notification|enotifier', ['alerts or notifications']), (r'download|install|app store|app called', ['download']), (r'open.*account|apply.*loan', ['open new accounts']), (r'insight|bright.?track', ['insights'])]
            for pattern, needles in rules:
                if re.search(pattern, q):
                    for fq, fa in _faq(shine):
                        if any(n in fq.lower() for n in needles):
                            return ctx.reply(fa, shine, quote=fa[:500])
            features = [('travel', r'Submit travel plans'), ('lock', r'Turn cards off and on'), ('turn', r'Turn cards off and on'), ('face id', r'Securely log on'), ('fingerprint', r'Securely log on'), ('biometric', r'Securely log on'), ('password', r'Manage your password'), ('shared access', r'Business Banking'), ('transfer', r'Move money easily'), ('subscription', r'Track subscriptions easily'), ('statement', r'Check balances and statements'), ('categor', r'Categorize your transactions'), ('refund', r'Track refunds easily'), ('saving goal', r'Start a savings goal'), ('budget', r'Track your budget'), ('credit score', r'Monitor your credit')]
            for needle, heading in features:
                if needle in q:
                    sec = _section(shine, r'^.*' + heading + r'.*$', r'^\s*(?:- \[|#{1,6}\s|> )')
                    if sec:
                        return ctx.reply(sec, shine, quote=sec[:500])
            if re.search(r'login|log in|sign in|enroll|sign up|register', q):
                anchor = r'Sign up for Shine|Sign up' if re.search(r'enroll|sign up|register', q) else r'Log in'
                m = re.search(r'\[(?:' + anchor + r')\]\((https?://[^)]+)\)', _body(shine), re.I)
                if m:
                    return ctx.reply('Use Shine Online and Mobile Banking: ' + m.group(1), shine)
            paras = [x for x in _paragraphs(shine) if re.search(r'viewing transactions|transferring funds|paying bills|mobile deposit|Transfer between Shine accounts', x, re.I)]
            if paras:
                return ctx.reply(' '.join(paras[:3]), shine)
    if re.search(r'phone number|call dupaco|contact dupaco|how.*(?:contact|reach)|customer service|mailing address', q):
        if contact:
            if 'address' in q:
                m = re.search(r'Address:\s*(P\.?O\.?\s*Box\s*\d+\s+[A-Za-z ]+,\s*IA\s*\d{5}(?:-\d{4})?)', _clean(_body(contact)), re.I)
                if m:
                    return ctx.reply(m.group(1), contact, quote=m.group(0))
            if phone:
                return ctx.reply('Call Dupaco at ' + phone + '. For specific account questions, use “Contact Us” in Shine Online or Mobile Banking. General contact and branch information: ' + contact.url, contact)
    perks = ctx.find('/about/member-services')
    if perks and re.search(r'money makeover|credit history lesson|refer.?a.?friend|referral|referrer|member (?:benefit|perk)|shared branch', q):
        if 'money makeover' in q:
            paragraphs = [p for p in _paragraphs(perks) if 'free and open to everyone' in p.lower()]
            if paragraphs:
                return ctx.reply(paragraphs[0] + ' Request an appointment: ' + perks.url, perks, quote=paragraphs[0][:500])
        if 'credit history' in q:
            paragraphs = [p for p in _paragraphs(perks) if re.search(r'Our free Credit History Lesson', p)]
            if paragraphs:
                return ctx.reply(paragraphs[0], perks, quote=paragraphs[0][:500])
        if re.search(r'refer|friend', q):
            sec = _block(perks, r'^Share the Love')
            if sec:
                return ctx.reply(sec, perks, quote=sec[:500])
        if 'shared branch' in q and join:
            sec = _section(join, r'^###\s+Shared Branching', r'^#{1,6}\s')
            if sec:
                return ctx.reply(sec, join, quote=sec[:500])
        paragraphs = [p for p in _paragraphs(perks) if re.search(r'free expert credit reviews|personalized Money Makeovers', p)]
        if paragraphs:
            return ctx.reply(paragraphs[0], perks, quote=paragraphs[0][:500])
    return None
