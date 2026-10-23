"""Deposit facts parsed from the requested snapshot's published rate tables.

This module never opens a file or contacts a service.  Product names, rates,
terms, balance tiers, minimums and effective dates come from Context.pages.
"""
import re
from datetime import datetime
from urllib.parse import urlsplit

from common import clean, term_months, requested_metrics
from evidence import deposit_identity,make_evidence,currently_valid,explicit_effective_date


def _norm(value):
    return re.sub(r"\s+", " ", clean(value).lower().translate(
        str.maketrans({"’": "'", "–": "-", "—": "-", "‑": "-", "\u00a0": " "}))).strip()


def _percent(value):
    m = re.search(r"(\d+(?:\.\d+)?|\.\d+)\s*%", value)
    return m[1] + "%" if m else None


def _term(value):
    parsed = term_months(value)
    if parsed is not None:
        return parsed
    q = _norm(value)
    m = re.search(r"(\d+)\s*[- ]?\s*(?:mos?\.?|mths?\.?)\b", q)
    if m:
        return int(m[1])
    units = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
             "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
             "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
             "fifty": 50, "sixty": 60}
    for m in re.finditer(r"\b([a-z]+)(?:[- ]([a-z]+))?[- ](months?|years?)\b", q):
        first, second, period = m.groups()
        if first in units and (second is None or second in units):
            return (units[first] + (units[second] if second else 0)) * (12 if period.startswith("year") else 1)
    if re.search(r"\bhalf[- ](?:a[- ])?year\b", q):
        return 6
    if re.search(r"\byear[- ]?long\b|\ba year\b", q):
        return 12
    return None


def _terms(value):
    """All explicitly requested terms, preserving coordinated term lists."""
    q = _norm(value)
    found = []
    for match in re.finditer(r"\b(?:\d+|[a-z]+(?:[- ][a-z]+)?)[- ](?:months?|years?|mos?\.?|mths?\.?|yrs?\.?)\b", q):
        term = _term(match[0])
        if term is not None:
            found.append(term)
    for match in re.finditer(r"\b(\d+)(?:\s*,\s*|\s+(?:and|or|versus|vs\.?)\s+)(\d+)\s*[- ]?\s*(months?|years?)\b", q):
        factor = 12 if match[3].startswith("year") else 1
        found.extend([int(match[1]) * factor, int(match[2]) * factor])
    if not found:
        term = _term(q)
        if term is not None:
            found.append(term)
    return list(dict.fromkeys(found))


def _money(value):
    m = re.search(r"\d[\d,]*(?:\.\d+)?", value)
    return float(m[0].replace(",", "")) if m else None


def _bounds(value):
    amounts = re.findall(r"\d[\d,]*(?:\.\d+)?", value)
    vals = [float(v.replace(",", "")) for v in amounts]
    if not vals:
        return (None, None)
    return vals[0], (vals[1] if len(vals) > 1 else float("inf") if "+" in value else vals[0])


_PRODUCTS = (
    ("bright savings", "Bright Savings"), ("launchpad", "Launchpad Savings"),
    ("high-yield", "High-Yield Savings"), ("high yield", "High-Yield Savings"),
    ("achieve", "Achieve Money Market"), ("investor", "Investor's Choice Money Market"),
    ("you-name-it", "You Name It Savings"), ("you name it", "You Name It Savings"),
    ("holiday", "Holiday Club Savings"), ("health savings", "Health Savings Account"),
    ("share savings", "Share Savings"), ("1st rate checking", "1st Rate Checking"),
    ("first rate checking", "1st Rate Checking"), ("free checking", "Free Checking"),
)


def _table_name(prefix, header):
    # Older tables omit the account-type column. Their immediately preceding
    # product heading is therefore part of the fact identity.
    for line in reversed(prefix.splitlines()):
        s = _norm(line).strip("# -")
        if not s or len(s) > 120 or line.lstrip().startswith("|"):
            continue
        for key, name in _PRODUCTS:
            if key in s:
                return name
    return ""


def _tables(page):
    text = page.markdown
    lines = text.splitlines(keepends=True)
    offsets = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line)
    rows = []
    i = 0
    while i < len(lines):
        if not lines[i].lstrip().startswith("|"):
            i += 1
            continue
        start = i
        block = []
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            block.append(lines[i].strip())
            i += 1
        header = [clean(c).lower() for c in block[0].strip("|").split("|")]
        divs = [j for j, c in enumerate(header) if "dividend" in c]
        apys = [j for j, c in enumerate(header) if "apy" in c or "annual percentage yield" in c]
        if not divs or not apys:
            continue
        # Tables can describe an introductory period alongside the subsequent
        # variable rate. Keep both periods under their published qualifiers.
        di, ai = divs[-1], apys[-1]
        names = [j for j, c in enumerate(header) if "account type" in c or "ira type" in c or c in ("certificate", "term")]
        tiers = [j for j, c in enumerate(header) if c in ("balance", "balance tier")]
        min_balances = [j for j, c in enumerate(header) if "min" in c and "balance" in c]
        max_balances = [j for j, c in enumerate(header) if "max" in c and "balance" in c]
        opens = [j for j, c in enumerate(header) if "open" in c]
        earns = [j for j, c in enumerate(header) if "earn" in c]
        default = _table_name(text[:offsets[start]], header)
        boundary = next((j for j in range(i, len(lines)) if lines[j].lstrip().startswith('|')), len(lines))
        following = "".join(lines[i:boundary])
        date_match = re.search(r"effective as of\s+(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})", following, re.I)
        effective = date_match[1] if date_match else explicit_effective_date(clean(following)) or None
        maintaining = re.search(r"(\$\s*\d[\d,]*(?:\.\d+)?)\s+minimum\s+balance\s+to\s+(?:open\s+(?:and|&)\s+)?maintain\b", clean(following), re.I)
        for line in block[1:]:
            cells = [clean(c) for c in line.strip("|").split("|")]
            if len(cells) <= max(di, ai):
                continue
            dividend, apy = _percent(cells[di]), _percent(cells[ai])
            if not dividend or not apy:
                continue
            name = cells[names[0]] if names else default
            tier = cells[tiers[0]] if tiers else ""
            if min_balances and max_balances:
                tier = cells[min_balances[0]] + " - " + cells[max_balances[0]]
            if re.match(r"(?:Roth|Traditional):", tier, re.I):
                name, tier = tier.split(":", 1)
                name = name.strip() + " Variable IRA"
                tier = tier.strip()
            if re.match(r"(?:Roth|Traditional):", name, re.I) and "$" in name:
                name, tier = name.split(":", 1)
                name = name.strip() + " Variable IRA"
                tier = tier.strip()
            term = _term(name)
            is_ira = "ira type" in " ".join(header) or bool(re.match(r"(?:Roth|Traditional)\b", name, re.I))
            family = "ira" if is_ira else "certificate" if term else "deposit"
            if family == "certificate" and "certificate" not in _norm(name):
                name += " Certificate"
            if family == "ira" and "ira" not in _norm(name):
                name += " IRA Certificate"
            if not name:
                continue
            lo, hi = _bounds(tier)
            row = dict(name=name, family=family, term=term, tier=tier,
                             dividend=dividend, apy=apy, lo=lo, hi=hi,
                             opening=cells[opens[0]] if opens else cells[min_balances[0]] if min_balances else None,
                             minimum=cells[earns[0]] if earns else None,
                             maintaining=maintaining[1] if maintaining else None,
                             effective=effective, page=page, quote=line, period="")
            if len(divs) > 1 and len(apys) > 1:
                row["period"] = re.sub(r"^dividend rate\s*", "", header[di], flags=re.I).strip()
                intro_div, intro_apy = _percent(cells[divs[0]]), _percent(cells[apys[0]])
                if intro_div and intro_apy:
                    intro = dict(row, dividend=intro_div, apy=intro_apy,
                                 period=re.sub(r"^dividend rate\s*", "", header[divs[0]], flags=re.I).strip())
                    rows.append(intro)
            rows.append(row)
    return rows


def _page(ctx, path):
    for page in ctx.pages:
        url = urlsplit(page.url)
        if url.path.rstrip("/") == path.rstrip("/") and not url.query and not url.fragment:
            return page
    return ctx.find(path)


def prepare(ctx):
    if "deposits" in ctx.cache:
        return ctx.cache["deposits"]
    # Product pages supply context and supersede incidental rates in articles.
    paths = ("/personal/savings-account", "/savings-account/online-savings-account",
             "/personal/checking-accounts", "/checking", "/personal/retirement",
             "/business/savings-accounts", "/business/checking-accounts",
             "/membermoneymarket-lp", "/newmembermoneymarket-lp", "/rates",
             "/business-rates", "/business/rates", "/earn-more")
    records = []
    seen_pages=set()
    for path in paths:
        page = _page(ctx, path)
        if page is None:
            continue
        if id(page) in seen_pages:continue
        seen_pages.add(id(page))
        for row in _tables(page):
            business = path.startswith("/business/") or path == "/business-rates"
            row["business"] = business
            if business and "business" not in _norm(row["name"]):
                row["name"] += " (Business)"
            row['evidence']={metric:make_evidence(page,ctx.sid,deposit_identity(row,metric),metric,row[metric],
                              row['quote'],clean,row.get('effective'),ctx.date) for metric in ('dividend','apy')}
            row['valid']=currently_valid(row.get('effective'),ctx.date,page.markdown)
            records.append(row)
    # Parsed query variants of an explicit product URL can disagree and must
    # not disappear solely because a canonical URL was found first.
    paths_set={p.rstrip('/') for p in paths}
    for page in ctx.pages:
        if id(page) in seen_pages or urlsplit(page.url).path.rstrip('/') not in paths_set:continue
        seen_pages.add(id(page))
        for row in _tables(page):
            row['business']=urlsplit(page.url).path.startswith('/business')
            row['valid']=currently_valid(row.get('effective'),ctx.date,page.markdown)
            row['evidence']={metric:make_evidence(page,ctx.sid,deposit_identity(row,metric),metric,row[metric],row['quote'],clean,row.get('effective'),ctx.date) for metric in ('dividend','apy')}
            records.append(row)
    ctx.cache['deposit_rows_by_source'] = records
    records = _resolve_rows([r for r in records if r['valid']])
    ctx.cache["deposits"] = records
    return records


def _resolve_rows(source_rows):
    records = [dict(r) for r in source_rows]
    def rank(row):
        effective = row.get('effective') or ''
        for fmt in ('%m/%d/%Y','%m/%d/%y','%Y-%m-%d'):
            try:
                effective = datetime.strptime(effective,fmt).date().isoformat()
                break
            except ValueError:
                pass
        path = urlsplit(row['page'].url).path.rstrip('/')
        auth = 3 if path.startswith(('/personal/','/business/')) or path in ('/checking','/savings-account/online-savings-account') else 2 if path in ('/rates','/business-rates') else 1
        return effective, auth, row['page'].fetched_at
    groups = {}
    for row in records:
        phase = 'introductory' if re.search(r'1st|first|intro',row['period']) else 'standard' if re.search(r'after|standard',row['period']) or 'achieve' in _norm(row['name']) else ''
        row['phase'] = phase
        key = (_norm(row['name']), row['lo'], row['hi'], row['term'], row['business'], phase)
        groups.setdefault(key,[]).append(row)
    records = []
    for alternatives in groups.values():
        # Authority bounds the comparison. A newly crawled promotional mirror
        # cannot displace a current product page merely by being fetched later.
        authoritative = [r for r in alternatives if rank(r)[1] >= 2]
        candidates = authoritative or alternatives
        winner = max(candidates,key=rank)
        tied=[r for r in candidates if rank(r)==rank(winner)]
        if len({(r['dividend'],r['apy']) for r in tied})>1:
            winner['unresolved']=True
            winner['conflicting_pages']=[r['page'] for r in tied]
        facts = ('dividend','apy','opening','minimum','maintaining')
        winner['corroborating'] = [r['page'] for r in candidates if r is not winner and
                                  all(r.get(f)==winner.get(f) for f in facts)]
        if any((r['dividend'],r['apy']) != (winner['dividend'],winner['apy']) for r in candidates):
            winner['note'] = 'Sources disagree for the same qualified deposit fact; the latest explicit effective date among authoritative product/rate tables is used.'
        records.append(winner)
    # A refreshed rate sheet can correct a leftover term label on an IRA page.
    # Require the same IRA type, jumbo qualifier, both rates and minimum; a
    # genuine Roth/Traditional price difference is never collapsed.
    rate_rows = [r for r in records if urlsplit(r["page"].url).path.rstrip("/") == "/rates"]
    superseded = []
    for row in records:
        if row["family"] != "ira" or not row["term"] or "special" not in _norm(row["name"]):
            continue
        for newer in rate_rows:
            if newer["family"] != "ira" or newer["term"] == row["term"] or not newer["term"]:
                continue
            same_type = _norm(row["name"]).split(":", 1)[0] == _norm(newer["name"]).split(":", 1)[0]
            same_qualifier = ("jumbo" in _norm(row["name"])) == ("jumbo" in _norm(newer["name"]))
            offered = any(r["family"] == "certificate" and r["term"] == newer["term"] and "special" in _norm(r["name"]) for r in records)
            old_offered = any(r["family"] == "certificate" and r["term"] == row["term"] and "special" in _norm(r["name"]) for r in records)
            if same_type and same_qualifier and offered and not old_offered and (row["dividend"], row["apy"], _money(row["minimum"] or "")) == (newer["dividend"], newer["apy"], _money(newer["minimum"] or "")):
                superseded.append(row)
                newer["note"] = "The IRA product page retains an obsolete term label; the updated rate sheet agrees with the currently listed certificate terms."
                break
    records = [r for r in records if r not in superseded]
    return records


def _source_rows(ctx, question):
    records = prepare(ctx)
    scope = getattr(ctx, 'question_page_scope', None)
    q = _norm(question)
    if not scope and re.search(r"(?:rates?|rate[- ]sheet)\s+(?:page|table|sheet|snapshot)|(?:snapshot|captured)\s+(?:rate[- ]sheet|rates? table)", q):
        scope = '/business-rates' if 'business' in q else '/rates'
    if not scope:
        return records, False
    if isinstance(scope, str):
        scope = [scope]
    paths = {urlsplit(s).path.rstrip('/') for s in scope}
    selected = [r for r in ctx.cache['deposit_rows_by_source']
                if urlsplit(r['page'].url).path.rstrip('/') in paths and r.get('valid',True)]
    return _resolve_rows(selected), True


def _amounts(question):
    q = _norm(question)
    month = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|sept(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    q = re.sub(r"\b" + month + r"\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+20\d{2})?\b", "", q)
    q = re.sub(r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?" + month + r"\.?(?:,?\s+20\d{2})?\b", "", q)
    q = re.sub(r"(?:\d+(?:\.\d+)?|\.\d+)\s*%", "", q)
    q = re.sub(r"\b\d+\s*[- ]?\s*(?:months?|years?|mos?\.?|mths?\.?|yrs?\.?)\b", "", q)
    q = re.sub(r"\b20\d{2}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b20\d{2}\b", "", q)
    q = re.sub(r"(?:\$\s*)?\d[\d,]*(?:\.\d+)?\s*[- ]\s*(?:minimum|min\b)", "", q)
    matches = list(re.finditer(r"(?:\$\s*)?(\d[\d,]*(?:\.\d+)?)\s*(k\b|thousand\b|million\b)?", q))
    vals, explicit = [], []
    for m in matches:
        # 1st Rate is a name, and effective dates are not account balances.
        if re.match(r'(?:st|nd|rd|th)\b', q[m.end(1):]):
            continue
        v = float(m[1].replace(",", ""))
        if m[2]:
            v *= 1000000 if m[2] == "million" else 1000
        if "$" in m[0] or m[2] or v >= 100 or re.search(r"balance|deposit|save|under|below|between", q):
            vals.append(v)
            if '$' in m[0] or m[2]:
                explicit.append(v)
    return explicit or vals


def _named_deposit(question, rows):
    """Resolve product noun phrases against table names, including new names.

    An unrecognized named account is not a request for the entire savings
    menu. Grammar and generic account descriptors do not constitute a name.
    """
    q = _norm(question)
    neutral = set("what which who how is are was were do does did can could would should will the a an my your our their this that these those i me we us you it its on of for in from to at with and or all any each account accounts dupaco dupaco's personal consumer business current currently today published listed available rate rates dividend dividends interest apy yield yields highest higher high best most maximum minimum min max balance balances tier tiers between exactly under above below over less more than up by earn earns earning earned pay pays paying paid get gets receive receives save saves saving regular standard ordinary online free emergency fund funds general basic first term deposit deposits return returns money monthly savings provide quote tell list show see find give please explain details information about fetch need want know now right".split())
    names = {_norm(r["name"]): r["name"] for r in rows}
    aliases = {key: name for key, name in _PRODUCTS}
    aliases.update({"online savings": "Bright Savings", "christmas club savings": "Holiday Club Savings"})
    # Check the longest full table name first. It also handles product names
    # made of otherwise generic words, such as You Name It Savings.
    direct = [(normalized, name) for normalized, name in names.items()
              if re.search(r"(?<!\w)" + re.escape(normalized) + r"(?!\w)", q)]
    if direct:
        return max(direct, key=lambda item: len(item[0]))[1], False
    candidates = []
    for match in re.finditer(r"\b(?:savings|checking|money market)\b", q):
        prefix = q[:match.start()]
        # Punctuation, numbers and sentence boundaries delimit a noun phrase.
        tail = re.search(r"([a-z][a-z'\-]*(?:\s+[a-z][a-z'\-]*){0,6})\s*$", prefix)
        words = tail[1].split() if tail else []
        category = match[0]
        relevant = [word for word in words if word not in neutral]
        if not relevant:
            continue
        candidate = " ".join(relevant + [category])
        candidates.append(candidate)
    for candidate in candidates:
        alias = next((alias for alias in aliases if re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", q)), None)
        if alias:
            return aliases[alias], False
        # Compare after removing business wrappers; account class remains a
        # separate selector in answer(). Names originate in parsed rows.
        matching = [name for normalized, name in names.items()
                    if _norm(re.sub(r"\(business\)|\bbusiness\b", "", normalized)).strip() == candidate]
        if matching:
            return matching[0], False
        alias = aliases.get(candidate)
        if alias:
            return alias, False
        return None, True
    return None, False


def _filter_balance(rows, question):
    vals = _amounts(question)
    if not vals or not any(r["tier"] for r in rows):
        return rows
    q = _norm(question)
    v = vals[0]
    if re.search(r"\b(?:under|below|less than)\b", q):
        selected = [r for r in rows if r["hi"] is not None and r["hi"] < v]
    elif re.search(r"\b(?:above|over|more than|at least)\b", q):
        selected = [r for r in rows if r["hi"] is not None and r["hi"] >= v]
    else:
        selected = [r for r in rows if r["lo"] is not None and r["lo"] <= v <= r["hi"]]
    return selected


def _filter_certificate_balance(rows, question):
    if not rows or not any(r['term'] is not None for r in rows):
        return rows
    vals = _amounts(question)
    if not vals:
        return rows
    q = _norm(question)
    # A question comparing published minima is not one member's deposit.
    if re.search(r"standard.*(?:and|versus|vs).*jumbo|regular.*(?:and|versus|vs).*jumbo|both|minimums|minimum balances|their minimum|two.*apy", q):
        return rows
    balance = vals[0]
    qualifying = [r for r in rows if _money(r.get('minimum') or '') is None or
                  _money(r['minimum']) <= balance]
    groups = {}
    for row in qualifying:
        # Keep independently requested terms and IRA types; only the deposit
        # minimum selects the applicable regular/jumbo tier within each.
        ira_type = re.match(r'(roth|traditional)', _norm(row['name']))
        key = (row['term'], ira_type[1] if ira_type else '', row['phase'])
        groups.setdefault(key, []).append(row)
    selected = []
    for alternatives in groups.values():
        cutoff = max(_money(r.get('minimum') or '') or 0 for r in alternatives)
        selected.extend(r for r in alternatives if (_money(r.get('minimum') or '') or 0) == cutoff)
    return selected


def _render(row, question):
    q = _norm(question)
    metrics = requested_metrics(question)
    if metrics == {"dividend", "apy"}:
        rate = row["dividend"] + " dividend rate, " + row["apy"] + " APY"
    elif metrics == {"dividend"}:
        rate = row["dividend"] + " dividend rate"
    elif metrics == {"apy"}:
        rate = row["apy"] + " APY"
    else:
        rate = row["dividend"] + " dividend rate, " + row["apy"] + " APY"
    tier = re.sub(r'\s*[–—-]\s*', '-', row['tier'])
    qualifiers = [v for v in (tier, row.get("period")) if v]
    name = re.sub(r'\b(\d+)\s+Months?\b', r'\1-month', row['name'], flags=re.I)
    text = name + (" (" + "; ".join(qualifiers) + ")" if qualifiers else "") + ": " + rate
    if row["family"] in ("certificate", "ira") and row["minimum"]:
        text += "; " + row["minimum"] + " minimum to earn"
    if re.search(r'\bopen\b|\bopening\b', q) and row.get('opening'):
        text += '; ' + row['opening'] + ' minimum to open'
    if re.search(r'\bmaintain\b', q) and row.get('maintaining'):
        text += '; ' + row['maintaining'] + ' minimum to maintain'
    return text


def _reply(ctx, rows, question, lead="", note=None):
    text = lead + "; ".join(_render(r, question) for r in rows) + "."
    effective = list(dict.fromkeys(r.get('effective') for r in rows if r.get('effective')))
    if effective:
        parts = []
        for date in effective:
            for fmt in ('%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d'):
                try:
                    parsed = datetime.strptime(date, fmt)
                    parts.append(parsed.strftime('%B') + ' ' + str(parsed.day) + ', ' + str(parsed.year))
                    break
                except ValueError:
                    pass
        if parts:
            text += ' Table rates effective ' + '; '.join(parts) + '.'
    notes = list(dict.fromkeys(r["note"] for r in rows if r.get("note")))
    pages = [r["page"] for r in rows]
    pages.extend(p for r in rows for p in r.get("corroborating", []))
    return ctx.reply(text, pages=pages, note=note or " ".join(notes) or None,
                     quote="\n".join(r["quote"] for r in rows)[:1600])


def _minimum_reply(ctx, rows, question):
    q = _norm(question)
    kinds = []
    if re.search(r'\bmaintain\b|keep (?:the |my )?account|keep.*open', q):
        kinds.append('maintaining')
    if re.search(r'\bearn\w*\b|\breceive\b|\bdividends?\b|\bapy\b|\byield\b', q):
        kinds.append('minimum')
    if re.search(r'\bopen\b|\bopening\b', q) and 'maintaining' not in kinds:
        kinds.append('opening')
    if not kinds:
        kinds = ['opening']
    names = list(dict.fromkeys(r['name'] for r in rows))
    parts, evidence = [], []
    for name in names:
        product_rows = [r for r in rows if r['name'] == name]
        for kind in kinds:
            eligible = product_rows
            if kind == 'minimum':
                # A zero-dividend tier is not a minimum for earning dividends.
                eligible = [r for r in product_rows if float(r['dividend'].strip('%')) > 0]
            choices = [(r, _money(r.get(kind) or '')) for r in eligible]
            choices = [(r, value) for r, value in choices if value is not None]
            if choices:
                row, value = min(choices, key=lambda pair: pair[1])
                label = {'opening':'minimum to open', 'minimum':'minimum balance to earn dividends',
                         'maintaining':'minimum balance to maintain the account'}[kind]
                parts.append(name + ': $' + format(value, ',.2f') + ' ' + label)
                evidence.append(row['page'])
            elif kind == 'minimum' and not eligible:
                parts.append(name + ' does not publish a positive dividend for the selected tier')
                evidence.extend(r['page'] for r in product_rows)
            elif kind == 'opening' and any(r.get('minimum') for r in product_rows):
                # Certificate tables sometimes name only their earning minimum.
                # Preserve that label instead of silently renaming it 'to open'.
                row = min((r for r in product_rows if _money(r.get('minimum') or '') is not None),
                          key=lambda r: _money(r['minimum']))
                parts.append(name + ': ' + row['minimum'] + ' published minimum to earn; a separate opening minimum is not stated in this table')
                evidence.append(row['page'])
            else:
                return ctx.reply("I don't know: the selected snapshot does not state the requested minimum for that account.",
                                 pages=[r['page'] for r in product_rows], confident=False)
    return ctx.reply('; '.join(parts) + '.', pages=evidence) if parts else None


def answer(ctx, question):
    q = _norm(question)
    # Excluded nearby entities must not become the longest matched product.
    q = re.split(r"\b(?:don't|do not|dont)\s+(?:mix|confuse)\b|\bnot\s+(?=[a-z-]+\s+savings\b)", q)[0].strip()
    certificate = bool(re.search(r"\bcertificates?\b|\bcds?\b|certificate of (?:accounts|deposit)|\bterm[- ]share account\b", q) or ("special" in q and _term(q)))
    ira = bool(re.search(r"\bira\b|individual retirement|roth|traditional.*(?:savings|rate|yield)", q))
    savings = bool(re.search(r"savings?|money market|investor'?s? choice|launchpad|holiday club|christmas club|\bhsa\b|\bbright\b|\bachieve\b|high[- ]yield", q))
    checking = "checking" in q or bool(re.search(r"\b(?:1st|first) rate\b", q))
    if savings and not re.search(r"\bcertificates?\b|\bcds?\b", q):
        certificate = False
    if not (certificate or ira or savings or checking):
        return None
    # Loan/fee/features questions continue to the responsible domain handler.
    asks_rate = bool(re.search(r"rate|apy|yield|dividend|interest|earn|pay|return|percent|\d\s*%|differ|compare|change|values|listed|better deal", q))
    rate_metrics = bool(re.search(r'(?:what|which|quote|show|list|give).*?(?:rates?|apys?|yields?|dividend rate)|(?:rates?|apys?|yields?).*(?:and|,).*minimum|dividend rate.*apy|apy.*dividend rate', q))
    asks_min = bool(re.search(r"minimum|min\.? balance|how much.*(?:open|need|deposit)|balance.*(?:open|maintain)", q))
    if re.search(r"\b(?:loans?|borrow|mortgage|credit card|student|auto|vehicle)\b", q):
        return None
    if 'calculator' in q or re.search(r'\bmembership\b|\bjoin page\b|\bmove away\b', q):
        return None
    if "changeup" in q or "change up" in q:
        return None
    if re.search(r"e[- ]?statements?|\b(?:eligibility|qualify|qualifications?|enroll|requirements?|withdrawals?|penalt(?:y|ies)|fees?|closure|closed|tax)\b", q) or ('eligible' in q and not re.search(r'eligible balance|balance.*eligible', q)):
        # These ask about account operation/eligibility rather than a rate
        # table, even when the sentence also mentions earning interest.
        return None
    if savings and "money market" in q and "new member" in q:
        page = _page(ctx, "/newmembermoneymarket-lp")
        if page and re.search(r"offer has ended|offer.*expired|offer.*no longer available", page.markdown, re.I):
            return ctx.reply("The new-member money market offer has ended, according to its offer page.", pages=[page])
    records, source_limited = _source_rows(ctx, q)
    business = "business" in q
    if certificate and re.search(r"\blink\b|\burl\b|\bwebsite\b|what.*(?:page|link)|where.*(?:find|see|view)", q) and not source_limited:
        page = ctx.find("/business/savings-accounts" if business else "/personal/savings-account")
        if page:
            url = page.url.split("#", 1)[0] + "#rates"
            result = ctx.reply("View the certificate rates at " + url + ".", pages=[page])
            result["sources"][0]["url"] = url
            return result
    if not asks_rate and not asks_min:
        return None
    rows = [r for r in records if r["business"] == business]
    if certificate or ira:
        rows = [r for r in rows if r["family"] == ("ira" if ira else "certificate")]
        terms = _terms(q)
        term = terms[0] if len(terms) == 1 else None
        if terms:
            rows = [r for r in rows if r["term"] in terms]
        both_types = 'roth' in q and 'traditional' in q
        if "roth" in q and not both_types:
            rows = [r for r in rows if "roth" in _norm(r["name"])]
        elif "traditional" in q and not both_types:
            rows = [r for r in rows if "traditional" in _norm(r["name"])]
        tier_comparison = bool(re.search(r"(?:regular|standard|non[- ]jumbo).*\b(?:and|versus|vs)\b.*jumbo|jumbo.*\b(?:and|versus|vs)\b.*(?:regular|standard)|both|two.*(?:special|apy)|special.*(?:and its|and the).*jumbo|minimums|minimum balances|their minimum", q))
        comparison = tier_comparison or len(terms) > 1
        if re.search(r"\bjumbo\b", q) and not re.search(r"non[- ]?jumbo|not jumbo", q) and not comparison:
            rows = [r for r in rows if "jumbo" in _norm(r["name"])]
        elif re.search(r"non[- ]?jumbo|not jumbo|non[- ]?special|regular|standard", q) and not comparison:
            rows = [r for r in rows if "jumbo" not in _norm(r["name"])]
            if re.search(r"non[- ]?special", q) or (("regular" in q or "standard" in q) and "special" not in q and not term):
                rows = [r for r in rows if "special" not in _norm(r["name"])]
        if "special" in q and len(terms) <= 1:
            rows = [r for r in rows if "special" in _norm(r["name"])]
        if not terms and re.search(r'longer[- ]term|longest.*special', q):
            offered = [r['term'] for r in rows if r['term'] is not None]
            if offered:
                rows = [r for r in rows if r['term'] == max(offered)]
        if re.search(r'\bshortest\b|\blongest\b', q) and not re.search(r'longer[- ]term', q):
            offered = [r['term'] for r in rows if r['term'] is not None]
            endpoints = set()
            if offered and 'shortest' in q:
                endpoints.add(min(offered))
            if offered and 'longest' in q:
                endpoints.add(max(offered))
            rows = [r for r in rows if r['term'] in endpoints]
        variable = bool(re.search(r"\bvariable\b|\bliquid\b|without (?:a )?certificate|non[- ]certificate|no (?:fixed |certificate )?term|without (?:a )?term", q))
        if ira and (variable or (_amounts(q) and not term and not re.search(r"\bfixed\b|\bspecial\b|\bcertificate\b|\bcd\b", q))):
            rows = [r for r in rows if "variable" in _norm(r["name"])]
        elif ira and re.search(r"\bfixed\b|certificate|\bcd\b", q):
            rows = [r for r in rows if r["term"] is not None]
        rows = _filter_balance(rows, q)
        if not asks_min or rate_metrics:
            rows = _filter_certificate_balance(rows, q)
        rows.sort(key=lambda r: ("special" not in _norm(r["name"]), r["term"] or 0, "jumbo" in _norm(r["name"]), r["name"]))
    else:
        rows = [r for r in rows if r["family"] == "deposit"]
        named, unknown = _named_deposit(q, rows)
        if unknown:
            page = _page(ctx, "/business/savings-accounts" if business else "/personal/savings-account")
            return ctx.reply("I don't know: the selected snapshot does not publish a rate for that named account.", pages=[page], confident=False)
        target = named or next((name for key, name in _PRODUCTS if key in q), None)
        if re.search(r"\b(?:1st|first) rate\b", q):
            target = "1st Rate Checking"
        if "christmas club" in q:
            target = "Holiday Club Savings"
        if "online savings" in q or "bright" in q:
            target = "Bright Savings"
        if "hsa" in q:
            target = "Health Savings Account"
        if target:
            rows = [r for r in rows if _norm(target) in _norm(r["name"])]
        elif checking:
            rows = [r for r in rows if "checking" in _norm(r["name"])]
        elif "money market" in q:
            rows = [r for r in rows if "money market" in _norm(r["name"])]
        elif "savings tiers" in q or "share" in q or "regular savings" in q:
            rows = [r for r in rows if "share savings" in _norm(r["name"])]
        else:
            rows = [r for r in rows if "savings" in _norm(r["name"]) and "health" not in _norm(r["name"])]
        rows = _filter_balance(rows, q)
        periods = [r for r in rows if r.get("period")]
        if periods or any(r.get('phase') for r in rows):
            both_periods = bool(re.search(r'promotional.*(?:and|versus|vs).*after|introductory.*(?:and|versus|vs).*(?:after|post)|first.*(?:post|after)|intro.*(?:and|versus|vs).*standard|both', q))
            if re.search(r"after|post[- ]promotion|subsequent|ongoing|regular|standard", q) and not both_periods:
                rows = [r for r in rows if r.get('phase') != 'introductory']
            elif re.search(r"introductory|intro\b|promotional|first|1st|new money", q) and not checking and not both_periods:
                rows = [r for r in rows if r.get('phase') == 'introductory']
        claimed = re.findall(r"(\d+(?:\.\d+)?|\.\d+)\s*(?:%|percent|apy)", q)
        if any(r.get('unresolved') for r in rows):
            pages={p.url:p for r in rows if r.get('unresolved') for p in r.get('conflicting_pages',[])}
            return ctx.reply("I don't know which published value is correct: equally authoritative sources disagree for the requested account and tier.",
                             [pages[url] for url in sorted(pages)],confident=False,
                             note='Unresolved same-identity disagreement; a claimed-rate yes/no question does not authorize selecting one conflicting value.')
        if claimed and re.search(r"any|do .*pay|does .*pay|earn|is .*rate|really|correct|heard|accurate|range|up to", q):
            metric = "dividend" if "dividend" in q and "apy" not in q else "apy"
            rates = {float(r[metric].strip("%")) for r in rows}
            valid = all(float(v) in rates for v in claimed)
            matching = [r for r in rows if float(r[metric].strip("%")) in {float(v) for v in claimed}]
            if not valid and rows:
                best = max(rows, key=lambda r: float(r[metric].strip("%")))
                return _reply(ctx, [best], question, "No. The published rate table's highest tier is ")
            if matching:
                return _reply(ctx, matching, question, "Yes. ")
    if any(r.get('unresolved') for r in rows):
        pages=[p for r in rows if r.get('unresolved') for p in r.get('conflicting_pages',[])]
        return ctx.reply("I don't know which published value is correct: equally authoritative sources disagree for the requested account and tier.",
                         pages,confident=False,note='Unresolved same-identity disagreement at equal authority, effective date and observed date.')
    if not rows:
        page = ctx.find("/personal/retirement" if ira else "/business/savings-accounts" if business else "/personal/savings-account")
        if source_limited:
            page = _page(ctx, '/business-rates' if business else '/rates')
        if asks_rate and re.search(r'listed|list\b|find|appeared', q):
            text = 'The requested product or term is not listed in the selected rate table.'
            if certificate:
                alternatives = [r for r in records if r['family'] == ('ira' if ira else 'certificate') and
                                'special' in _norm(r['name']) and r['term'] is not None]
                if alternatives:
                    available = sorted(set(r['term'] for r in alternatives))
                    text += ' It did not list that term; listed special terms are ' + ', '.join(str(term) + '-month' for term in available) + '.'
            return ctx.reply(text, pages=[page], confident=False)
        return ctx.reply("I don't know: the selected snapshot does not publish a matching rate or balance tier for that product.", pages=[page], confident=False)
    if re.search(r'effective date|which date|resolve.*\d{1,2}/\d{1,2}/\d{2,4}|effective.*(?:belongs|table)', q):
        dated = [r for r in rows if r.get('effective')]
        if not dated:
            return ctx.reply("I don't know: this table does not state an effective date.", pages=[r['page'] for r in rows], confident=False)
        parts = []
        for row in dated:
            date = row['effective']
            for fmt in ('%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d'):
                try:
                    parsed = datetime.strptime(date, fmt)
                    shown = parsed.strftime('%B') + ' ' + str(parsed.day) + ', ' + str(parsed.year)
                    break
                except ValueError:
                    shown = date
            item = row['name'] + ' table rates are effective ' + shown + ' (' + date + ')'
            if item not in parts:
                parts.append(item)
        pages=[r['page'] for r in dated]
        for row in dated:
            for page in row.get('corroborating',[]):
                matching=[r for r in _tables(page) if _norm(r['name'])==_norm(row['name']) and
                          (r['lo'],r['hi'],r['term'])==(row['lo'],row['hi'],row['term']) and
                          r.get('effective')==row.get('effective')]
                if matching:pages.append(page)
        return ctx.reply('; '.join(parts) + '.', pages=pages,
                         note='Use the effective date attached directly to the table, ahead of residual footnote dates.')
    if asks_min and not rate_metrics:
        result = _minimum_reply(ctx, rows, question)
        if result:
            return result
    if re.search(r"highest|best|maximum|max(?:imum)? (?:apy|rate)|top.*(?:rate|yield)|most interest", q):
        value = max(float(r["dividend" if "dividend" in q else "apy"].strip("%")) for r in rows)
        rows = [r for r in rows if float(r["dividend" if "dividend" in q else "apy"].strip("%")) == value]
    return _reply(ctx, rows, question)
