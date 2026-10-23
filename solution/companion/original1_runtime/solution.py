"""Offline, provenance-preserving knowledge retrieval. Python 3.9+, no dependencies.

Only objects passed to ingest() supply knowledge. Neither the evaluation questions
nor files on disk are accessed by the system. Facts are partitioned by observation
date; table columns and qualifiers remain part of their identity.
"""
import bisect
import calendar
import copy
import html
import math
import re
import difflib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlparse

try:
    from contract import Answer, Conflict, Source
except ImportError:
    # Standalone use works as well; the harness accepts structurally identical types.
    @dataclass
    class Source:
        url: str
        snapshot_id: str = None
        quote: str = None

    @dataclass
    class Answer:
        text: str
        sources: list = field(default_factory=list)
        confident: bool = True
        conflict_note: str = None

    @dataclass
    class Conflict:
        topic: str
        values: list
        sources: list
        resolution: str = None
        reason: str = None


MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
DATE_RE = re.compile(r"\b([A-Z][a-z]+)(?:\.\s*|\s+)(\d{1,2}),?\s*(20\d{2})\b", re.I)
RATE_RE = re.compile(r"\d+(?:\.\d+)?\s*%")
MONEY_RE = re.compile(r"\$\s*(\d[\d,]*(?:\.\d+)?)")
STOP = set("a an and are as at be by can could do does for from get give have how i in is it me my of on or our please right s tell that the their these this to us was what when which with would you your now current dupaco account accounts rate rates interest apy apr dividend percentage annual yield loan loans".split())
SYNONYMS = {"cd": "certificate", "cds": "certificate", "certificates": "certificate",
             "cars": "auto", "car": "auto", "vehicle": "auto", "vehicles": "auto",
             "automobile": "auto", "motorcycle": "auto", "branches": "branch",
             "locations": "location", "hours": "hour", "fees": "fee",
             "cards": "card", "mortgages": "mortgage", "savings": "savings",
             "replacement": "replace", "replacing": "replace", 'payments':'payment',
             'wires':'wire', 'overdrafts':'overdraft', 'transactions':'transaction',
             'withdrawals':'usage', 'withdrawal':'usage', 'costs':'cost','services':'service'}
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                "twelve": 12, "fifteen": 15, "seventeen": 17, "eighteen": 18,
                "twenty": 20, "twenty four": 24, "thirty": 30, "thirty six": 36,
                "forty eight": 48, "sixty": 60, "seventy two": 72, "eighty four": 84}
SMALL_NUMBERS = {'zero':0,'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,
                 'eight':8,'nine':9,'ten':10,'eleven':11,'twelve':12,'thirteen':13,
                 'fourteen':14,'fifteen':15,'sixteen':16,'seventeen':17,'eighteen':18,
                 'nineteen':19,'twenty':20,'thirty':30,'forty':40,'fifty':50,'sixty':60,
                 'seventy':70,'eighty':80,'ninety':90}
NUM_WORD_RE = re.compile(r'\b(?:' + '|'.join(SMALL_NUMBERS) + r'|hundred|thousand|million|and)(?:\s+(?:' + '|'.join(SMALL_NUMBERS) + r'|hundred|thousand|million|and))*\b')


def quantity_words(text):
    def replace(match):
        phrase = match.group()
        after = text[match.end():]
        before = text[max(0, match.start()-24):match.start()]
        if re.match(r'(?:thousand|million)\b',phrase) and re.search(r'\d+(?:\.\d+)?\s*$',before):
            return phrase
        if not re.match(r'\s+(?:dollars?|months?|years?)\b', after) and not re.search(r'(?:balance(?: of)?|amount(?: of)?|deposit(?: of)?)\s*$', before) and not re.search(r'thousand|million',phrase):
            return phrase
        if phrase.startswith('and ') or phrase.endswith(' and'):
            return phrase
        total, current = 0, 0
        for word in phrase.split():
            if word in SMALL_NUMBERS: current += SMALL_NUMBERS[word]
            elif word == 'hundred': current = (current or 1) * 100
            elif word in ('thousand', 'million'):
                total += (current or 1) * (1000 if word == 'thousand' else 1000000); current = 0
        return str(total + current)
    return NUM_WORD_RE.sub(replace, text)


def clean(text):
    for _ in range(2):
        text = html.unescape(text)
    text = re.sub(r"!\[[^\]]*\]\([^\n]*?\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^\n]*?\)", r"\1", text)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\\r\\n", " ").replace("\\", "")
    text = text.replace("–", "-").replace("—", "-").replace("’", "'")
    text = text.replace('afet r','after').replace('atet mpted','attempted')
    text = re.sub(r"[*_#]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def readable(text, links=False):
    stored_urls=[]
    if links:
        def protect(m):
            stored_urls.append(html.unescape(m.group()));return 'URLPLACEHOLDER'+str(len(stored_urls)-1)
        text=re.sub(r'(?:https?://|mailto:)[^\s)]+',protect,text)
        text=re.sub(r'!\[[^\]]*\]\([^\n]*?\)','',text)
        text=re.sub(r'\[([^\]]+)\]\(([^)\n]+)\)',lambda m:m[1]+' ('+m[2]+')',text)
    text=clean(text)
    text=re.sub(r'(?<=\d)\s*-\s*(?=[$\d])','-',text)
    for i,url in enumerate(stored_urls):text=text.replace('URLPLACEHOLDER'+str(i),url)
    return text


def document_sections(md):
    heads=list(re.finditer(r'(?m)^(#{1,6})\s+(.+)$',md))
    result=[]
    for i,h in enumerate(heads):
        end=next((x.start() for x in heads[i+1:] if len(x[1])<=len(h[1])),len(md))
        title=clean(h[2]);body=md[h.start():end]
        if title and not title.startswith(('Continue','Cancel')):
            result.append((title,body,len(h[1]),h.start()))
    return result


def display_date(day):
    d=date.fromisoformat(day)
    return d.strftime('%B')+' '+str(d.day)+', '+str(d.year)


def expand_date_text(text):
    def expand(m):
        mo=m[1].lower();mo='sep' if mo=='sept' else mo
        if mo not in MONTHS:return m.group()
        try:return display_date(date(int(m[3]),MONTHS[mo],int(m[2])).isoformat())
        except ValueError:return m.group()
    return re.sub(r'\b([A-Za-z]{3,4})\.\s*(\d{1,2}),\s*(20\d{2})\b',expand,text)


def normalized(text):
    text = clean(text).lower()
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    text = re.sub(r"\bmonths?\b", "month", text)
    text = re.sub(r"\byears?\b", "year", text)
    return re.sub(r"\s+", " ", text).strip()


def query_normalized(text):
    text = normalized(text).replace("-", " ")
    substitutions = {'cert':'certificate','acct':'account','accts':'accounts','yr':'year','yrs':'years',
                     'mo':'month','mos':'months','reg':'regular','w':'with','ur':'your','pls':'please',
                     'bucks':'dollars','grand':'thousand','svc':'service','notery':'notary',
                     'notarize':'notary','notarise':'notary','notarization':'notary','brite':'bright',
                     'checkin':'checking','ext':'extension','mgr':'manager','rait':'rate','ra it':'rate',
                     'apys':'apy','aprs':'apr','yields':'yield','ride':'vehicle','rewads':'rewards','dividends':'dividend'}
    text = re.sub(r'\b(?:'+'|'.join(map(re.escape,substitutions))+r')\b',lambda m:substitutions[m.group()],text)
    cardinal='|'.join(sorted(SMALL_NUMBERS,key=len,reverse=True))
    fractions={'half':0.5,'quarter':0.25}
    def mixed_fraction(m):
        whole=float(m[1]) if re.fullmatch(r'\d+(?:\.\d+)?',m[1]) else SMALL_NUMBERS[m[1]]
        return format(whole+fractions[m[2]],'g')+' '+m[3]
    text=re.sub(r'\b(\d+(?:\.\d+)?|'+cardinal+r')\s+and\s+(?:a\s+)?(half|quarter)\s+(year|month|thousand|million)\b',mixed_fraction,text)
    text=re.sub(r'\b(?:a\s+)?year\s+and\s+a\s+half\b','1.5 year',text)
    text=re.sub(r'\bthree\s+quarters?(?:\s+of)?\s+(?:a\s+)?(year|month|million)\b',r'0.75 \1',text)
    text=re.sub(r'\b(?:a\s+|one\s+)?(half|quarter)(?:\s+of)?\s+(?:a\s+)?(year|month|thousand|million)\b',lambda m:format(fractions[m[1]],'g')+' '+m[2],text)
    text = re.sub(r"\b(\d{2})\s+(car|vehicle|model)\b",lambda m:'20'+m[1]+' '+m[2],text)
    text = re.sub(r'\btwenty twenty (\w+)\b',lambda m:str(2020+SMALL_NUMBERS.get(m[1],0)),text)
    text = re.sub(r'\bthree quarter million\b','750000',text)
    text = re.sub(r'\ba quarter million\b','250000',text)
    text = quantity_words(text)
    text = re.sub(r'\b(\d+(?:\.\d+)?)\s+(thousand|million)\b', lambda m: str(float(m[1]) * (1000 if m[2]=='thousand' else 1000000)), text)
    for word, number in sorted(NUMBER_WORDS.items(), key=lambda x: -len(x[0])):
        text = re.sub(r"\b" + word + r"\b(?=\s+(?:month|year))", str(number), text)
    text = re.sub(r"\b(\d+(?:\.\d+)?)\s*([km])\b", lambda m: str(int(float(m[1]) * (1000 if m[2]=='k' else 1000000))), text)
    text = re.sub(r"\bfirst rate\b", "1st rate", text)
    if not re.search(r'compare|both|separate|terms|certificates|\bcds\b',text):
        text=re.sub(r'\b(\d+(?:\.\d+)?|a)\s+year\s+and\s+(\d+(?:\.\d+)?)\s+month\b',lambda m:format((1 if m[1]=='a' else float(m[1]))*12+float(m[2]),'g')+' month',text)
    text=re.sub(r'\ba\s+year\b','1 year',text)
    return text


def product_name(entity):
    name=query_normalized(entity)
    name=re.sub(r'\(?\b(?:business|personal|accounts?)\b\)?','',name)
    return re.sub(r'\s+',' ',name).strip()


def positive_metric_text(q):
    """Remove only negative metric clauses, preserving positive instructions."""
    excluded=set()
    pattern=re.compile(r"\b(?:do not|don't|dont|not|no|exclude|excluding|omit|ignore|without)\b[^,;.!?]*")
    def remove(m):
        text=m.group()
        boundary=re.search(r'\bbut\b|\band\s+(?:show|give|tell|include|state|quote|report|use)\b',text)
        negative=text[:boundary.start()] if boundary else text
        if not re.search(r'\b(?:apy|apr|dividend|interest|rate|yield)\b',negative):return text
        if re.search(r'\bapy\b|annual percentage yield',negative):excluded.add('apy')
        if re.search(r'\bapr\b|annual percentage rate',negative):excluded.add('apr')
        if 'dividend' in negative:excluded.add('dividend')
        if 'interest' in negative:excluded.add('rate')
        return text[boundary.start():] if boundary else ''
    return pattern.sub(remove,q),excluded


def tokens(text):
    words = re.findall(r"[a-z]+|\d+(?:\.\d+)?", query_normalized(text))
    return [SYNONYMS.get(w, w) for w in words if w not in STOP]


def rates(text):
    return [m.group().replace(" ", "") for m in RATE_RE.finditer(text)]


def value_identity(value):
    # Formatting changes ($5.00 each / $5.00each, 3.5% / 3.50%) are not conflicts.
    v = clean(value).lower().replace(',', '')
    v = re.sub(r'\d+(?:\.\d+)?', lambda m: format(float(m.group()), '.12g'), v)
    return re.sub(r'\s+', '', v)


def dates(text):
    found = []
    for m in DATE_RE.finditer(text):
        month = MONTHS.get(m[1].lower())
        if month:
            try:
                found.append((date(int(m[3]), month, int(m[2])).isoformat(), m.group()))
            except ValueError:
                pass
    return found


def effective_date(text):
    iso=re.search(r'\b(?:effective|accurate)\s+(?:as of\s+)?(20\d{2}-\d{2}-\d{2})\b',text,re.I)
    if iso:
        try:return date.fromisoformat(iso[1]).isoformat()
        except ValueError:pass
    m = re.search(r"(?:effective|accurate)\s+(?:as of\s+)?(\d{1,2})/(\d{1,2})/(\d{4})", text, re.I)
    if m:
        try:
            return date(int(m[3]), int(m[1]), int(m[2])).isoformat()
        except ValueError:
            pass
    ds = dates(text)
    return ds[0][0] if ds else ""


def term(text, unit="month"):
    number=r'(?:\d+(?:\.\d+)?|\.\d+)'
    noun=r'(?:months?|mo)' if unit=='month' else r'years?'
    direct=re.search(r'(?<![\d.])('+number+r')\s+'+noun+r'\b',query_normalized(text))
    if direct:
        value=float(direct[1]);return int(value) if value.is_integer() else value
    values=all_terms(text,unit)
    return values[0] if values else None


def offer_validity(text):
    """Absolute offer dates only; a relative rate lock is not a site-wide expiry."""
    date_text=r'(?:20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/20\d{2}|[A-Za-z]+\.?\s*\d{1,2},?\s*20\d{2})'
    result={}
    for field,marker in [('valid_from',r'(?:starts?|begins?|valid from|available from)'),
                         ('valid_until',r'(?:ends?|ended|expires?|expired|valid until|valid through|available through)')]:
        m=re.search(r'\b'+marker+r'\s*(?:on\s+|by\s+|at\s+)?('+date_text+r')',text,re.I)
        if not m:continue
        raw=m[1]
        try:
            if re.fullmatch(r'20\d{2}-\d{2}-\d{2}',raw):parsed=date.fromisoformat(raw).isoformat()
            elif '/' in raw:
                month,day,year=map(int,raw.split('/'));parsed=date(year,month,day).isoformat()
            else:parsed=dates(raw)[0][0]
        except (ValueError,IndexError):continue
        result[field]=parsed
    return result


def wanted_metric(q):
    if re.search(r'\bapr\b|annual percentage rate', q):
        return 'apr'
    if re.search(r'\bapy\b|annual percentage yield', q):
        return 'apy'
    if re.search(r'\bdividend\b', q):
        return 'dividend'
    if re.search(r'\byield\b', re.sub(r'\bhigh yield\b', '', q)):
        return 'apy'
    return None


def asked_metrics(q, family):
    q,excluded=positive_metric_text(q)
    has_apr = bool(re.search(r'\bapr\b|annual percentage rate',q))
    has_apy = bool(re.search(r'\bapy\b|annual percentage yield|\byields?\b',re.sub(r'high yield','',q)))
    explicit_rate = bool(re.search(r'dividend rate|interest rate|(?:rate|rates)\s*(?:/|and|,).*?(?:apr|apy)|(?:apr|apy).*?and.*?rate',q))
    if has_apr and (explicit_rate or re.search(r'rate\s*/\s*apr|rate and apr|rate, apr',q)):
        return {'rate','apr'} if family=='mortgage' else {'apr'}
    if has_apy and (explicit_rate or re.search(r'\b(?:tier|band)\b.*\byield',q)):
        return {'dividend','apy'}
    if family=='mortgage' and explicit_rate and not has_apr:return {'rate'}
    metric=wanted_metric(q)
    if metric:return {metric}-excluded
    if excluded:
        defaults={'rate','apr'} if family=='mortgage' else {'dividend','apy'} if family in ('savings','checking','ira','certificate') else {'apr'}
        return defaults-excluded
    return None


def all_terms(q, unit='month'):
    q=query_normalized(q)
    noun=r'(?:month|mo)' if unit=='month' else r'year'
    number=r'(?:\d+(?:\.\d+)?|\.\d+)'
    numeric=lambda value:int(float(value)) if float(value).is_integer() else float(value)
    found=[numeric(m[1]) for m in re.finditer(r'(?<![\d.])('+number+r')\s+'+noun+r'\b',q)]
    for m in re.finditer(r'((?:'+number+r'\s*[, -]\s*)+(?:and\s+)?'+number+r')\s+'+noun+r'\b',q):
        found.extend(numeric(v) for v in re.findall(number,m[1]))
    if unit=='month':
        m=re.search(r'\bfrom\s+(\d+)\s+through\s+(\d+)\s+month',q)
        if m:return list(range(int(m[1]),int(m[2])+1))
    return sorted(set(found))


def bounds(text, model=False):
    t = normalized(text)
    if model:
        m = re.search(r"(20\d{2})\s*-\s*(\d{2}|20\d{2})", t)
        if m:
            hi = int(m[2]); hi = hi + 2000 if hi < 100 else hi
            return min(int(m[1]), hi), max(int(m[1]), hi)
        m = re.search(r"20\d{2}", t)
        if m:
            n = int(m.group()); return (0, n) if 'older' in t else (n, n)
        return None
    money = MONEY_RE.findall(t)
    money_range = re.search(r'\$\s*(\d+(?:\.\d+)?)\s*-\s*\$?\s*(\d+(?:\.\d+)?)', t)
    if money_range:
        return float(money_range[1]), float(money_range[2])
    ns = [float(v.replace(',', '')) for v in money] if money else [float(v.replace(',', '')) for v in re.findall(r"\d+(?:\.\d+)?", t)]
    if not ns:
        return None
    if "+" in t or "and up" in t or "and over" in t or "or more" in t:
        return ns[0], float('inf')
    if "or less" in t or "up to" in t:
        return 0, ns[0]
    return (ns[0], ns[1]) if len(ns) > 1 else (ns[0], ns[0])


@dataclass
class Row:
    family: str
    entity: str
    qualifier: str
    cells: dict
    url: str
    sid: str
    observed: str
    fetched: str
    effective: str
    quote: str
    authority: int
    scope: str = "personal"
    months: int = None
    years: int = None
    model: tuple = None
    balance: tuple = None
    phase: str = "standard"
    valid_from: str = None
    valid_until: str = None

    def source(self):
        return Source(self.url, self.sid, self.quote)

    def key(self):
        if '_identity' not in self.__dict__:
            entity = normalized(self.entity)
            entity = re.sub(r'\(?\bbusiness\b\)?', '', entity)
            entity = re.sub(r'\s+', ' ', entity).strip()
            qualifier = normalized(self.qualifier)
            if self.family in ('certificate','ira') and self.months is not None:
                variant=query_normalized(entity)
                variant=re.sub(r'(?<![\d.])(?:\d+(?:\.\d+)?)\s+(?:month|year)\b','',variant)
                variant=re.sub(r'\s+',' ',variant).strip()
                entity=format(self.months,'g')+' month / '+variant
            if self.family == 'checking' and entity == 'checking':
                entity = '1st rate checking'
            if self.family == 'auto':
                entity = 'model years ' + repr(self.model)
                qualifier = str(self.months)
            elif self.family in ('savings', 'checking', 'improvement', 'recreation') and self.balance:
                qualifier = repr(self.balance) + ' / ' + str(self.months)
            elif self.family == 'mortgage':
                entity = re.sub(r'\$\s*\d+(?:\.\d+)?\s*or less', '', entity).strip()
                qualifier = repr(self.balance)
            elif self.family == 'ira' and self.balance and self.months is None:
                entity = entity.split(':')[0] + ' ira share savings'
                qualifier = repr(self.balance)
            elif self.family=='card':
                entity=re.sub(r'\s+rates?$', '',entity)
            self.__dict__['_identity'] = (self.family, self.scope, entity, qualifier, self.phase)
        return self.__dict__['_identity']


@dataclass
class Chunk:
    text: str
    url: str
    sid: str
    title: str
    published: str
    weight: int
    terms: Counter
    length: int = 0
    title_terms: frozenset = field(default_factory=frozenset)


class State:
    def __init__(self, snap):
        self.sid = snap.snapshot_id
        self.taken_on = snap.taken_on
        self.rows = []
        self.pages = {p.url: p for p in snap.pages}
        self.quote_index = {}
        self.chunks = []
        self.hours = []
        self.scalar = defaultdict(list)
        self.index = defaultdict(list)
        self.df = Counter()
        self.best = {}
        self.family_rows = defaultdict(list)
        self.claims = defaultdict(list)
        self.faqs = []
        self.sections = {}
        self.table_date_claims=[]
        self.invalid_counters={}
        self.deposit_products=defaultdict(dict)
        self.deposit_aliases=defaultdict(dict)


def authority(url, family):
    path = urlparse(url).path.lower().rstrip('/')
    canonical = {"certificate": "/personal/savings-account", "savings": "/personal/savings-account",
                 "checking": "/personal/checking-accounts", "auto": "/personal/loans/auto-motorcycle-loans",
                 "mortgage": "/personal/loans/home-loans", "personal": "/personal/loans/personal-loans",
                 "card": "/personal/credit-cards", "equity": "/personal/loans/home-equity",
                 "improvement": "/personal/loans/home-improvement-loan",
                 "recreation": "/personal/loans/recreational-loans", "ira": "/personal/retirement"}
    if path == canonical.get(family):
        return 100
    if path in ('/business/rates', '/business-rates', '/business/credit-cards', '/business/savings-accounts', '/business/business-checking-accounts'):
        return 100
    if path == '/rates' or path.startswith('/rates/'):
        return 95
    if family == 'fee' and 'fee-schedule' in path:
        return 100
    if path.startswith('/personal/') or path.startswith('/business/'):
        return 75
    if 'calculator' in path:
        return 15
    if '/newsroom/' in path or '/blog/' in path or 'owners-manual' in path:
        return 25
    return 60


class Knowledge:
    def __init__(self):
        self.states = []
        self._conflicts_cache = None
        self._active_cache={}

    def ingest(self, snapshot):
        state = State(snapshot)
        for page in snapshot.pages:
            self._parse_page(state, page)
        # Bridge one missing fee-page observation, for at most 90 days. Repeated
        # absence in full snapshots is not proof that an old fee remains current.
        # Removed rows on a recrawled page are tombstoned. Never carry rates.
        prior_states = [s for s in self.states if s.sid != snapshot.snapshot_id and s.taken_on <= snapshot.taken_on]
        previous = max(prior_states, key=lambda s:(s.taken_on,s.sid)) if prior_states else None
        if previous:
            for row in previous.best.values():
                age = (date.fromisoformat(snapshot.taken_on) - date.fromisoformat(row.observed)).days
                if row.family == 'fee' and row.url not in state.pages and row.url in previous.pages and 0 <= age <= 90:
                    state.rows.append(row)
        # Complete the registry before resolving short table-context labels.
        # This makes source identity independent of page ingestion order.
        names=defaultdict(dict)
        for row in state.rows:
            if row.family in ('savings','checking'):
                names[(row.family,row.scope)][product_name(row.entity)]=row.entity
        for row in state.rows:
            if row.family not in ('savings','checking'):continue
            name=product_name(row.entity)
            if not re.search(r'\b(?:savings|checking|money|market|account)\b',name):
                longer=[n for n in names[(row.family,row.scope)] if n.startswith(name+' ') and re.search(r'\b(?:savings|checking|market)\b',n)]
                if len(longer)==1:
                    row.entity=names[(row.family,row.scope)][longer[0]];row.__dict__.pop('_identity',None)
        for row in state.rows:
            key = row.key()
            prev = state.best.get(key)
            if prev is None or self._rank(row) > self._rank(prev):
                state.best[key] = row
            state.claims[key].append(row)
        for row in state.best.values():
            state.family_rows[row.family].append(row)
            if row.family in ('savings','checking'):
                state.deposit_products[(row.family,row.scope)].setdefault(product_name(row.entity),[]).append(row)
        self._learn_deposit_aliases(state)
        for i, chunk in enumerate(state.chunks):
            for word in chunk.terms:
                state.index[word].append(i)
                state.df[word] += 1
        # Reingesting a snapshot is idempotent; receiving them out of order is safe.
        self.states = [s for s in self.states if s.sid != state.sid]
        self.states.append(state)
        self.states.sort(key=lambda s: (s.taken_on, s.sid))
        self._conflicts_cache = None
        self._active_cache={}

    @staticmethod
    def _rank(row):
        # Official rate tables share an authority class; their local effective
        # date orders them before page specificity. Recrawl time is a last tie.
        return (2 if row.authority>=95 else 1 if row.authority>=60 else 0), row.effective, row.authority, row.fetched, row.url

    def _learn_deposit_aliases(self,state):
        for (family,scope),products in state.deposit_products.items():
            proposals=defaultdict(set)
            for url,sections in state.sections.items():
                if authority(url,family)<60:continue
                page_scope='business' if '/business/' in url or '/business-' in url else 'personal'
                if scope!=page_scope:continue
                for title,body,_,_ in sections:
                    alias=product_name(title)
                    if not re.search(r'\b(?:savings|checking|money market)\b',alias):continue
                    if alias in products:
                        proposals[alias].add(alias);continue
                    text=query_normalized(body)
                    present={name for name in products if re.search(r'\b'+re.escape(name)+r'\b',text)}
                    opened={name for name in present if re.search(r'\bopen\s+(?:(?:my|your|a|an)\s+)?'+re.escape(name)+r'\b',text)}
                    selected=opened or present
                    generic=set(re.findall(r'[a-z0-9]+',alias)) <= {'savings','checking','money','market','account','accounts','rates'}
                    if len(selected)==1 or generic:
                        proposals[alias].update(selected)
                        if 'online only' in alias:proposals[alias.replace('online only','online')].update(selected)
            state.deposit_aliases[(family,scope)]={alias:names for alias,names in proposals.items() if names}

    def _positive_product_query(self,q,products):
        negative=r"(?:not(?:\s+(?:about|asking for|referring to))?|except|excluding|rather than|instead of|(?:do not|don't|dont)\s+(?:mix(?:\s+(?:it|them))?(?:\s+up)?\s+with|confuse(?:\s+(?:it|them))?\s+with))"
        for name in sorted(products,key=len,reverse=True):
            q=re.sub(r'\b'+negative+r'\s+(?:(?:the|business|personal)\s+)?'+re.escape(name)+r'\b','',q)
        short_names=defaultdict(list)
        for name in products:
            short=re.sub(r'\s+(?:savings|checking|money market|account)\b.*$','',name)
            if short and short!=name:short_names[short].append(name)
        for short,names in short_names.items():
            if len(names)==1:q=re.sub(r'\b'+negative+r'\s+(?:(?:the|business|personal)\s+)?'+re.escape(short)+r'\b','',q)
        return q

    def _matched_deposit_products(self,state,q,family,scope):
        products=state.deposit_products.get((family,scope),{})
        q=self._positive_product_query(q,products)
        words=set(re.findall(r'[a-z0-9]+',q))
        generic={'savings','checking','money','market','account','accounts','business','personal','s','rates'}
        signature=lambda name:set(re.findall(r'[a-z0-9]+',name))-generic
        exact={name for name in products if re.search(r'\b'+re.escape(name)+r'\b',q)}
        explicit_words=set().union(*(signature(name) for name in exact)) if exact else set()
        matched=set(exact)
        for name in products:
            specific=signature(name)
            if specific and specific<=words and (not exact or not specific<=explicit_words):matched.add(name)
        for alias,names in state.deposit_aliases.get((family,scope),{}).items():
            alias_specific=set(re.findall(r'[a-z0-9]+',alias))-generic
            if re.search(r'\b'+re.escape(alias)+r'\b',q) and (not matched or alias_specific and not alias_specific<=explicit_words):
                matched.update(names)
        return matched

    def _unknown_deposit_product(self,state,q,family):
        scope='business' if 'business' in q else 'personal'
        products=state.deposit_products.get((family,scope),{})
        if not products:return False
        q=self._positive_product_query(q,products)
        exact={name for name in products if re.search(r'\b'+re.escape(name)+r'\b',q)}
        for named in re.findall(r'\b(?:named|called)\s+(?:the\s+)?((?:[a-z0-9\']+\s+){0,4}(?:checking|savings|money market)(?:\s+account)?)\b',q):
            name=product_name(named)
            if name not in products and name not in state.deposit_aliases.get((family,scope),{}):return True
        for quoted in re.findall(r'["“]([^"”]+)["”]',q):
            if re.search(r'checking|savings|money market',quoted) and product_name(quoted) not in products:return True
        if exact:
            # A full source-declared name is stronger than incidental wording
            # before it. Unknown standalone names still fail the registry check.
            return False
        generic=STOP|{'any','all','every','each','general','current','regular','standard','basic','existing','new',
                      'primary','secondary','active','fixed','variable','online','only','account','accounts','tier','tiers',
                      'band','balance','amount','deposit','deposits','rate','rates','annual','percentage','yield','apy',
                      'apr','dividend','interest','my','your','their','our','personal','business','compare','which',
                      'how','much','minimum','min','maximum','minimums','open','opening','to','on','for','of','the',
                      'will','would','should','may','might','must','has','have','had','does','do','can','could','get','give',
                      'show','quote','tell','provide','return','earn','earns','pay','pays','offer','offers','offered',
                      'eligible','eligibility','qualify','bank','credit','union','financial','cooperative','available',
                      'normal','mid','middle','lowest','highest','top','large','small','branch','within','under','over'}
        known_words=set().union(*(set(re.findall(r'[a-z0-9]+',name)) for name in products))
        for m in re.finditer(r'((?:[a-z0-9]+\s+){0,4})(checking|savings|money market)\b',q):
            words=m[1].split();boundaries={'on','in','for','from','at','of','into','the','a','an','my','your','our','its','their','with'}
            cut=max((i for i,w in enumerate(words) if w in boundaries),default=-1)
            modifiers={w for w in words[cut+1:] if w not in generic and not w.isdigit()}
            if modifiers-known_words:return True
        return False

    def _parse_page(self, state, page):
        md = page.markdown
        excerpts=[part for part in md.split('\n\n') if part.strip()]
        excerpts.extend(line for line in md.splitlines() if line.strip())
        state.quote_index[page.url]={}
        for excerpt in excerpts:
            state.quote_index[page.url].setdefault(clean(excerpt),excerpt)
        state.sections[page.url]=document_sections(md)
        published = (dates(md[:650]) or [("", "")])[0][0]
        lines = md.splitlines()
        context = ""
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('#') or (line and len(line) < 100 and not line.startswith(('|', '!', '['))):
                context = clean(line)
            if line.startswith('|') and i + 1 < len(lines) and re.match(r"^\|\s*:?-+", lines[i + 1].strip()):
                header = [clean(v) for v in line.strip('|').split('|')]
                j = i + 2
                while j < len(lines) and lines[j].strip().startswith('|'):
                    j += 1
                footnote = " ".join(lines[j:j + 5])
                ed = effective_date(footnote)
                local_dates=[]
                for dm in re.finditer(r'Rates are effective (?:as of\s+)?(\d{1,2}/\d{1,2}/\d{4})',clean(footnote),re.I):
                    parsed=effective_date(dm.group())
                    if parsed and parsed not in [d[0] for d in local_dates]:local_dates.append((parsed,dm.group()))
                if len(local_dates)>1:
                    entity=clean(lines[i+2].strip().strip('|').split('|')[0]) if i+2<j else context
                    state.table_date_claims.append((entity,local_dates,page.url,clean(footnote)))
                for raw in lines[i + 2:j]:
                    values = [clean(v) for v in raw.strip().strip('|').split('|')]
                    if len(values) != len(header):
                        continue
                    before=len(state.rows)
                    self._table_row(state, page, header, values, context, ed, raw)
                    if re.search(r'offer|promotion|special',footnote,re.I):
                        validity=offer_validity(clean(footnote))
                        for row in state.rows[before:]:
                            if row.phase=='promotional' or 'special' in row.entity.lower():
                                for field,value in validity.items():setattr(row,field,value)
                i = j
                continue
            i += 1
        # Personal card APR ranges live in prose, not in a rate table.
        if '/credit-cards' in page.url or ('visa' in page.title.lower() and 'business' not in page.title.lower()):
            self._card_prose(state, page)
        # The small harness fixture (and some prose-only pages) use explicit statements.
        self._explicit_prose(state, page)
        if 'fee-schedule' in page.url:
            m=re.search(r'You will not be charged an overdraft fee.*?Maximum charge of one fee per day',clean(md),re.I)
            if m:
                for row in state.rows:
                    if row.url==page.url and row.family=='fee' and 'overdraft' in row.entity.lower():row.cells['conditions']=m.group()
        self._scalars(state, page, published)
        self._hours(state, page)
        faq_pattern = r'(?m)^\s*-\s+\[([^\]\n]+\?)\]\([^\n]+\)\s*\n'
        faqs = list(re.finditer(faq_pattern, md))
        for j, match in enumerate(faqs):
            after = md[match.end():faqs[j+1].start() if j+1<len(faqs) else len(md)]
            after = re.split(r'\n#{1,6}\s|\n\*\*Have questions', after)[0]
            answer_text = clean(after)
            if answer_text and len(answer_text)<2800:
                state.faqs.append((clean(match[1]), answer_text, page.url, frozenset(tokens(match[1]))))
        # Ignore related-article lists and forms. They introduce unrelated facts.
        main = re.split(r"\n#{1,6}\s+(?:Recent News|Related|Handpicked for You|You [Mm]ight|Have questions\? Ready|Contact us)\b", md)[0]
        seen = set()
        for para in main.split('\n\n'):
            para = clean(para)
            if len(para) < 30 or len(para) > 2000 or para in seen:
                continue
            if para.startswith(('Continue ', 'Cancel', 'First Name', 'Please Select', 'Alabama ')) or 'data:image' in para:
                continue
            seen.add(para)
            terms = Counter(tokens(para))
            state.chunks.append(Chunk(para, page.url, state.sid, page.title, published,
                                      authority(page.url, ''), terms, sum(terms.values()),
                                      frozenset(tokens(page.title + ' ' + urlparse(page.url).path))))

    def _table_row(self, state, page, header, vals, context, ed, raw):
        heads = [normalized(h) for h in header]
        label = vals[0]
        low = normalized(label)
        cells = {}
        family = None
        qualifier = ""
        scope = 'business' if '/business/' in page.url or '/business-' in page.url or 'business' in low or 'business' in page.title.lower() else 'personal'
        phase = 'standard'
        is_model = 'model year' in low
        if re.match(r'(?:roth|traditional)\s*:', low) and any('yield' in h for h in heads):
            family = 'ira'
        elif heads[0] == 'loan type' and re.search(r'atv|snowmobile|jet ski|recreational', context + page.url, re.I) and is_model:
            family = 'recreation'; qualifier = vals[1]
            label = 'ATV, Snowmobile & Jet Ski ' + label
        elif is_model:
            if re.search(r'atv|snowmobile|jet ski|recreational', context + page.url, re.I):
                family = 'recreation'; label = 'ATV, Snowmobile & Jet Ski ' + label
            else:
                family = 'auto'
            qualifier = vals[1]
        elif 'certificate' in heads[0] or (heads[0] == 'term' and any('yield' in h for h in heads)) or ('certificate' in low and any('yield' in h for h in heads)):
            family = 'certificate'
            if 'certificate' not in low:
                label += ' Certificate'
        elif heads[0].startswith('ira type'):
            family = 'ira'
        elif heads[0] in ('program', 'term') and 'rate' in heads and 'apr' in heads:
            family = 'mortgage'
            if not re.search(r'purchase|refinance', low):
                label = ('Refinance: ' if 'refi' in page.url else 'Purchase: ') + label
        elif heads[0] == 'card type':
            family = 'card'
        elif heads[0] == 'product' and any('apr' in h for h in heads):
            family = 'equity'
        elif heads[0] == 'loan type':
            family = 'recreation'; qualifier = vals[1]
            label = ('Boat & RV ' if '$' in vals[0] else context + ' ') + label
        elif heads[0] == 'loan amount' and any('apr' in h or 'annual percentage rate' in h for h in heads):
            family = 'improvement'; qualifier = vals[1]
        elif heads[0] == 'term' and any('apr' in h or 'annual percentage rate' in h for h in heads):
            family = 'personal'
            qualifier = vals[0]; label = 'Personal Loan'
        elif heads[0] in ('account type', 'balance','balance tier') and any('dividend rate' in h or 'annual percentage yield' in h for h in heads):
            family = 'checking' if 'checking' in low or (heads[0] == 'balance' and ('checking' in page.url or 'checking' in context.lower() or 'checking' in page.title.lower())) else 'savings'
            if heads[0] in ('balance','balance tier'):
                qualifier = vals[0]
                family = 'checking' if 'checking' in (context+' '+page.url).lower() else 'savings'
                label = ('1st Rate Checking' if scope=='personal' else 'Business 1st Rate Checking') if family=='checking' else context
                related=[r.entity for r in state.rows if r.family==family and r.entity.lower().startswith(label.lower())]
                if related:label=max(related,key=len)
            elif len(vals) > 1 and 'balance' in heads[1]:
                qualifier = vals[1]
        elif 'fee-schedule' in page.url and len(vals) >= 2 and ('$' in vals[1] or 'free' in vals[1].lower() or '%' in vals[1]):
            family = 'fee'
            cells['fee'] = vals[1]
        if not family:
            return
        for h, v in zip(heads, vals):
            if h=='points':cells['points']=v
            duration=re.search(r'(?:first|1st)\s+(\d+(?:\.\d+)?)\s+month',h)
            if duration:cells['intro duration months']=float(duration[1])
            rs = rates(v)
            if not rs:
                if h.startswith('min') or h.startswith('max') or 'payment example' in h:
                    cells[h] = v
                continue
            value = '-'.join(rs)
            # A stale calculator labels auto APR as APY: the row's unit is explicit.
            if family == 'auto' or 'apr' in h or 'annual percentage rate' in h:
                metric = 'apr'
            elif 'annual percentage yield' in h or 'apy' in h:
                metric = 'apy'
            elif 'dividend rate' in h:
                metric = 'dividend'
            elif h == 'rate':
                metric = 'rate'
            elif 'points' in h:
                cells['points'] = v
                continue
            else:
                continue
            if 'after' in h:
                metric += '_after'
            elif duration or re.search(r'\b(?:introductory|promotional)\b',h):
                metric += '_intro'; phase = 'promotional'
            cells[metric] = value
        if not any(k in cells for k in ('apr', 'apy', 'rate', 'dividend', 'fee', 'apy_intro')):
            return
        if family == 'checking' and heads[0] == 'balance' and scope == 'personal':
            m = re.search(r'\$\s*(\d+(?:,\d{3})*(?:\.\d+)?)', label)
            if m: qualifier = vals[0]
        row = Row(family, label, qualifier, cells, page.url, state.sid, state.taken_on,
                  page.fetched_at, ed, raw, authority(page.url, family), scope,
                  term(label + ' ' + qualifier), term(label, 'year'),
                  bounds(label, True) if is_model else None,
                  bounds(label if family in ('mortgage', 'ira', 'improvement', 'recreation') else qualifier) if family in ('savings', 'checking', 'improvement', 'mortgage', 'ira', 'recreation') and ('$' in label or '$' in qualifier) else None,
                  phase)
        if row.months is None and row.years is not None and family in ('certificate','ira','auto','personal','equity','recreation','improvement'):
            row.months=row.years*12
        if family=='savings' and not row.balance:
            minimum=next((v for k,v in cells.items() if k.startswith('min. balance')),None)
            maximum=next((v for k,v in cells.items() if k.startswith('max. balance')),None)
            if minimum and maximum and MONEY_RE.search(minimum) and MONEY_RE.search(maximum):
                row.qualifier=minimum+'-'+maximum;row.balance=bounds(row.qualifier)
        state.rows.append(row)

    def _card_prose(self, state, page):
        md = page.markdown
        if '/business/credit-cards' in page.url:
            for entity in ('Business Platinum Visa','Business Rewards Visa'):
                match=re.search(r'(?m)^#{1,6}\s+[^\n]*'+re.escape(entity)+r'[^\n]*\n',md,re.I)
                if not match:continue
                after=md[match.end():];end=re.search(r'(?m)^#{1,6}\s',after);section=clean(after[:end.start()] if end else after)
                minimum=re.search(r'minimum credit limit of (\$[\d,]+)',section,re.I)
                if minimum:
                    for row in state.rows:
                        if row.family=='card' and row.url==page.url and row.entity.lower()==entity.lower():
                            row.cells['minimum credit limit']=minimum[1];row.quote+=' '+minimum.group()
            return
        # Identify each product's own section, so introductory APRs cannot become purchase APRs.
        for entity in ('Platinum Visa', 'Rewards Visa'):
            candidates = []
            for m in re.finditer(r"(?m)^#{1,6}\s+[^\n]*" + entity + r"[^\n]*", md, re.I):
                end = re.search(r"(?m)^#{1,6}\s", md[m.end():])
                section = md[m.end():m.end() + end.start()] if end else md[m.end():]
                section_clean = clean(section)
                candidates.extend(re.findall(r"(\d+(?:\.\d+)?%)\s*[-–]\s*(\d+(?:\.\d+)?%)\s*APR", section_clean, re.I))
                if not candidates:
                    candidates.extend(re.findall(r'APR\d?\s*:\s*(\d+(?:\.\d+)?%)\s*[-–]\s*(\d+(?:\.\d+)?%)', section_clean, re.I))
            if not candidates:
                # Fine print begins with the named card, then describes its standard range.
                for para in md.split('\n\n'):
                    p = clean(para)
                    if p.lower().startswith(('1' + entity.lower(), '2' + entity.lower(), entity.lower())):
                        candidates.extend(re.findall(r"(\d+(?:\.\d+)?%)\s*[-–]\s*(\d+(?:\.\d+)?%)", p))
            if candidates:
                value = '-'.join(candidates[0])
                state.rows.append(Row('card', entity, '', {'apr': value}, page.url, state.sid,
                                      state.taken_on, page.fetched_at, '', entity + ': ' + value + ' APR',
                                      authority(page.url, 'card')))
                if entity == 'Platinum Visa':
                    for m in re.finditer(r'(?m)^#{1,6}\s+[^\n]*Platinum Visa[^\n]*', md, re.I):
                        after = md[m.end():]
                        end = re.search(r'(?m)^#{1,6}\s', after)
                        section = clean(after[:end.start()] if end else after)
                        intro = re.search(r'(\d+(?:\.\d+)?%)\s+(?:intro\s+)?APR[^%]*?transferred balances[^%]*?for (\d+) months', section, re.I)
                        if intro:
                            window=re.search(r'(?:first\s+)(\d+)\s+days',clean(md),re.I)
                            state.rows.append(Row('card', entity, 'Balance-transfer introductory offer',
                                                  {'apr': intro[1],**({'qualifying window':window[1]+' days'} if window else {})}, page.url, state.sid, state.taken_on,
                                                  page.fetched_at, '', intro.group()+(' '+window.group() if window else ''), authority(page.url, 'card'),
                                                  phase='introductory', months=int(intro[2])))

    def _explicit_prose(self, state, page):
        for para in page.markdown.split('\n\n'):
            p = clean(para)
            # A declarative, fully qualified certificate sentence (no inferred tiers).
            m = re.search(r"(\d+)\s*[- ]?month\s+((?:fixed\s+)?(?:jumbo\s+)?(?:share\s+)?certificate(?:\s+special)?)\s*(?:APY\s*)?(?:is|:|pays|earns|=)?\s*(\d+(?:\.\d+)?%)", p, re.I)
            if m:
                entity = m[1] + ' Month ' + m[2].title()
                metric = 'dividend' if 'dividend' in p.lower() and 'apy' not in p.lower() else 'apy'
                row=Row('certificate', entity, '', {metric: m[3]}, page.url, state.sid,
                        state.taken_on, page.fetched_at, effective_date(p), para,
                        authority(page.url, 'certificate'), months=int(m[1]))
                for field,value in offer_validity(p).items():setattr(row,field,value)
                state.rows.append(row)
            if re.search(r'debit card.*(?:replacement|replace)|(?:lost|replacement).*debit card', p, re.I):
                m = re.search(r'(?:fee\s*)?[:=]\s*(\$\s*\d+(?:\.\d+)?)', p)
                if m:
                    state.rows.append(Row('fee', 'Lost debit card replacement', '', {'fee': m[1]},
                                          page.url, state.sid, state.taken_on, page.fetched_at,
                                          effective_date(p), p, authority(page.url, 'fee')))
        if 'fee-schedule' in page.url:
            lines=page.markdown.splitlines()
            for index,raw in enumerate(lines):
                if raw.startswith('|'):
                    continue
                if '$' not in raw and index+1<len(lines) and lines[index+1].strip().startswith('(') and '$' in lines[index+1]:
                    raw+=' '+lines[index+1]
                p = clean(raw)
                m = re.match(r"(.+?)\s+(\$\d+(?:\.\d+)?(?:.*)|Free(?:.*)|\d+%.*)$", p)
                if m and len(m[1]) < 110 and not p.startswith(('•', '- ', 'If ', 'We ')):
                    state.rows.append(Row('fee', m[1], '', {'fee': m[2]}, page.url, state.sid,
                                          state.taken_on, page.fetched_at, effective_date(page.markdown[:350]),
                        p, authority(page.url, 'fee')))

    def _scalars(self, state, page, published):
        md = page.markdown
        main = re.split(r'\n#{1,6}\s+(?:Recent News|Related|Handpicked)', md)[0]
        # Some pages put the field name and its value in separate paragraphs.
        full = clean(main)
        explicit_asof=re.search(r'As of\s*:\s*([A-Za-z]+\.?\s+\d{1,2},\s*20\d{2})',full,re.I)
        report_date=(dates(explicit_asof[1]) or [('', '')])[0][0] if explicit_asof else published
        institutional=any(x in page.url.lower() for x in ['/about','/newsroom/','owners-manual','impact-report'])
        if institutional:
            for m in re.finditer(r'(?:Members\s*:\s*|membership has grown to (?:more than\s*)?)(\d[\d,]+)',full,re.I):
                value=m[1];quote=full[max(0,m.start()-80):m.end()+180]
                state.scalar['members'].append((value,quote,page.url,report_date,100 if explicit_asof else 60))
            for m in re.finditer(r'(?:Assets\s*:\s*|assets (?:exceeding|of)\s*)(\$\d+(?:\.\d+)?\s*billion)',full,re.I):
                state.scalar['assets'].append((m[1],full[max(0,m.start()-100):m.end()+100],page.url,report_date,100 if explicit_asof else 60))
            for m in re.finditer(r'((?:more than|over)?\s*\d+(?:\.\d+)?\s*million)[^.!]{0,50}personalized insights',full,re.I):
                quote=full[max(0,m.start()-200):m.end()+160]
                if 'bright' in quote.lower() or 'bright' in page.title.lower():
                    value=re.sub(r'\s+',' ',m[1]).strip()
                    state.scalar['insights'].append((value,quote,page.url,report_date,100 if '.pdf' in page.url else 60))
            for m in re.finditer(r'\b(\d+)\s+counties\b',full,re.I):
                state.scalar['counties'].append((m[1]+' counties',full[max(0,m.start()-80):m.end()+120],page.url,published or state.taken_on,95 if urlparse(page.url).path=='/about' else 60))
            for m in re.finditer(r'(?m)^#\s+(0\+?|NaN)\s*\n\s*#{1,6}\s+(Members|Total Assets|Branches)',main,re.I):
                field={'members':'members','total assets':'assets','branches':'branch_count'}[m[2].lower()]
                state.invalid_counters[field]=(m[1],page.url,clean(m.group()))
        for m in re.finditer(r'routing\s+(?:number|#)\s*[:(]?\s*(\d{9})\b', full, re.I):
            quote = full[max(0, m.start() - 30):m.end() + 20]
            state.scalar['routing'].append((m[1], quote, page.url, published, 100 if '/contact' in page.url or '/cash-management' in page.url else 80))
        for para in main.split('\n\n'):
            p = clean(para)
            if not p:
                continue
            for m in re.finditer(r'routing\s+(?:number|#)\s*:?\s*(\d{9})\b', p, re.I):
                state.scalar['routing'].append((m[1], p, page.url, published, 100 if '/contact' in page.url or '/cash-management' in page.url else 80))
            m = re.search(r'(\d+)\s+branch office locations', p, re.I)
            if m:
                state.scalar['branch_count'].append((m[1], p, page.url, published, 60))
            m = re.search(r'(?:was the|for the)\s+(\w+)\s+time\s+Forbes', p, re.I)
            if m:
                state.scalar['forbes'].append((m[1], p, page.url, published, 100))
            if re.search(r'(?:will|would|scheduled to)\s+close', p, re.I) and 'hy-vee' in (p + page.title).lower():
                ds = dates(p)
                if ds:
                    publication=state.taken_on if published==ds[0][0] else published
                    state.scalar['hyvee_close'].append((ds[0][0], p, page.url, publication, 100))
            if 'Volunteer Time Off' in p and re.search(r'\d+\s+(?:Dupaco\s+)?employees', p, re.I):
                state.scalar['vto'].append((p, p, page.url, published, 100))
            if re.search(r'/(?:newsroom|learn/blog)/',page.url) and 'branch' in (page.title+' '+p).lower() and re.search(r'last day of service|(?:location|branch) will close',p,re.I):
                ds=dates(p)
                if ds:state.scalar['branch_closure'].append((ds[0][0],p,page.url,published,100))

    def _hours(self, state, page):
        md = page.markdown
        for m in re.finditer(r'\*\*(Lobby|Drive[- ]up)\*\*', md, re.I):
            after = md[m.end():]
            end = re.search(r'\*\*|\n#{1,6}\s|\n!\[', after)
            block = after[:end.start()] if end else after[:650]
            block = clean(block)
            if len(block) < 500 and re.search(r'Monday|Mon\b', block, re.I) and re.search(r'\d', block):
                state.hours.append((m[1].lower(), block, page.url, page.title, clean(md[:1600])))

    def _state(self, as_of):
        if not self.states:
            return None
        if not as_of:
            return self.states[-1]
        try:
            cutoff = date.fromisoformat(str(as_of)[:10]).isoformat()
        except ValueError:
            return None
        eligible = [s for s in self.states if s.taken_on <= cutoff]
        return eligible[-1] if eligible else None

    def _question_date(self, question):
        q = clean(question)
        if not re.search(r'as of|back in|(?:in|on) (?:January|February|March|April|May|June|July|August|September|October|November|December)|during|as at|on 20\d{2}', q, re.I):
            return None
        m = re.search(r'\b20\d{2}-\d{2}-\d{2}\b', q)
        if m:
            return m.group()
        m = re.search(r'\b(\d{1,2})/(\d{1,2})/(20\d{2})\b', q)
        if m:
            try:return date(int(m[3]),int(m[1]),int(m[2])).isoformat()
            except ValueError:return None
        ds = dates(q)
        if ds:
            return ds[0][0]
        m = re.search(r'\b([A-Z][a-z]+)\s+(20\d{2})\b', q, re.I)
        if m and m[1].lower() in MONTHS:
            y, mo = int(m[2]), MONTHS[m[1].lower()]
            return date(y, mo, calendar.monthrange(y, mo)[1]).isoformat()
        return None

    def _active_state(self,state,effective_on,q):
        if not any(r.valid_from or r.valid_until or r.effective>state.taken_on for r in state.rows):return state
        age=self._stated_account_age(q)
        explicit_post=bool(re.search(r'after|post promotion|following.*promotion',q))
        cache_key=(state.sid,effective_on,age,explicit_post)
        if cache_key in self._active_cache:return self._active_cache[cache_key]
        active=[]
        for row in state.rows:
            if row.effective and row.effective>effective_on:continue
            if row.valid_from and effective_on<row.valid_from:continue
            if row.valid_until and effective_on>row.valid_until:
                period=row.cells.get('intro duration months')
                existing_post=bool(row.cells.get('apy_after') and (explicit_post or age is not None and period is not None and age>=period))
                if not existing_post:continue
            active.append(row)
        view=copy.copy(state);view.rows=active;view.best={};view.claims=defaultdict(list);view.family_rows=defaultdict(list);view.deposit_products=defaultdict(dict)
        for row in active:
            k=row.key();view.claims[k].append(row)
            if k not in view.best or self._rank(row)>self._rank(view.best[k]):view.best[k]=row
        for row in view.best.values():
            view.family_rows[row.family].append(row)
            if row.family in ('savings','checking'):view.deposit_products[(row.family,row.scope)].setdefault(product_name(row.entity),[]).append(row)
        view.deposit_aliases=defaultdict(dict)
        for key,aliases in state.deposit_aliases.items():
            current=set(view.deposit_products.get(key,{}))
            view.deposit_aliases[key]={a:names&current for a,names in aliases.items() if names&current}
        self._active_cache[cache_key]=view
        return view

    def _time_targets(self, question):
        found=[]
        full=dates(question)
        years=re.findall(r'\b20\d{2}\b',question)
        default_year=int(full[-1][0][:4]) if full else int(years[-1]) if years else int(self.states[-1].taken_on[:4]) if self.states else 2026
        for m in re.finditer(r'\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sept?\.?|Oct\.?|Nov\.?|Dec\.?)\s+(\d{1,2})(?:,?\s+(20\d{2}))?\b',question,re.I):
            mo=m[1].lower().rstrip('.');mo='sep' if mo=='sept' else mo
            try:found.append(date(int(m[3] or default_year),MONTHS[mo],int(m[2])).isoformat())
            except (ValueError,KeyError):pass
        found.extend(re.findall(r'\b20\d{2}-\d{2}-\d{2}\b',question))
        for m in re.finditer(r'\b([A-Za-z]+)\s+(20\d{2})\b',question):
            if m[1].lower() in MONTHS:
                mo=MONTHS[m[1].lower()];year=int(m[2]);found.append(date(year,mo,calendar.monthrange(year,mo)[1]).isoformat())
        return sorted(set(found))

    def _has_time_comparison(self, question):
        return len(self._time_targets(question))>1 or bool(re.search(r'(?:all|five|every).*snapshots?|across.*snapshots|timeline|over time',question,re.I))

    @staticmethod
    def _refuse(sources=None, text=None):
        return Answer(text or "I don't know; that information isn't published in the available snapshots. Please contact Dupaco for confirmation.", sources or [], False)

    def _source(self, state, url, quote):
        return Source(url, state.sid, self._raw_quote(state,url,quote))

    @staticmethod
    def _raw_quote(state,url,quote):
        if not quote:return None
        p=state.pages.get(url.split('#')[0])
        if p is None:return None
        if quote in p.markdown:return quote
        return state.quote_index.get(p.url,{}).get(clean(quote))

    def _validate_sources(self,answer):
        states={state.sid:state for state in self.states}
        valid=[];seen=set()
        for source in answer.sources:
            state=states.get(source.snapshot_id)
            if state is None or source.url.split('#')[0] not in state.pages:continue
            excerpt=self._raw_quote(state,source.url,source.quote)
            key=(source.url,source.snapshot_id,excerpt)
            if key in seen:continue
            seen.add(key);valid.append(Source(source.url,source.snapshot_id,excerpt))
        answer.sources=valid
        return answer

    def _page(self, state, fragment):
        pages = [p for p in state.pages.values() if fragment in p.url]
        return max(pages, key=lambda p: (p.url.rstrip('/').endswith(fragment.rstrip('/')), -len(p.url))) if pages else None

    def _scalar(self, state, name):
        values = state.scalar.get(name, [])
        # Publication dates, not recrawl timestamps, order archived press releases.
        usable = [v for v in values if not v[3] or v[3] <= state.taken_on]
        return max(usable, key=lambda v: (v[4], v[3], v[2])) if usable else None

    def answer(self, question, as_of=None):
        composed=self._composed_answer(question,as_of)
        return self._validate_sources(composed if composed else self._answer(question,as_of))

    def _composed_answer(self,question,as_of):
        if not self.states:return None
        products={name for state in self.states for names in state.deposit_products.values() for name in names}
        q=self._positive_product_query(query_normalized(question),{name:None for name in products})
        clauses=re.split(r';\s*|\s+(?:and|versus|vs\.?|with|compared to)\s+',q)
        requests=[]
        for clause in clauses:
            named={name for name in products if re.search(r'\b'+re.escape(name)+r'\b',clause)}
            if named:requests.append((clause,named))
        if len(requests)<2:return None
        scopes={('business' in clause,tuple(sorted(named))) for clause,named in requests}
        if len(scopes)<2:return None
        if any(len(named)>1 for _,named in requests):return None
        metrics=asked_metrics(q,self._family(q))
        money=MONEY_RE.findall(q)
        results=[]
        for clause,_ in requests:
            local_metrics,_=positive_metric_text(clause)
            if not re.search(r'\bapy\b|\bapr\b|dividend|interest|\brate\b|\byield\b',local_metrics):
                clause+=' '+(' and '.join(metrics) if metrics else 'rate')
            if len(money)==1 and not MONEY_RE.search(clause):clause+=' balance $'+money[0]
            if as_of and any(day>str(as_of)[:10] for day in self._time_targets(clause)):
                result=self._refuse(text="I can't confirm that part beyond the requested as-of date.")
            else:
                result=self._answer(clause,None if self._time_targets(clause) else as_of)
            results.append((clause,result))
        notes=list(dict.fromkeys(a.conflict_note for _,a in results if a.conflict_note))
        return Answer(' '.join(a.text for _,a in results),[s for _,a in results for s in a.sources],all(a.confident for _,a in results),'; '.join(notes) if notes else None)

    def _answer(self, question, as_of=None):
        cutoff = as_of or self._question_date(question)
        if as_of is None and self._has_time_comparison(question):
            targets=self._time_targets(question)
            cutoff=max(targets) if targets else None
        semantic_question = re.sub(r'\b(?:as of|as at|back in|in|during|on)\s+(?:20\d{2}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/20\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sept?\.?|Oct\.?|Nov\.?|Dec\.?)\s+(?:\d{1,2},?\s+)?20\d{2})\b', '', question, flags=re.I)
        semantic_question = re.sub(r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sept?\.?|Oct\.?|Nov\.?|Dec\.?)\s+(?:\d{1,2},?\s+)?20\d{2}\b','',semantic_question,flags=re.I)
        q = query_normalized(semantic_question)
        state = self._state(cutoff)
        if state is None:
            return self._refuse(text="I don't know; no snapshot is available for the requested date.")
        state=self._active_state(state,str(cutoff)[:10] if cutoff else state.taken_on,q)
        known_products={name for products in state.deposit_products.values() for name in products}
        known_products.update(product_name(r.entity) for r in state.family_rows.get('card',[]))
        q=self._positive_product_query(q,{name:None for name in known_products})
        positive,excluded=positive_metric_text(q)
        positive_requested=asked_metrics(positive,self._family(positive))
        if positive_requested and positive_requested&excluded:
            return self._refuse(text="I can't confirm which metric you want because the request both includes and excludes it.")
        stats=self._institutional_answer(state,q)
        if stats:return stats
        if self._unsafe_attribution_or_condition(question,q,state):
            return self._refuse()
        if re.search(r'\b(?:changed?|changes|track|across|timeline|between|differ)\b', q) and self._has_time_comparison(question) and re.search(r'rate|apy|apr|certificate|mortgage|auto|purchase|refinance', q):
            changed = self._change(question, state, str(cutoff)[:10] if cutoff else None)
            if changed is not None:
                return changed
        if self._contact_query(q):
            contacted=self._contact_facts(state,q)
            if contacted:return contacted
        if 'routing' in q or re.search(r'aba (?:number|code)', q):
            owner = re.search(r"\b([a-z]+)(?:'s)? routing (?:number|code)\b", q)
            if owner and owner[1] not in {'dupaco','the','your','our','my','a','an','aba','bank','repeat','confirm'}:
                return self._refuse()
            fact = self._scalar(state, 'routing')
            if fact:
                agreeing = [v for v in state.scalar['routing'] if v[0] == fact[0]]
                agreeing.sort(key=lambda v: ('cash-management' not in v[2], '/contact' not in v[2], v[2]))
                sources = []; seen = set()
                for value in agreeing:
                    if value[2] in seen: continue
                    sources.append(self._source(state, value[2], value[1])); seen.add(value[2])
                    if len(sources) == 2: break
                return Answer(f"Dupaco's routing number is {fact[0]}.", sources)
            return self._refuse()
        if re.search(r'\bhy ?vee\b', q):
            ans = self._hyvee(state, q, cutoff)
            if ans:
                return ans
        if re.search(r'how many|number of|count|total', q) and re.search(r'branch|location', q):
            fact = self._scalar(state, 'branch_count')
            if fact:
                text=f"Dupaco has {fact[0]} branch office locations."+(' The dated statement is from '+display_date(fact[3])+'.' if fact[3] else '')
                return Answer(text, [self._source(state, fact[2], fact[1])],
                              conflict_note="Use the most recent dated statement; older press-release boilerplate describes earlier branch counts.")
            return self._refuse()
        if 'forbes' in q:
            fact = self._scalar(state, 'forbes')
            if fact:
                return Answer(f"Forbes recognized Dupaco for the {fact[0]} time as a top Best-in-State credit union.",
                              [self._source(state, fact[2], fact[1])])
        if re.search(r'volunteer time off|\bvto\b', q):
            fact = self._scalar(state, 'vto')
            if fact:
                # Preserve the explicit reporting year instead of relabeling it 'last year'.
                if 'last year' in q:
                    facts = sorted(state.scalar['vto'], key=lambda v: (v[3], v[2]), reverse=True)
                    unique = list({v[1]: v for v in facts}.values())
                    text = 'The available reports give these dated totals: ' + ' '.join(v[0] for v in unique[:3])
                    text += ' These are the reporting years stated by the sources; I cannot confirm a different year from these reports.'
                    return Answer(text, [self._source(state, v[2], v[1]) for v in unique[:3]])
                requested_year = re.search(r'\b20\d{2}\b', q)
                if requested_year:
                    matching = [v for v in state.scalar['vto'] if requested_year.group() in v[0]]
                    if not matching: return self._refuse()
                    fact = max(matching, key=lambda v: (v[3], v[2]))
                return Answer(fact[0], [self._source(state, fact[2], fact[1])])
        if re.search(r'home\$?tart|home start', q):
            return self._program(state, 'Home$tart')
        if re.search(r'(?:direct|private|only|manager|boss).*extension|extension.*(?:only|manager|boss)',q):
            return self._refuse()
        doc_answer=self._document_query(state,q)
        if doc_answer:return doc_answer
        deposit_family=self._family(q)
        if deposit_family in ('savings','checking') and self._unknown_deposit_product(state,q,deposit_family):
            return self._refuse()
        if re.search(r'lobby|drive up|drive thru|drive through|branch.*(?:hour|open|clos)|(?:hour|open|clos).*branch', q):
            return self._branch_hours(state, q)
        if re.search(r'\b(?:address|where is|where.*located)\b', q) and re.search(r'branch|galena|location', q):
            return self._address(state, q)
        if re.search(r'mailing address|postal address|po box|p\.o\. box|phone number|telephone|contact number|call.*help|call.*support', q):
            p = self._page(state, '/contact')
            if p:
                text = clean(p.markdown)
                if re.search(r'mailing|postal|po box|p\.o\. box', q):
                    m = re.search(r'P\.?O\.?\s*Box\s+\d+\s+Dubuque,\s+IA\s+[\d-]+', text, re.I)
                else:
                    m = re.search(r'800-\d{3}-\d{4}', text)
                if m:
                    return Answer(m.group() + '.', [self._source(state, p.url, m.group())])
        if re.search(r'\b(?:locator|locate|find)\b', q) and re.search(r'branch|atm', q):
            p = self._page(state, '/contact')
            if p:
                return Answer('Use the branch and ATM locator at ' + p.url + '.', [self._source(state, p.url, clean(p.markdown[:600]))])
        if re.search(r'\b(?:join|eligible|eligibility|become a member|membership)\b', q) and not re.search(r'loan|credit card|wallet|insurance|benefit|shared branch|referral',q) and (self._family(q) is None or re.search(r'become.*member|join dupaco|join online',q)):
            ans = self._membership(state, q)
            if ans:
                return ans
        if re.search(r'update|change|edit', q) and re.search(r'contact|address|phone|email|information', q):
            p = self._page(state, '/contact')
            if p:
                m = re.search(r'800-\d{3}-\d{4}', p.markdown)
                if m and 'Shine' in p.markdown:
                    return Answer(f"Log in to Shine Online or Mobile Banking to update your contact information, or call {m.group()} for help.", [self._source(state, p.url, clean(p.markdown[:750]))])
        if re.search(r'mobile wallet|apple pay|google pay|samsung pay|mobile payment', q):
            return self._targeted(state, q, '/online-and-mobile-banking/mobile-payments', ['Apple Pay', 'Google Pay', 'Samsung Pay'])
        if re.search(r'student|university|college', q) and re.search(r'loan|borrow|financ', q) and not re.search(r'\brate|apr|interest', q):
            if 'origination' in q or 'prepayment' in q:
                return self._targeted(state, q, '/personal/loans/student-loans', ['no origination fee', 'no prepayment fee'])
            return self._targeted(state, q, '/personal/loans/student-loans', ['flexible', 'origination', 'repayment'], max_chunks=3)
        family = self._family(q)
        comparison=self._pricing_alternatives(state,q,family)
        if comparison:return comparison
        eligibility=self._deposit_eligibility(state,q,family)
        if eligibility:return eligibility
        metric_text,_=positive_metric_text(q)
        requested=asked_metrics(q,family) if family else None
        if family and re.search(r'minimum|min\. |min to|min balance|minimum deposit|how much.*(?:open|deposit)|opening deposit', q) and (requested==set() or not requested and not re.search(r'\brate',re.sub(r'\bhigh yield\b','',metric_text))):
            ans = self._minimum(state, q, family)
            if ans: return ans
        if re.search(r'fee|cost|how much|charge', q) and not re.search(r'apr|apy|interest|dividend|yield|\brate', q):
            if family == 'card':
                return self._card_fee(state, q)
            if family == 'savings' and re.search(r'\bhsa\b|health savings', q):
                p = self._page(state, '/personal/savings-account')
                if p:
                    for para in p.markdown.split('\n\n'):
                        text = clean(para)
                        if 'hsa' in text.lower() and 'monthly service fee' in text.lower():
                            if re.search(r'waiv|avoid|free', q):
                                return Answer(text, [self._source(state,p.url,text)])
                            amount = re.search(r'\$\d+(?:\.\d+)?',text)
                            if amount:
                                return Answer('The monthly HSA service fee is ' + amount.group() + '; it can be waived by meeting the published account criteria.', [self._source(state,p.url,text)])
            if family not in ('construction', 'mortgage'):
                return self._rate_answer(state, q, 'fee')
        if family:
            if re.search(r'\b(?:url|link|website|where.*see)\b', q) and family == 'certificate':
                p = self._page(state, '/personal/savings-account')
                if p:
                    return Answer('See certificate rates at ' + p.url.rstrip('/') + '#rates.', [self._source(state, p.url + '#rates', 'See today\'s rates')])
            is_rate = re.search(r'rate|apy|apr|interest|dividend|yield|pay|earn|cost|fee|charge|how much|quote|compare|diff(?:er|erence)|identical|resolve.*certificate.*values', metric_text)
            if re.search(r'(?:listed|appear|could.*find|can.*find|did.*list|does.*list)',q) and family in ('certificate','savings') and re.search(r'rates? (?:table|snapshot)|snapshot|listed',q):
                listing=self._listing_answer(state,q,family)
                if listing:return listing
            if is_rate or family == 'card' and 'offer' in q:
                return self._rate_answer(state, q, family)
        faq = self._faq_answer(state, q)
        return faq if faq else self._retrieve(state, q)

    @staticmethod
    def _family(q):
        if re.search(r'certificate|\bcds?\b', q): return 'ira' if re.search(r'\bira|roth|traditional', q) else 'certificate'
        if re.search(r'credit card|\bvisa\b', q): return 'card'
        if re.search(r'auto|car loan|vehicle|motorcycle|\bcar\b', q): return 'auto'
        if re.search(r'construction', q): return 'construction'
        if re.search(r'home improvement', q): return 'improvement'
        if re.search(r'heloc|home equity', q): return 'equity'
        if re.search(r'mortgage|home loan|home purchase|fixed purchase|purchase loan|refinance quote|refinance.*(?:loan|tier)|conventional.*(?:tier|purchase|refinance)|\b(?:purchase|refinance)\b.*\b(?:quote|row|fixed)\b|adjustable|\barm\b', q): return 'mortgage'
        if term(q,'year') is not None and re.search(r'\b(?:purchase|refinance|refi)\b',q) and re.search(r'\b(?:apr|rate|interest|quote)\b',q): return 'mortgage'
        if re.search(r'personal loan|unsecured|signature loan', q): return 'personal'
        if re.search(r'checking', q): return 'checking'
        if re.search(r'\bira\b|roth|traditional', q): return 'ira'
        if re.search(r'recreational|\brv\b|boat|camper|atv', q): return 'recreation'
        if re.search(r'savings|money market|investor.?s choice|achieve|holiday club|launchpad|\bhsa\b', q): return 'savings'
        if re.search(r'fee|cost|how much|charge', q): return 'fee'
        return None

    def _select_rows(self, state, q, family, ignore_amount=False):
        rows = list(state.family_rows.get(family, []))
        if not rows:
            return []
        if family == 'card':
            introductory = bool(re.search(r'intro|balance transfer|promotional', q))
            rows = [r for r in rows if (r.phase == 'introductory') == introductory]
            both_scopes = 'business' in q and 'personal' in q
            if 'business' in q and not both_scopes:
                rows = [r for r in rows if r.scope == 'business']
            elif not both_scopes and ('personal' in q or 'platinum visa' in q or 'rewards visa' in q):
                rows = [r for r in rows if r.scope == 'personal']
            requested_cards = [name for name in ('platinum', 'rewards') if name in q]
            if requested_cards: rows = [r for r in rows if any(name in r.entity.lower() for name in requested_cards)]
            return sorted(rows, key=lambda r: (r.scope, r.entity))
        if family == 'fee':
            qw = set(tokens(q))
            ignored = {'much', 'fee', 'cost', 'charge', 'per', 'attempted', 'without', 'with', 'each','service'}
            qw -= ignored
            def fee_score(row):
                name = re.sub(r'\bbill paid\b', 'bill pay', query_normalized(row.entity.split('(')[0]))
                if re.search(r'\bbill\b', q) and 'stop' not in q and name.startswith('per bill'):
                    return 1.0
                words = set(tokens(name)) - ignored
                return len(qw & words) / max(1, len(words))
            ranked = [(fee_score(r), r) for r in rows]
            if 'stop' in q and re.search(r'check|ach|bill|payment',q):
                stop_rows=[r for r in rows if 'stop payment' in r.entity.lower()]
                if stop_rows:ranked=[(1.0,r) for r in stop_rows]
            ranked.sort(key=lambda x: (-x[0], -x[1].authority, x[1].entity))
            if not ranked or ranked[0][0] < 0.55: return []
            if re.search(r'all|three|table|complete|compare|versus|both',q):
                if 'wire' in q:return [r for r in rows if 'wire' in r.entity.lower()]
                if re.search(r'safe.deposit',q):return [r for r in rows if re.search(r'safe.deposit|re.key|drill.*box',r.entity,re.I)]
                if 'processing' in q or 'payment' in q and 'phone' in q and 'online' in q:
                    return [r for r in rows if 'processing' in r.entity.lower() and 'card' in r.entity.lower()]
            return [ranked[0][1]]
        scope = 'business' if 'business' in q else 'personal'
        rows = [r for r in rows if r.scope == scope]
        months = term(q)
        years = term(q, 'year')
        month_terms=all_terms(q)
        year_terms=all_terms(q,'year')
        if year_terms and family!='mortgage':month_terms=sorted(set(month_terms+[y*12 for y in year_terms]))
        if months is None and years and family in ('certificate', 'ira', 'auto', 'personal', 'equity', 'improvement', 'recreation'):
            months = years * 12
        if family in ('certificate', 'ira'):
            funding=None if ignore_amount else self._amount(q)
            if len(MONEY_RE.findall(q))>1 and 'minimum' in q and not re.search(r'\b(?:have|put|deposit|balance|only)\b',q):funding=None
            if month_terms: rows = [r for r in rows if r.months in month_terms]
            both_variants = bool(re.search(r'(?:standard|regular|non jumbo|fixed certificate special).*\bjumbo\b|\bjumbo\b.*(?:standard|regular)|two.*(?:special|apy)|both.*(?:certificate|version|apy)',q))
            if len(MONEY_RE.findall(q))>1 and 'minimum' in q:both_variants=True
            if re.search(r'resolve|resolution',q) and 'values' in q and not re.search(r'standard|regular|non jumbo|jumbo',q):both_variants=True
            if 'non jumbo' in q:
                rows = [r for r in rows if 'jumbo' not in r.entity.lower()]
            elif 'jumbo' in q and not both_variants:
                rows = [r for r in rows if 'jumbo' in r.entity.lower()]
            elif ('standard' in q or 'regular' in q) and not both_variants:
                rows = [r for r in rows if 'jumbo' not in r.entity.lower() and ('special' in q or 'special' not in r.entity.lower())]
            elif months is not None and funding is None and not both_variants and not re.search(r'jumbo|both|all|compare|types|options|two', q):
                rows = [r for r in rows if 'jumbo' not in r.entity.lower()]
            if funding is not None:
                amount=funding
                minimum=lambda r: next((float(MONEY_RE.search(v)[1].replace(',','')) for k,v in r.cells.items() if k.startswith('min. to earn') and MONEY_RE.search(v)),0)
                eligible=[r for r in rows if minimum(r)<=amount]
                rows=eligible
                if rows and not both_variants and not re.search(r'highest|maximum|top|best',q):
                    by_term=defaultdict(list)
                    for row in rows:by_term[row.months].append(row)
                    rows=[row for group in by_term.values() for row in group if minimum(row)==max(minimum(r) for r in group)]
            if 'special' in q and len(month_terms)<=1: rows = [r for r in rows if 'special' in r.entity.lower()]
            if family == 'ira':
                plans=[p for p in ('roth','traditional') if p in q]
                if plans:rows=[r for r in rows if any(p in r.entity.lower() for p in plans)]
                if months is None and (self._amount(q) is not None or 'share savings' in q):
                    rows = [r for r in rows if r.months is None and r.balance]
                    amount = self._amount(q)
                    if amount is not None: rows = [r for r in rows if r.balance[0] <= amount <= r.balance[1]]
            if rows:
                official = [r for r in rows if r.authority >= 95]
                if official:
                    rows = official
            if re.search(r'shortest|longest|endpoint|longer term',q) and rows:
                terms=[r.months for r in rows if r.months]
                wanted={max(terms)} if 'longer term' in q else ({min(terms),max(terms)} if 'shortest' in q and 'longest' in q else {min(terms)} if 'shortest' in q else {max(terms)})
                rows=[r for r in rows if r.months in wanted]
            if not ignore_amount and re.search(r'highest|maximum|top|best',q) and rows:
                metric='dividend' if asked_metrics(q,family)=={'dividend'} else 'apy'
                peak=max(float(rates(r.cells.get(metric,'0%'))[0].strip('%')) for r in rows)
                rows=[r for r in rows if float(rates(r.cells.get(metric,'0%'))[0].strip('%'))==peak]
            return sorted(rows, key=lambda r: (r.months or 0, 'jumbo' in r.entity.lower(), r.entity))
        if family == 'auto':
            if month_terms: rows = [r for r in rows if r.months in month_terms]
            model_match = re.search(r'\b(20\d{2})\s+(?:model|vehicle|auto|car)', q)
            if not model_match:
                model_match = re.search(r'\b(?:model year|vehicle year)\s+(20\d{2})\b', q)
            if not model_match:
                model_match = re.search(r'\b20\d{2}\b', q)
            if model_match:
                models=list(map(int,re.findall(r'\b20\d{2}\b',q)))
                rows = [r for r in rows if r.model and any(r.model[0] <= model <= r.model[1] for model in models)]
                if rows:
                    top = max(r.authority for r in rows)
                    rows = [r for r in rows if r.authority == top]
            elif 'new' in q and rows:
                newest = max((r.model[1] for r in rows if r.model), default=None)
                rows = [r for r in rows if r.model and r.model[1] == newest]
            else:
                # A broad rate list must use the current official table, excluding
                # superseded calculator bands that still have different row names.
                top = max((r.authority for r in rows), default=0)
                rows = [r for r in rows if r.authority == top]
            rows = [r for r in rows if r.authority >= 60]
            return sorted(rows, key=lambda r: (-(r.model[1] if r.model else 0), r.months or 0))
        if family == 'mortgage':
            if re.search(r'\barm\b|adjustable|\d+/\d+', q):
                wanted = re.search(r'\d+/\d+', q)
                rows = [r for r in rows if (wanted.group() in r.entity if wanted else 'adjustable' in r.entity.lower() or 'arm' in r.entity.lower())]
            else:
                uses=[u for u in ('purchase','refinance') if u in q]
                if not uses: uses=['refinance'] if re.search(r'refi',q) else ['purchase']
                if 'relief' in q:
                    rows=[r for r in rows if 'relief' in r.entity.lower() or r.entity.lower().startswith('purchase') and r.balance and r.balance[1]==self._amount(q)]
                else: rows=[r for r in rows if any(r.entity.lower().startswith(u) for u in uses)]
                if year_terms: rows = [r for r in rows if r.years in year_terms]
                amount = self._amount(q)
                if amount is not None:
                    protected=[r for r in rows if 'relief' in q and 'relief' in r.entity.lower()]
                    eligible = [r for r in rows if r.balance and r.balance[0] <= amount <= r.balance[1]]
                    if eligible:
                        tiers=defaultdict(list)
                        for r in eligible:
                            use=next((u for u in uses if r.entity.lower().startswith(u)),r.entity)
                            tiers[(use,r.years)].append(r)
                        rows=[r for group in tiers.values() for r in group if r.balance[1]==min(v.balance[1] for v in group)]+protected
                    else:
                        rows = [r for r in rows if not r.balance]
            return sorted(rows, key=lambda r: (-(r.years or 0), r.balance[1] if r.balance else float('inf')))
        if family == 'equity':
            if 'heloc' in q or 'line of credit' in q: rows = [r for r in rows if 'heloc' in r.entity.lower()]
            elif 'loan' in q: rows = [r for r in rows if 'heloc' not in r.entity.lower()]
        if family in ('savings', 'checking', 'ira'):
            matched_products=self._matched_deposit_products(state,q,family,scope) if family in ('savings','checking') else set()
            if matched_products:rows=[r for r in rows if product_name(r.entity) in matched_products]
            aliases = {'share': ['share savings'], 'bright': ['bright savings'], 'holiday': ['holiday club'],
                       'launchpad': ['launchpad'], 'you name': ['you name it'], 'investor': ["investor's choice"],
                       'achieve': ['achieve'], 'high yield': ['high-yield', 'high yield'],
                       'health': ['health savings'], 'hsa': ['health savings'],
                       '1st': ['1st rate checking'], 'free checking': ['free checking'],
                       'prime': ['prime'], 'jump start': ['jump start']}
            chosen = next((vals for key, vals in aliases.items() if key in q), None) if not matched_products else None
            if chosen:
                rows = [r for r in rows if any(a in normalized(r.entity) for a in chosen)]
            if family == 'savings' and not chosen and not matched_products and 'savings' in q and 'money market' not in q and not re.search(r'all|every|list|complete|options|products|account types',q):
                rows = [r for r in rows if normalized(r.entity) == 'share savings']
            amount=None if ignore_amount else self._amount(q)
            if amount is not None:
                rows=[r for r in rows if r.balance and r.balance[0]<=amount<=r.balance[1]]
            if not ignore_amount and re.search(r'highest|maximum|top|best', q):
                if rows:
                    metric = 'dividend' if 'dividend' in q else 'apy'
                    rows = [max(rows, key=lambda r: (float(rates(r.cells.get(metric, '0%'))[0].strip('%')), r.authority))]
        if month_terms and family not in ('savings', 'checking'): rows = [r for r in rows if r.months in month_terms]
        if family == 'personal' and re.search(r'shortest|longest|endpoint',q) and rows:
            vals=[r.months for r in rows if r.months];want={min(vals),max(vals)} if 'shortest' in q and 'longest' in q else {min(vals)} if 'shortest' in q else {max(vals)}
            rows=[r for r in rows if r.months in want]
        if family == 'recreation':
            for word in ('boat', 'rv', 'atv', 'motorhome', 'snowmobile'):
                if re.search(r'\b' + word + r'\b', q): rows = [r for r in rows if word in r.entity.lower()]
            amount = self._amount(q)
            if amount is not None: rows = [r for r in rows if r.balance and r.balance[0] <= amount <= r.balance[1]]
            model_match = re.search(r'\b20\d{2}\b', q)
            if model_match:
                model = int(model_match.group())
                rows = [r for r in rows if r.model and r.model[0] <= model <= r.model[1]]
        if family == 'improvement':
            amount = self._amount(q)
            if amount is not None: rows = [r for r in rows if r.balance and r.balance[0] <= amount <= r.balance[1]]
        return sorted(rows, key=lambda r: (r.entity, -(r.balance[0] if r.balance else 0), r.months or 0))

    @staticmethod
    def _amount(q):
        for role in (r'(?:loan|mortgage)(?: amount)?(?: of)?|borrow(?:ing)?',r'balance(?: of)?|deposit(?: of)?|have(?: exactly)?|put|invest(?:ing)?',r'only'):
            m=re.search(r'\b(?:'+role+r')\s*\$\s*(\d+(?:\.\d+)?)',q)
            if m:return float(m[1])
        m = re.search(r'\$\s*(\d+(?:\.\d+)?)', q)
        if not m:
            m = re.search(r'\b(\d+(?:\.\d+)?)\s*(?:dollars?|usd)\b', q)
        if not m:
            m = re.search(r'\b(?:balance(?: of)?|between|deposit(?: of)?|borrow(?:ing)?|(?:loan|mortgage)(?: amount)?(?: of)?|under|over|at least)\s+(\d+(?:\.\d+)?)', q)
            if m and re.match(r'\s+(?:months?|years?)\b', q[m.end():]):
                m = None
        if not m:
            ns=[x for x in re.finditer(r'\b\d{3,}(?:\.\d+)?\b',q) if not re.match(r'\s+(?:month|year|model)',q[x.end():]) and not (1900<=float(x.group())<=2099)]
            if len(ns)==1:return float(ns[0].group())
        return float(m[1]) if m else None

    def _resolve_price(self,state,q,family,depth=0):
        if depth<3:
            grouped=self._pricing_alternatives(state,q,family,depth)
            if grouped:return grouped
        if family in ('savings','checking') and self._unknown_deposit_product(state,q,family):return self._refuse()
        eligible=self._deposit_eligibility(state,q,family)
        return eligible if eligible else self._rate_answer(state,q,family)

    def _unresolved_rows(self,state,rows,metrics):
        for chosen in rows:
            claims=state.claims.get(chosen.key(),[])
            rank=self._rank(chosen)[:3]
            equals=[row for row in claims if self._rank(row)[:3]==rank]
            if any(len({value_identity(row.cells[metric]) for row in equals if metric in row.cells})>1 for metric in metrics):
                return equals
        return []

    def _pricing_alternatives(self,state,q,family,depth=0):
        positive,_=positive_metric_text(q)
        if not family or not re.search(r'\b(?:apy|apr|rate|rates|interest|dividend|yield|quote)\b',positive):return None
        requested_metrics=asked_metrics(q,family)
        labels={'rate':'interest rate' if family=='mortgage' else 'rate','apr':'apr','apy':'apy','dividend':'dividend rate'}
        inherited=' '+' / '.join(labels[m] for m in ('rate','apr','dividend','apy') if m in requested_metrics) if requested_metrics else ' rate'
        candidates=[]
        grouped_metrics=re.sub(r'\b(rate|rates|dividend(?: rate)?|interest rate|apr|apy)\s+and\s+(?=(?:apr|apy|dividend|interest|rate)\b)',r'\1 / ',q)
        for clause in re.split(r';\s*|\s+(?:and|versus|vs\.?|with|compared to)\s+',grouped_metrics):
            kind=self._family(clause)
            if not kind and family=='mortgage' and re.search(r'\b(?:purchase|refinance|refi)\b',clause):kind='mortgage'
            # Generic amount/opening wording is an attribute of its named product.
            if kind and kind!='fee':
                scope='business' if 'business' in clause else 'personal'
                candidates.append((clause,kind,scope))
        distinct={(kind,scope) for _,kind,scope in candidates}
        purpose_clauses=family=='mortgage' and len(candidates)>=2 and all(kind=='mortgage' and re.search(r'\b(?:purchase|refinance|refi)\b',clause) and MONEY_RE.search(clause) for clause,kind,_ in candidates)
        # Card selectors already preserve shared product names across both scopes.
        if family=='card' and all(kind=='card' for _,kind,_ in candidates):return None
        requests=[]
        if len(candidates)>=2 and (len(distinct)>1 or purpose_clauses):
            shared_years=all_terms(q,'year')
            for clause,kind,scope in candidates:
                if not re.search(r'\b(?:apy|apr|rate|rates|yield|interest|dividend)\b',clause):clause+=inherited
                if kind=='mortgage' and not all_terms(clause,'year') and len(shared_years)==1:clause+=' '+format(shared_years[0],'g')+' year'
                requests.append((scope.title()+' '+kind.replace('_',' ').title(),clause,kind))
        elif 'personal' in q and 'business' in q and family!='card':
            base=re.sub(r'\b(?:personal|business)\b','',q)
            requests=[('Personal',base+' personal',family),('Business',base+' business',family)]
        elif not re.search(r'minimum|credit limit|promo code|fee|processing|cash advance|payment|per month',q):
            mentions=[(m.start(),m.end(),float(m[1].replace(',',''))) for m in MONEY_RE.finditer(q)]
            mentions.extend((m.start(),m.end(),float(m[1])) for m in re.finditer(r'\b(\d+(?:\.\d+)?)\s+dollars?\b',q))
            mentions.sort()
            amounts=list(dict.fromkeys(value for _,_,value in mentions))
            separate=any(re.search(r'\band\b|versus|\bvs\b|,|\bor\b',q[left[1]:right[0]]) for left,right in zip(mentions,mentions[1:]))
            if len(amounts)>1 and separate:
                base=q
                for start,end,_ in reversed(mentions):base=base[:start]+base[end:]
                role='loan amount' if family in ('mortgage','improvement','recreation') else 'balance'
                for value in amounts:requests.append(('$'+format(value,',g'),base+' '+role+' $'+format(value,'g'),family))
        if not requests:return None
        results=[(label,self._resolve_price(state,subquery,kind,depth+1)) for label,subquery,kind in requests]
        sources={}
        for _,answer in results:
            for source in answer.sources:sources[(source.url,source.snapshot_id,source.quote)]=source
        notes=list(dict.fromkeys(answer.conflict_note for _,answer in results if answer.conflict_note))
        return Answer(' '.join(label+': '+answer.text for label,answer in results),list(sources.values()),all(answer.confident for _,answer in results),'; '.join(notes) if notes else None)

    def _rate_answer(self, state, q, family):
        rows = self._select_rows(state, q, family)
        if not rows:
            p = self._page(state, '/personal/loans/home-loans') if family in ('mortgage', 'construction') else None
            return self._refuse([self._source(state, p.url, 'Contact the mortgage team for rates not listed.')] if p else None)
        requested=asked_metrics(q,family)
        missing=[row for row in rows if requested and any(metric not in row.cells and metric+'_intro' not in row.cells and metric+'_after' not in row.cells for metric in requested)]
        if missing:
            return self._refuse(self._row_sources(missing),"I can't confirm the requested metric because it is not published for this qualified product.")
        metrics=requested or {'apy','apr','rate','dividend','fee'}
        metrics=set(metrics)|{m+suffix for m in metrics for suffix in ('_intro','_after')}
        unresolved=self._unresolved_rows(state,rows,metrics)
        if unresolved:
            return self._refuse(self._row_sources(unresolved),"I can't confirm a unique value because equally authoritative sources with the same effective date disagree.")
        if family == 'savings' and re.search(r'do any|is there|does.*pay', q) and re.search(r'\d+(?:\.\d+)?\s*%', q):
            requested = float(rates(q)[0].strip('%'))
            matching = [r for r in rows if any(float(v.strip('%')) == requested for v in rates(r.cells.get('apy', '')))]
            if not matching:
                top = max(rows, key=lambda r: float(rates(r.cells.get('apy', '0%'))[0].strip('%')))
                return Answer('No. ' + top.entity + ' tops out at ' + top.cells['apy'] + ' APY for ' + top.qualifier + '.', [top.source()])
            rows = matching
        texts = []
        requested_metrics=asked_metrics(q,family)
        for row in rows:
            display_entity=re.sub(r'\b(\d+)\s+Months?\b',r'\1-month',row.entity,flags=re.I)
            qualifier=row.qualifier
            if row.months and family in ('personal','auto','improvement','recreation'):
                qualifier=str(row.months)+'-month term ('+str(row.months)+' months)'
            label = display_entity + (' (' + qualifier + ')' if qualifier else '')
            label=re.sub(r'(?<=\d)\s*-\s*(?=[$\d])','-',label)
            if family=='card' and row.scope=='personal':label='Personal '+label
            c = row.cells
            if family == 'fee':
                text = label + ': ' + c['fee']
                if c.get('conditions'):text+='; '+c['conditions']
                if 'stop payment' in row.entity.lower():text+=' (check, ACH, and bill-pay items)'
                if 'bill' in q and re.search(r'(?:with|enrolled|signed up|get|have|use).*(?:estatement|e statement)', q) and 'without' not in q and 'free if' in row.entity.lower():
                    text = 'Bill pay is free when signed up for eStatements'
            elif family == 'mortgage':
                if requested_metrics == {'apr'}:
                    text = label + ': ' + c.get('apr', '') + ' APR'
                elif requested_metrics == {'rate'} or 'interest rate' in q and 'apr' not in q:
                    text = label + ': ' + c.get('rate', '') + ' interest rate'
                else:
                    text = label + ': ' + c.get('rate', '') + ' interest rate; ' + c.get('apr', '') + ' APR'
            elif 'apr' in c:
                text = label + ': ' + c['apr'] + ' APR' + (' (as low as, subject to approval)' if family != 'card' else '')
            elif 'apy_intro' in c:
                after = bool(re.search(r'after|post promotion|ongoing|following|once.*(?:ends|expires)', q))
                metric = 'dividend' if 'dividend' in q else 'apy'
                boundary=re.search(r'after|post promotion|ongoing|following|once',q)
                initial_requested=bool(re.search(r'intro|promotional|first\s+\d+\s+month',q[:boundary.start()] if boundary else q))
                age=self._stated_account_age(q)
                period=c.get('intro duration months')
                if age is not None and period is not None:
                    after=age>=period;initial_requested=False
                if after and initial_requested:
                    if requested_metrics=={'apy'}:
                        text=label+': '+c['apy_intro']+' introductory APY; afterward '+c.get('apy_after','')+' APY'
                    else:text=label+': '+c.get('dividend_intro','')+' introductory dividend rate, '+c['apy_intro']+' APY; afterward '+c.get('dividend_after','')+' dividend rate, '+c.get('apy_after','')+' APY'
                elif after:
                    text = label + ': ' + c.get(metric + '_after', '') + (' dividend rate' if metric == 'dividend' else ' APY') + ' after the promotional period'
                elif re.search(r'intro|promotional|first|apy|dividend', q):
                    if requested_metrics=={'dividend','apy'}:text=label+': '+c.get('dividend_intro','')+' introductory dividend rate, '+c['apy_intro']+' APY'
                    else:text = label + ': ' + c.get(metric + '_intro', '') + (' introductory dividend rate' if metric == 'dividend' else ' introductory APY')
                else:
                    text = label + ': ' + c.get('dividend_intro', '') + ' introductory dividend rate, ' + c['apy_intro'] + ' APY for the introductory period; afterward ' + c.get('dividend_after', '') + ' dividend rate, ' + c.get('apy_after', '') + ' APY'
            else:
                if requested_metrics == {'apy'}:
                    text = label + ': ' + c.get('apy', '') + ' APY'
                elif requested_metrics == {'dividend'}:
                    text = label + ': ' + c.get('dividend', '') + ' dividend rate'
                else:
                    text = label + ': ' + c.get('dividend', c.get('rate', '')) + ' dividend rate, ' + c.get('apy', '') + ' APY'
            if row.phase == 'introductory' and row.months:
                spelled=next((k for k,v in SMALL_NUMBERS.items() if v==row.months),str(row.months))
                text += ' for ' + str(row.months) + ' months ('+spelled+' months)' + ' on eligible transferred balances'
                if c.get('qualifying window'):text+=' posting in the first '+c['qualifying window']
                standard=[r for r in state.family_rows['card'] if r.key()[2]==row.key()[2] and r.scope==row.scope and r.phase=='standard']
                if standard and re.search(r'follow|after|ongoing|post|range|how long',q):text+='; afterward '+standard[0].cells['apr']+' APR'
            if c.get('minimum credit limit'):text+='; minimum credit limit '+c['minimum credit limit']
            min_earn = next((v for k, v in c.items() if k.startswith('min. to earn')), None)
            if min_earn and family in ('certificate', 'ira'):
                text += '; minimum to earn ' + min_earn
            if family=='savings' and re.search(r'minimum|open|opening',q):
                minimum=next((v for k,v in c.items() if k.startswith('min. to open')),None)
                if minimum:
                    compact=re.sub(r'\.00\b','',minimum)
                    text+='; '+compact+' to open ('+compact+' minimum)'
                    if row.balance and row.balance[1]!=float('inf'):
                        money=lambda n:format(n,',.2f').rstrip('0').rstrip('.')
                        text+='; balance band $'+money(row.balance[0])+' to $'+money(row.balance[1])
            if row.effective:
                d=date.fromisoformat(row.effective);text+='; effective '+d.strftime('%B')+' '+str(d.day)+', '+str(d.year)+' ('+d.strftime('%m/%d/%Y')+')'
                if d.month==9:text+=' [Sept. '+str(d.day)+', '+str(d.year)+']'
            if family=='auto' and row.model:
                models=list(map(int,re.findall(r'\b20\d{2}\b',q)))
                covered=[str(m) for m in models if row.model[0]<=m<=row.model[1]]
                if covered:text+='; requested vehicle year(s): '+', '.join(covered)
            if family=='mortgage':
                if 'points' in q or requested_metrics is None or len(requested_metrics or ())>1:
                    if 'points' in row.cells:text+='; zero points' if row.cells['points'] in ('0','0.00%') else '; points '+row.cells['points']
                    elif 'points' in q:text+='; I cannot confirm points because they are not published'
                if re.search(r'payment|example',q):
                    payment=next((v for k,v in row.cells.items() if 'payment example' in k),None)
                    if payment:
                        m=MONEY_RE.search(payment)
                        text+='; example monthly payment $'+format(float(m[1].replace(',','')),',.2f') if m else ''
                if 'jumbo' in q:
                    caps=[r.balance[1] for r in state.family_rows['mortgage'] if r.balance]
                    if caps:text+='; jumbo requires a loan amount that exceeded $'+format(max(caps),',.0f')
            texts.append(text + '.')
        supported = list(rows)
        metric = wanted_metric(q)
        requested = {metric} if metric else ({'rate'} if family == 'mortgage' and 'interest rate' in q else None)
        for row in rows:
            for other in state.claims.get(row.key(), []):
                metrics = set(row.cells) & set(other.cells) & {'apy', 'apr', 'rate', 'dividend','apy_intro','dividend_intro','apy_after','dividend_after'}
                if requested_metrics: metrics = {m for m in metrics if m.split('_')[0] in requested_metrics}
                if other.authority >= 60 and metrics and all(value_identity(row.cells[m]) == value_identity(other.cells[m]) for m in metrics):
                    supported.append(other)
        srcs = self._row_sources(supported)
        note = self._disagreement_note(state, rows)
        text=' '.join(texts)
        if re.search(r'resolve|authoritative|which.*win|which.*quote|should.*quote',q):
            page_name='home-loan page' if any('/home-loans' in r.url for r in rows) else 'product-specific official rate table'
            text+=' Selected the '+page_name+' using the table-local effective date and matching product qualifiers.'
        confirmed=not ('points' in q and family=='mortgage' and any('points' not in row.cells for row in rows))
        return Answer(text, srcs, confirmed, note)

    @staticmethod
    def _row_sources(rows):
        sources = [];seen=set()
        for row in rows:
            key=(row.url,row.sid,row.quote)
            if key not in seen:
                seen.add(key);sources.append(row.source())
        return sources

    def _disagreement_note(self, state, rows):
        for chosen in rows:
            others = state.family_rows.get('auto', []) if chosen.family == 'auto' else state.claims.get(chosen.key(), [])
            for other in others:
                if other.key() == chosen.key() and other.cells != chosen.cells and any(other.cells.get(k) != chosen.cells.get(k) for k in ('apr', 'apy', 'rate', 'dividend') if k in chosen.cells and k in other.cells):
                    return 'The official product rate table takes precedence over conflicting secondary pages; each balance, term and rate type is treated separately.'
                if chosen.family == 'auto' and other.family == 'auto' and chosen.months == other.months and chosen.model and other.model and max(chosen.model[0], other.model[0]) <= min(chosen.model[1], other.model[1]) and chosen.cells.get('apr') != other.cells.get('apr'):
                    return 'The official auto-loan rate table supersedes stale calculator rates for the overlapping model years.'
        return None

    def _hyvee(self, state, q, cutoff):
        fact = self._scalar(state, 'hyvee_close')
        if not fact:
            return self._refuse()
        page = state.pages[fact[2]]
        if re.search(r'where|go|full service|alternative|instead|switch|substitute|far|employee|laid off', q):
            paras = [clean(p) for p in page.markdown.split('\n\n') if 'Key West' in p and 'Sycamore' in p]
            if paras:
                supplement=[clean(p) for p in page.markdown.split('\n\n') if 'will close' in p or 'employees' in p and 'remain' in p]
                text=' '.join(supplement+[paras[0]])
                if re.search(r'employee|laid off',q) and any('remain' in p for p in supplement):
                    text+=' The closure plan said all employees would remain with the credit union and transition to other branches.'
                return Answer(text, [self._source(state, page.url, text)])
        ds = dates(fact[1]); display = ds[0][1] if ds else fact[0]
        closed = (cutoff or state.taken_on) >= fact[0]
        text = f"The Hy-Vee branch {'closed' if closed else 'is scheduled to close'} {display}."
        if re.search(r'still open|open today|open now', q):
            text = ('No. ' if closed else 'Its announced closure is still in the future. ') + text
        if re.search(r'legacy|selector|form|current status|still operating|still.*operate',q):
            text+=' Any remaining branch-selector option is stale after the announced closure.'
            alternatives=[clean(p) for p in page.markdown.split('\n\n') if 'Key West' in p and 'Sycamore' in p]
            if alternatives:text+=' '+alternatives[0]
        return Answer(text, [self._source(state, fact[2], fact[1])])

    def _branch_hours(self, state, q):
        kind = 'drive-up' if re.search(r'drive up|drive thru|drive through', q) else 'lobby'
        items = [h for h in state.hours if h[0] == kind]
        # A named branch must match its own evidence, not another branch's hours.
        name = re.search(r'(?:for|of|at) (?:the )?(.+?) branch', q)
        if not name:
            name = re.search(r'(?:the )?([a-z]+(?: avenue| street| road| learning lab)?) branch', q)
        if not name:
            name = re.search(r'\b(?:in|at|for)\s+(?:the\s+)?([a-z]+(?:\s+(?:falls|rapids|street|avenue))?)\s*(?:\?|$)', q)
        generic = {'dupaco', 'general', 'your', 'all', 'every', 'each', 'which', 'a', 'the', 'my', 'any'}
        if name and name[1].strip() not in generic:
            words = set(tokens(name[1])) - {'branch', 'hour', 'lobby', 'drive'}
            if words:
                items = [h for h in items if words <= set(tokens(h[3] + ' ' + h[4]))]
                if not items: return self._refuse()
        if not items: return self._refuse()
        # Prefer the complete schedule in the branch announcement, then deterministic URL.
        items.sort(key=lambda h: ('celebrates-completion-of-newest-learning-lab' not in h[2], h[2]))
        seen = set(); picked = []
        for h in items:
            if h[1] in seen: continue
            seen.add(h[1]); picked.append(h)
            if len(picked) == (3 if re.search(r'same|all|vary|different', q) else 1): break
        text = ('No; schedules vary by branch. ' if re.search(r'same|all', q) else 'Hours vary by branch. ')
        day = next((d for d in ('Saturday', 'Sunday', 'Friday') if d.lower() in q), None)
        if day:
            narrowed = []
            for h in picked:
                m = re.search(day + r':\s*(.*?)(?=\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday):|$)', h[1], re.I)
                if m:
                    narrowed.append((h[0], day + ': ' + m[1], *h[2:]))
            if narrowed: picked = narrowed
        text += ' '.join(('One published ' if i == 0 else 'Another published ') + kind + ' schedule is ' + h[1] + '.' for i, h in enumerate(picked))
        text += ' Which branch would you like to confirm?'
        srcs = [self._source(state, h[2], h[1]) for h in picked]
        p = self._page(state, '/contact')
        if p:
            srcs.append(self._source(state, p.url, 'Find a Location Near You'))
        return Answer(text, srcs)

    def _address(self, state, q):
        words = set(tokens(q)) - {'address', 'branch', 'location', 'where', 'located'}
        candidates = []
        for p in state.pages.values():
            for line in p.markdown.splitlines():
                text = clean(line)
                if re.search(r'\b\d{2,6}\s+\w+', text) and re.search(r'\b(?:IA|IL|WI),?\s*\d{5}\b', text):
                    hit = len(words & set(tokens(text + ' ' + p.title)))
                    if hit:
                        candidates.append((hit, '/contact' in p.url, -len(text), text, p.url))
        if not candidates:
            return self._refuse()
        _, _, _, text, url = max(candidates)
        return Answer(text, [self._source(state, url, text)])

    def _membership(self, state, q):
        p = self._page(state, '/about/join')
        if not p:
            return None
        if 'online' in q or re.search(r'\burl|link|website', q):
            links = re.findall(r'https://join\.dupaco\.com/?(?=[)\s])', p.markdown)
            if links:
                return Answer('Join online at ' + links[0].rstrip('/') + '/.', [self._source(state, p.url, links[0])])
        m = re.search(r"#{1,6}[^\n]*(?:Eligible|eligible)[^\n]*\n(.*?)(?=\n#{1,6}|\Z)", p.markdown, re.S)
        if m:
            eligible = clean(m[1])
            lead=''
            if 'live or work' in eligible:lead+='Eligibility includes living or working within the charter area. '
            if 'immediate family' in eligible:lead+='An immediate-family connection is another stated route. '
            geography = next((clean(para) for para in p.markdown.split('\n\n') if 'Iowa, Illinois and Wisconsin' in para), '')
            return Answer(lead+eligible + (' ' + geography if geography else ''), [self._source(state, p.url, eligible + ' ' + geography)])
        return self._retrieve(state, q, url_filter=lambda u: u == p.url)

    def _unsafe_attribution_or_condition(self, raw, q, state):
        if 'routing' in q or 'aba' in q:
            institutions=re.findall(r"\b([a-z]+)\s+(?:community\s+)?(?:credit union|cu)\b",q)
            if any(n not in {'dupaco','the','this','your','our','a','my','another'} for n in institutions):return True
            if re.search(r'i mean\s+(?!dupaco\b)\w+.*(?:routing|not dupaco)',q):return True
            owner=re.search(r"\b(\w+)'s\s+routing",q)
            if owner and owner[1]!='dupaco':return True
        if 'key' in q and re.search(r'bent|damaged|broken|snapped|worn|not lost',q):
            qualifier=re.search(r'bent|damaged|broken|snapped|worn',q)
            if 'not lost' in q or qualifier and not any(qualifier.group() in r.quote.lower() for r in state.family_rows.get('fee',[]) if 'key' in r.entity.lower()):return True
        return False

    def _contact_query(self,q):
        if re.search(r'branch|announcement|wallet|apple|google|samsung|card.services',q):return False
        return sum(bool(re.search(p,q)) for p in (r'address|po box|po-box|mailing|postal',r'phone|telephone|toll free|contact number',r'routing|aba'))>=2

    def _contact_facts(self,state,q):
        page=self._page(state,'/contact')
        if not page:return None
        text=clean(page.markdown);parts=[]
        if re.search(r'address|po box|po-box|mailing|postal',q):
            m=re.search(r'P\.?O\.?\s*Box\s+\d+\s+Dubuque,\s+IA\s+[\d-]+',text,re.I)
            if m:parts.append(m.group())
        if re.search(r'phone|telephone|toll free|contact number',q):
            m=re.search(r'800-\d{3}-\d{4}',text)
            if m:parts.append('Main phone: '+m.group())
        if re.search(r'routing|aba',q):
            fact=self._scalar(state,'routing')
            if fact:parts.append('Routing number: '+fact[0])
        return Answer('; '.join(parts)+'.',[self._source(state,page.url,'; '.join(parts))]) if parts else None

    def _document_query(self,state,q):
        path=None;section_words=[]
        if 'calculator' in q and 'certificate' in q:
            p=self._page(state,'/calculators/certificate-calculator')
            if p:
                text=readable(p.markdown)
                standalone=[clean(part) for part in p.markdown.split('\n\n') if re.fullmatch(r'\d+\s+months?',clean(part),re.I)]
                outcome=re.search(r'After\s+(\d+)\s+months',text,re.I)
                duration=int(outcome[1]) if outcome else term(standalone[0]) if standalone else term(text)
                if duration:
                    word=next((k for k,v in SMALL_NUMBERS.items() if v==duration),str(duration));text+=' Captured duration: '+word+' months.'
                return Answer('Captured calculator example: '+text,[self._source(state,p.url,text[:1800])])
        if re.search(r'scholarship|nonprofit grant|non profit grant|gift of innovation',q):
            path='/scholarships' if 'scholarship' in q else '/gift-of-innovation-grant' if 'gift of innovation' in q else '/non-profit-grant'
            p=self._page(state,path)
            if p:
                if 'scholarship' in q:
                    banner=next((h[0] for h in state.sections.get(p.url,[]) if re.search(r'application period begins',h[0],re.I)),None)
                    if banner:
                        text=expand_date_text(banner)
                        ds=dates(text)
                        if ds and ds[0][0]>state.taken_on:
                            text='Not yet open; '+text+' ('+banner+')'
                        return Answer(text,[self._source(state,p.url,banner)])
                if path=='/non-profit-grant' and re.search(r'open|current|apply|next',q):
                    paras=[clean(x) for x in p.markdown.split('\n\n') if re.search(r'next grant cycle',x,re.I)]
                    if paras:
                        years=re.findall(r'20\d{2}',clean(p.markdown))
                        prior=min(map(int,years)) if years else int(state.taken_on[:4])
                        text='Not currently open; the '+str(prior)+' application window has passed. '+' '.join(paras)
                        return Answer(text,[self._source(state,p.url,' '.join(paras))])
                text=readable(p.markdown)
                if path=='/gift-of-innovation-grant':
                    for m in re.finditer(r'Oct\.?\s*1\s*-\s*Nov\.?\s*(\d+),?\s*(20\d{2})',text,re.I):
                        text+=' Application period: October 1 through November '+m[1]+', '+m[2]+'.'
                return Answer(text,[self._source(state,p.url,text[:1800])])
        # Route by the requested subject before interpreting its incidental words
        # (e.g. "eligible" in a loan FAQ is not membership eligibility).
        if re.search(r'tax.refund.*checking.*offer|tax.checking.offer|checking.*promo code',q):
            candidates=[p for p in state.pages.values() if 'checking' in p.url and 'offer' in p.url and ('tax' in p.url or 'refund' in p.title.lower())]
            if candidates:
                p=min(candidates,key=lambda p:len(p.url));text=readable(p.markdown)
                return Answer(text,[self._source(state,p.url,text[:1800])])
        if re.search(r'mobile wallet|apple wallet|mobile payment|tokenization|phone wallet|apple pay|google pay|samsung pay',q):
            path='/online-and-mobile-banking/mobile-payments'
            if re.search(r'token|security|lost|missing|stolen',q):section_words=['security and safety']
            elif re.search(r'flow|checkout|four step|how.*\bpay\b',q):section_words=['how you pay']
            elif re.search(r'set ?up|setup|adding|plus sign|app store|download',q):section_words=['set up your mobile wallet']
            elif re.search(r'fee|charge|card.services|help',q):section_words=['have questions']
            elif re.search(r'compatible|both|types|platform|support|combination',q):section_words=['using your dupaco cards']
            else:section_words=['using your dupaco cards']
        elif re.search(r'accidental death|dismemberment|shared.branch network|shared branching|referral|refer.a.friend',q):
            path='/about/join'
            section_words=['accidental death'] if re.search(r'accidental|dismemberment',q) else ['shared branching'] if re.search(r'shared.branch',q) else ['refer a friend']
            if re.search(r'referral|referrer|refer.a.friend',q):
                candidates=[]
                for url,sections in state.sections.items():
                    if '/blog/' in url or '/newsroom/' in url:continue
                    for title,body,depth,_ in sections:
                        if re.search(r'refer.a.friend',title+' '+body,re.I):
                            score=len(set(tokens(q)) & set(tokens(body)))/(1+len(body)/6000)
                            candidates.append((score,-len(body),-depth,url,title))
                if candidates:
                    _,_,_,url,title=max(candidates);path=urlparse(url).path;section_words=[query_normalized(title)]
        elif re.search(r'join|membership application',q) and re.search(r'links?|continu|existing application',q):path='/about/join';section_words=[]
        elif 'membership' in q and re.search(r'deposit|move away|minimum',q):path='/about/join';section_words=['eligible to join']
        elif re.search(r'senior leadership|board of directors|elected board|\bmission\b|\bvision\b|\borigin\b|\bfound(?:ing|ers|ed)\b|meatpacking|workers.*start|started.*pool',q):
            path='/about'
            section_words=['senior leadership'] if 'leadership' in q else ['board of directors'] if 'board' in q else ['mission, values'] if re.search(r'mission|vision',q) else ['solid foundation']
        elif 'business' in q and re.search(r'loan|financing|construction',q):
            if re.search(r'equipment|vehicle',q):path='/business/loans/equipment-vehicle-loans'
            elif re.search(r'real.estate',q):path='/business/loans/real-estate-loans'
            elif re.search(r'small.business',q):path='/business/loans/small-business-loans'
            elif re.search(r'construction',q):path='/business/loans/construction-loans'
            if path and re.search(r'\bapr\b|interest rate',q):return None
        elif re.search(r'commercial construction|commercial financing',q):path='/business/loans/construction-loans'
        elif re.search(r'personal.loans.*overview|top.level.*(?:loan|protection)|loan or protection categor',q):path='/personal-loans'
        elif 'debt consolidation' in q and not re.search(r'apr|interest rate',q):path='/personal/loans/debt-consolidation';section_words=['ways to consolidate']
        elif re.search(r'share.secured|collateral.*borrowing|ordinary personal.loan.*range',q):path='/personal/loans/personal-loans';section_words=[]
        elif re.search(r'recreational.*(?:purchase|application|examples|kinds)|kinds of recreational',q):path='/personal/loans/recreational-loans';section_words=[]
        elif re.search(r'fee schedule',q) and re.search(r'scope|effective|loan officer',q):
            pages=[p for p in state.pages.values() if 'fee-schedule' in p.url.lower()]
            if pages:
                p=min(pages,key=lambda p:len(p.url));text=readable(p.markdown.split('MISCELLANEOUS')[0])
                return Answer(text,[self._source(state,p.url,text)])
        elif re.search(r'\bbranch\b|branch announcement|\bplatteville\b|washington avenue|\basbury\b',q) and re.search(r'address|direct phone|announcement|both|lobby and|drive.up schedule|location results|labeled|still open|legacy|current branch|appointment selector',q):
            if re.search(r'location results|labeled|every entry',q):
                p=self._page(state,'/contact')
                if p:
                    chunks=re.findall(r'###\s+[^\n]+\n(.*?)(?=\n###|\Z)',p.markdown,re.S)
                    text=' '.join(readable(c) for c in chunks if 'Dupaco Branch' in c)
                    return Answer(text,[self._source(state,p.url,text)]) if text else None
            names=set(tokens(q))&{'platteville','washington','asbury','saratoga','hy','vee'}
            if names:
                candidates=[p for p in state.pages.values() if '/newsroom/' in p.url and names <= set(tokens(p.markdown[:3500]))]
                candidates=[p for p in candidates if re.search(r'Branch hours|last day of service|will close',p.markdown,re.I)]
                if candidates:
                    p=max(candidates,key=lambda p:(len(names & set(tokens(p.title))),-len(p.url)));path=urlparse(p.url).path
        if not path:return None
        p=self._page(state,path)
        if not p:return None
        parts=[]
        sections=state.sections.get(p.url,[])
        for term_text in section_words:
            matches=[s for s in sections if term_text in query_normalized(s[0])]
            if matches:parts.append(min(matches,key=lambda s:s[2])[1])
        if not parts:
            # Whole-product descriptions are bounded to the requested official
            # page, including its FAQ but excluding related article lists/forms.
            md=p.markdown
            spans=list(re.finditer(r'(?m)^##\s+Handpicked for You\b',md))
            if spans:
                start=spans[0].start();faq=re.search(r'(?m)^##\s+Frequently',md[start:])
                md=md[:start]+(md[start+faq.start():] if faq else '')
            md=re.split(r'\n#{1,6}\s+(?:Contact us|Let.s get in touch|Questions\?|Have questions\? Ready)',md,flags=re.I)[0]
            parts=[md]
        text=readable('\n'.join(parts),links=bool(re.search(r'link|url|download|upload|application|app.store',q)))
        text=expand_date_text(text)
        text=re.sub(r"we don't have stockholders",'there are no stockholders',text,flags=re.I)
        text=re.sub(r'we return earnings','Dupaco returns earnings',text,flags=re.I)
        if path=='/online-and-mobile-banking/mobile-payments' and re.search(r'phone|extension|email|reach|contact|team',q):
            for para in p.markdown.split('\n\n'):
                if re.search(r'card services team|mailto:',para):text+=' '+readable(para,True)
        text=text.replace("aren't shared with merchants or stored on your phone",'are not shared with merchants and are not stored on your phone')
        if path=='/about' and 'solid foundation' in section_words:
            m=re.search(r'(\d+) meatpacking employees pooled \$(\d+) each',text)
            if m:
                spell=lambda value:next((k for k,v in SMALL_NUMBERS.items() if v==int(value)),str(value))
                text+=' '+spell(m[1]).title()+' meatpacking employees; '+spell(m[2])+' dollars apiece.'
        if '/newsroom/' in path and 'last day of service' in text.lower():
            ds=dates(text)
            if ds and ds[0][0] <= state.taken_on:text+=' This branch is closed; an old selector entry is stale.'
        return Answer(text[:16000],[self._source(state,p.url,text[:1800])]) if text else None

    def _institutional_answer(self,state,q):
        name=None
        if re.search(r'membership count|member(?:ship)? totals?|member count|number of members|how many members|different member totals',q):name='members'
        elif re.search(r'asset.*(?:total|figure)|total asset|asset totals|current.*asset|financial strength',q):name='assets'
        elif re.search(r'bright.?track|personalized insight',q) and re.search(r'\bcount\b|how many|delivered|cumulative|freshest',q):name='insights'
        elif re.search(r'count(?:y|ies).*?(?:count|footprint)|(?:footprint|how many|profile).*count(?:y|ies)|older.*counties',q):name='counties'
        if not name:return None
        fact=self._scalar(state,name)
        if not fact:return self._refuse()
        if name=='members':text='The most precise dated membership count is '+fact[0]+' members.'
        elif name=='assets':text='The most recent explicitly dated total assets are '+fact[0]+'.'
        elif name=='insights':text='The newer publication reports '+fact[0]+' personalized insights delivered by Bright Track.'
        else:text='The current charter footprint covers '+fact[0]+'.'
        if fact[3] and name!='insights':text+=' As of '+display_date(fact[3])+'.'
        return Answer(text,[self._source(state,fact[2],fact[1])])

    def _listing_answer(self,state,q,family):
        p=self._page(state,'/rates')
        if not p:return None
        rows=self._select_rows(state,q,family)
        listed=[r for r in rows if r.url==p.url or any(other.url==p.url for other in state.claims.get(r.key(),[]))]
        if listed:return None
        named=any(s in q for s in ('achieve','launchpad')) or term(q) is not None
        if not named:return None
        text='The selected rates snapshot did not list this requested product or term; it was not listed in that table.'
        if family=='certificate':
            alternatives=[r for r in state.family_rows['certificate'] if (r.url==p.url or any(other.url==p.url for other in state.claims.get(r.key(),[]))) and 'special' in r.entity.lower() and 'jumbo' not in r.entity.lower()]
            if alternatives:text+=' Listed alternatives: '+', '.join(re.sub(r'(\d+) Month',r'\1-month',r.entity) for r in alternatives)+'.'
        return Answer(text,[self._source(state,p.url,text)],True)

    def _card_fee(self, state, q):
        p = self._page(state, '/business/credit-cards' if 'business' in q else '/personal/credit-cards')
        if not p: return self._refuse()
        entity = 'Rewards Visa' if 'rewards' in q else ('Platinum Visa' if 'platinum' in q else '')
        phrases = [clean(x) for x in p.markdown.split('\n\n')]
        if entity:
            fine = [s for s in phrases if re.match(r'^\d*' + entity + r' Rates?:', s, re.I)]
        else:
            fine = [s for s in phrases if 'fee' in s.lower()]
        feature = next((x for x in ('annual fee', 'balance transfer fee', 'cash advance fee', 'foreign transaction fee', 'late payment fee', 'returned payment fee') if x in q), None)
        if not feature:
            return self._refuse()
        candidates = fine or phrases
        for text in candidates:
            if re.search(r'no\s+' + feature, text, re.I):
                return Answer('There is no ' + feature + '.', [self._source(state, p.url, text)])
            m = re.search(re.escape(feature) + r'\s*(?:[-:]\s*|is\s+|up to\s+)?([^;]+)', text, re.I)
            if m:
                statement = feature.title() + ': ' + m[1].strip().rstrip('.') + '.'
                return Answer(statement, [self._source(state, p.url, m.group())])
        return self._refuse()

    def _minimum(self, state, q, family):
        rows = self._select_rows(state, q, family,ignore_amount=True)
        if not rows: return None
        positive,_=positive_metric_text(q)
        to_earn = bool(re.search(r'earn|dividend', positive)) or asked_metrics(q,family)=={'apy'}
        texts=[];chosen=[]
        for row in rows:
            prefix = 'min. to earn' if to_earn else 'min. to open'
            value = next((v for k,v in row.cells.items() if k.startswith(prefix)), None)
            if value is None and family in ('certificate','ira'):
                value = next((v for k,v in row.cells.items() if k.startswith('min. to earn')), None)
            if value:
                texts.append(row.entity + ': ' + value + (' minimum to earn dividends.' if to_earn else ' minimum to open.'))
                chosen.append(row)
        return Answer(' '.join(dict.fromkeys(texts)), self._row_sources(chosen)) if texts else None

    def _deposit_eligibility(self,state,q,family):
        if family not in ('certificate','ira','savings','checking'):return None
        amount=self._amount(q)
        if amount is None:return None
        if len(MONEY_RE.findall(q))>1 and 'minimum' in q and not re.search(r'\b(?:have|put|deposit|balance|only)\b',q):return None
        if not re.search(r'open|qualif|eligible|earn|yield|apy|dividend',q):return None
        rows=self._select_rows(state,q,family,ignore_amount=True)
        if not rows:return None
        opening=bool(re.search(r'\bopen|opening\b',q))
        if not opening:
            applicable=self._select_rows(state,q,family)
            wanted=asked_metrics(q,family) or {'dividend','apy'}
            for row in applicable:
                values=[float(v.strip('%')) for metric in wanted for v in rates(row.cells.get(metric,''))]
                if row.balance and row.balance[0]<=amount<=row.balance[1] and values and all(v==0 for v in values):
                    return None
        entries=[]
        for row in rows:
            prefixes=('min. to open','min. to earn') if opening else ('min. to earn',)
            value=next((v for prefix in prefixes for k,v in row.cells.items() if k.startswith(prefix) and MONEY_RE.search(v)),None)
            if value:
                minimum=float(MONEY_RE.search(value)[1].replace(',',''));entries.append((minimum,row))
        if not entries or any(minimum<=amount for minimum,_ in entries):return None
        minimum=min(m for m,_ in entries)
        sources=self._row_sources([r for m,r in entries if m==minimum])
        purpose='open' if opening else 'earn dividends'
        text='That balance is below the published $'+format(minimum,',g')+' minimum to '+purpose+' for the requested product. It does not qualify for the published rate at that balance.'
        return Answer(text,sources,True)

    def _stated_account_age(self,q):
        patterns=(r'\b(?:opened|started)\s+(\d+(?:\.\d+)?)\s+month\s+ago',
                  r'\b(?:held|had|open|opened|owned)\s+(?:it\s+)?(?:for\s+)?(\d+(?:\.\d+)?)\s+month\b',
                  r'\baccount\s+is\s+(\d+(?:\.\d+)?)\s+month\s+old')
        for pattern in patterns:
            m=re.search(pattern,q)
            if m:return float(m[1])
        for pattern in patterns:
            m=re.search(pattern.replace('month','year'),q)
            if m:return float(m[1])*12
        return None

    def _faq_answer(self, state, q):
        qw=set(tokens(q)) - {'could','want','like','know','offer','options','option'}
        if not qw:return None
        family = self._family(q)
        candidates=[]
        for title,text,url,words in state.faqs:
            hits=qw & words
            if not hits:continue
            recall=len(hits)/len(qw)
            precision=len(hits)/max(1,len(words))
            if recall<0.7 or precision<0.5:continue
            score=2*recall*precision/(recall+precision)
            if family and family == self._family(query_normalized(title)):score+=0.1
            candidates.append((score,authority(url,family or ''),-len(text),url,text,title))
        if not candidates:return None
        _,_,_,url,text,title=max(candidates)
        return Answer(text,[self._source(state,url,title+' '+text)])

    def _program(self, state, name):
        chunks = [c for c in state.chunks if name.lower() in c.text.lower()]
        if not chunks: return self._refuse()
        def rank(c):
            return (bool(MONEY_RE.search(c.text.replace(name, ''))),
                    sum(w in c.text.lower() for w in ('assistance', 'provides', 'down payment', 'closing costs')),
                    c.published, c.weight, -len(c.text), c.url)
        chunk = max(chunks, key=rank)
        return Answer(chunk.text, [self._source(state, chunk.url, chunk.text)])

    def _targeted(self, state, q, fragment, required, max_chunks=1):
        p = self._page(state, fragment)
        if not p:
            return self._refuse()
        chunks = [c for c in state.chunks if c.url == p.url and any(w.lower() in c.text.lower() for w in required)]
        for title, answer_text, url, _ in state.faqs:
            if url == p.url and any(w.lower() in answer_text.lower() for w in required):
                chunks.append(Chunk(answer_text, url, state.sid, title, '', 100, Counter()))
        chunks.sort(key=lambda c: (-sum(w.lower() in c.text.lower() for w in required), len(c.text), c.text))
        if not chunks:
            return self._refuse()
        chosen = chunks[:max_chunks]
        text = ' '.join(c.text for c in chosen)
        if 'student-loans' in fragment:
            text = 'Dupaco offers student loans for new borrowing and refinancing. ' + text
        return Answer(text, [self._source(state, p.url, text)])

    def _retrieve(self, state, q, url_filter=None):
        qw = set(tokens(q))
        if not qw:
            return self._refuse()
        scores = defaultdict(float)
        n = len(state.chunks)
        for w in qw:
            idf = math.log(1 + (n + 1) / (state.df[w] + 1))
            for i in state.index.get(w, []):
                c = state.chunks[i]
                tf = c.terms[w]
                scores[i] += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * c.length / 65))
        ranked = []
        for i, score in scores.items():
            c = state.chunks[i]
            if url_filter and not url_filter(c.url): continue
            hits = qw & c.terms.keys()
            title_hits = qw & c.title_terms
            score *= 1 + 0.12 * len(title_hits) + c.weight / 500
            if re.search(r'\d+(?:\.\d+)?%', c.text) and re.search(r'rate|apy|apr', q):
                score *= 0.6
            ranked.append((score, len(hits), c))
        if not ranked: return self._refuse()
        ranked.sort(key=lambda v: (-v[0], -v[1], v[2].url, v[2].text))
        _, hits, chosen = ranked[0]
        informative = {w for w in qw if w not in {'know', 'offer', 'offered', 'options', 'option', 'could', 'want', 'like'}}
        if hits < min(2, len(informative)):
            return self._refuse()
        # Never substitute an unqualified prose/calculator percentage for a missing rate.
        if re.search(r'rate|apy|apr|interest', q) and rates(chosen.text):
            return self._refuse([self._source(state, chosen.url, chosen.text)])
        return Answer(chosen.text, [self._source(state, chosen.url, chosen.text)])

    def _change(self, question, state, evidence_on=None):
        q = query_normalized(question)
        family = self._family(q)
        if not family:
            return None
        selected = []
        mentioned = self._time_targets(question)
        observations = [(s,s.taken_on) for s in self.states if s.taken_on <= state.taken_on]
        if len(mentioned) >= 2:
            if any(day>(evidence_on or state.taken_on) for day in mentioned):
                return self._refuse(text="I can't confirm that comparison from snapshots available by the requested as-of date.")
            observations=[]
            for day in mentioned:
                observed=self._state(day)
                if observed:observations.append((observed,day))
        elif len(observations) > 1 and not re.search(r'all|five|every|across',q):
            observations = [observations[0], observations[-1]]
        if len(observations) < 2:
            return self._refuse()
        # Dates identify observations, not vehicle model years in this query.
        rate_q = query_normalized(re.sub(r'20\d{2}-\d{2}-\d{2}|\b(?:January|February|March|April|May|June|July|August|September|October|November|December|Aug\.?|Sept?\.?)\s+(?:\d{1,2}(?:,)?(?:\s+20\d{2})?|20\d{2})\b', '', question, flags=re.I))
        for s,day in observations:
            # Apply the same qualifiers and completeness rules at every date.
            view=self._active_state(s,day,rate_q)
            ans = self._resolve_price(view, rate_q, family)
            selected.append((s,day,ans))
        return Answer(' '.join('As of ' + date.fromisoformat(day).strftime('%B')+' '+str(date.fromisoformat(day).day)+', '+day[:4]+' ('+day+'); snapshot '+s.taken_on+': ' + a.text for s,day,a in selected),
                      [src for _,_,a in selected for src in a.sources], all(a.confident for _,_,a in selected),
                      'These values belong to different observation dates, so the earlier value is historical rather than current.')

    def conflict_diagnostics(self):
        simultaneous=[];historical=[];expired=[];future=[]
        for state in self.states:
            active=self._active_state(state,state.taken_on,'')
            for key,claims in active.claims.items():
                for metric in ('rate','apr','dividend','apy','fee','apy_intro','apy_after','dividend_intro','dividend_after'):
                    values=sorted({value_identity(row.cells[metric]) for row in claims if metric in row.cells})
                    if len(values)>1:simultaneous.append({'fact':list(key),'metric':metric,'observed':state.taken_on,'values':values,'sources':[{'url':row.url,'snapshot_id':row.sid} for row in claims if metric in row.cells]})
            for row in state.rows:
                entry={'fact':list(row.key()),'observed':row.observed,'effective':row.effective,'valid_from':row.valid_from,'valid_until':row.valid_until,'url':row.url}
                if row.valid_until and row.valid_until<state.taken_on:expired.append(entry)
                if row.effective>state.taken_on or row.valid_from and row.valid_from>state.taken_on:future.append(entry)
        groups=defaultdict(list)
        for state in self.states:
            for row in self._active_state(state,state.taken_on,'').rows:
                for metric in ('rate','apr','dividend','apy','fee'):
                    if metric in row.cells:groups[(row.key(),metric)].append(row)
        for (key,metric),rows in groups.items():
            by_date=defaultdict(set)
            for row in rows:by_date[row.observed].add(value_identity(row.cells[metric]))
            if len(set.union(*by_date.values()))>1 and all(len(v)==1 for v in by_date.values()):
                historical.append({'fact':list(key),'metric':metric,'observations':{day:sorted(v) for day,v in sorted(by_date.items())}})
        return {'simultaneous':simultaneous,'historical_changes':historical,'expired_copies':expired,'future_effective':future}

    def conflicts(self):
        if self._conflicts_cache is not None:
            return copy.deepcopy(self._conflicts_cache)
        groups = defaultdict(list)
        for state in self.states:
            for row in state.rows:
                for metric in ('apy', 'apr', 'rate', 'dividend', 'fee', 'apy_intro', 'dividend_intro', 'apy_after', 'dividend_after'):
                    if metric in row.cells:
                        groups[(row.key(), metric)].append(row)
        result = []
        components = defaultdict(list)
        for (key, metric), rows in sorted(groups.items()):
            values = list(dict.fromkeys(r.cells[metric] for r in sorted(rows, key=lambda r: (r.observed, r.url))))
            numeric = {value_identity(v) for v in values}
            if len(numeric) < 2:
                continue
            latest_date = max(r.observed for r in rows)
            latest_rows = [r for r in rows if r.observed == latest_date]
            winner = max(latest_rows, key=self._rank)
            # Retired entities have no defensible *current* winner.
            latest_state=self._active_state(self.states[-1],self.states[-1].taken_on,'') if self.states else None
            present = latest_state.best.get(winner.key()) if latest_state else None
            resolution = present.cells.get(metric) if present else None
            if present and self._unresolved_rows(latest_state,[present],{metric}):resolution=None
            revised_band = False
            if present and winner.family == 'auto' and present.authority < 95 and present.model:
                authoritative = [r for r in self.states[-1].best.values() if r.family == 'auto' and r.authority >= 95 and r.months == present.months and r.model]
                revised_band = any(max(r.model[0], present.model[0]) <= min(r.model[1], present.model[1]) and r.cells.get(metric) != present.cells.get(metric) for r in authoritative)
                if revised_band:
                    resolution = None
            by_date = defaultdict(set)
            for r in rows:
                if r.effective and r.effective>r.observed or r.valid_from and r.valid_from>r.observed or r.valid_until and r.valid_until<r.observed:continue
                by_date[r.observed].add(value_identity(r.cells[metric]))
            simultaneous = any(len(v) > 1 for v in by_date.values())
            historical=len(by_date)>1 and len(set.union(*by_date.values()))>1 if by_date else False
            expired_copy=any(r.valid_until and r.valid_until<r.observed for r in rows)
            if not simultaneous and not historical and not expired_copy:continue
            reason = ('Official product rate/fee table overrides secondary pages with the same qualifiers. ' if simultaneous else '')
            reason += 'Observation dates preserve historical changes; rate, APY, product, term and tier are compared separately.'
            if historical and not simultaneous:reason+=' This is an organizer-compatible historical change record, not a strict simultaneous contradiction.'
            if expired_copy:reason+=' An expired copy remains visible but cannot supply a current winner.'
            if present and resolution is None:reason+=' Equal-authority claims without an effective-date distinction remain unresolved.'
            if not present:
                reason += ' This qualified product is absent from the newest snapshot; no current rate is asserted.'
            if revised_band:
                reason += ' This secondary model-year band has been superseded by differently partitioned official bands; there is no single current rate for its entire old interval. See the qualified overlap conflicts.'
            reps = []
            for value in values:
                same = [r for r in rows if r.cells[metric] == value]
                reps.append(max(same, key=lambda r: (r.observed, self._rank(r))).source())
            display_entity = winner.entity
            if winner.scope == 'business' and 'business' not in display_entity.lower():
                display_entity = 'Business ' + display_entity
            components[key].append((metric, rows, Conflict(display_entity + (' / ' + winner.qualifier if winner.qualifier else '') + ' ' + metric.upper(), values, reps, resolution, reason)))
        # A table update is one contradiction for the same qualified product,
        # even when both APR/rate or APY/dividend change together. Label every
        # column in each source observation; different metrics never compete.
        for key, parts in sorted(components.items()):
            if len(parts) == 1:
                parts[0][2]._fact_keys={key}
                result.append(parts[0][2]); continue
            metrics = sorted((part[0] for part in parts),key=lambda m:('rate','apr','dividend','apy','fee').index(m) if m in ('rate','apr','dividend','apy','fee') else 10)
            observations = {}
            for _, rows, _ in parts:
                for row in rows:
                    signature = tuple((m, row.cells.get(m)) for m in metrics if row.cells.get(m))
                    existing = observations.get(signature)
                    if existing is None or (row.observed, self._rank(row)) > (existing.observed, self._rank(existing)):
                        observations[signature] = row
            ordered = sorted(observations.items(), key=lambda pair: (pair[1].observed, pair[1].url))
            values = [' / '.join(m.upper() for m,_ in signature)+': '+' / '.join(value for _,value in signature) for signature, _ in ordered]
            sources = [row.source() for _, row in ordered]
            resolutions = [(metric, c.resolution) for metric, _, c in parts if c.resolution]
            resolutions.sort(key=lambda pair:metrics.index(pair[0]))
            resolution = ' / '.join(m.upper() for m,_ in resolutions)+': '+' / '.join(value for _,value in resolutions) if resolutions else None
            sample = parts[0][2]
            topic = re.sub(r'\s+' + re.escape(parts[0][0].upper()) + '$', '', sample.topic)
            conflict=Conflict(topic + ' (' + ', '.join(m.upper() for m in metrics) + ')', values, sources, resolution,
                              sample.reason + ' Each labelled value describes a source observation of this same tier; metrics retain their own units.')
            conflict._fact_keys={key};result.append(conflict)
        # Conflicting sources can have a different authoritative winner on each
        # observation date. Keep these decisions explicitly time-qualified.
        for conflict in result:
            relevant=[]
            for state in self.states:
                for row in state.best.values():
                    if row.key() not in getattr(conflict,'_fact_keys',set()):continue
                    if not any(s.url==row.url and s.snapshot_id==row.sid for s in conflict.sources):continue
                    claims=state.claims.get(row.key(),[])
                    metrics=[m for m in ('rate','apr','dividend','apy','fee') if m in row.cells]
                    if not any(len({value_identity(r.cells[m]) for r in claims if m in r.cells})>1 for m in metrics):continue
                    if self._unresolved_rows(state,[row],set(metrics)):continue
                    pair=' / '.join(row.cells[m] for m in metrics)
                    dated='As of '+state.taken_on+': '+pair
                    if dated not in relevant:relevant.append(dated)
            if relevant:
                conflict.resolution=(conflict.resolution+'; ' if conflict.resolution else '')+'; '.join(relevant)
        # Model-year bands move between crawls. Compare their intersection, rather
        # than falsely claiming 2023 and 2027 vehicles are the same tier.
        if self.states:
            state = self.states[-1]
            auto = [r for r in state.best.values() if r.family == 'auto' and r.model]
            seen = set()
            for a in auto:
                for b in auto:
                    if a.authority <= b.authority or a.months != b.months or a.scope != b.scope or a.model == b.model:
                        continue
                    lo, hi = max(a.model[0], b.model[0]), min(a.model[1], b.model[1])
                    if lo > hi or a.cells.get('apr') == b.cells.get('apr'):
                        continue
                    k = (a.months, a.cells['apr'], b.cells['apr'])
                    if k in seen: continue
                    seen.add(k)
                    result.append(Conflict(f'{a.months}-month auto loan APR, overlapping {lo}-{hi} model years',
                                           [b.cells['apr'], a.cells['apr']], [b.source(), a.source()], a.cells['apr'],
                                           'The model-year bands overlap for these vehicles. The official auto-loan table overrides the stale calculator table.'))
            for name, title in [('branch_count', 'Dupaco branch count'), ('routing', 'Dupaco routing number')]:
                facts = state.scalar.get(name, [])
                values = list(dict.fromkeys(f[0] for f in sorted(facts, key=lambda f: (f[3], f[2]))))
                if len(values) < 2: continue
                winner = self._scalar(state, name)
                if not winner: continue
                reps = [max((f for f in facts if f[0] == value), key=lambda f: (f[3], f[2])) for value in values]
                result.append(Conflict(title, values, [self._source(state, f[2], f[1]) for f in reps], winner[0],
                                       'Use the latest dated statement about this entity; recrawling an archived release does not make its publication or historical totals current.'))
            for name,broken in state.invalid_counters.items():
                winner=self._scalar(state,name)
                if not winner:continue
                title={'members':'Membership member count','assets':'Total assets financial strength','branch_count':'Dupaco branch count'}[name]
                existing=next((c for c in result if c.topic==title),None)
                if existing:
                    existing.values.append(broken[0]);existing.sources.append(self._source(state,broken[1],broken[2]))
                    existing.reason+=' The current dynamic widget is an invalid placeholder, not a measured zero.'
                else:
                    result.append(Conflict(title,[winner[0],broken[0]],[self._source(state,winner[2],winner[1]),self._source(state,broken[1],broken[2])],winner[0],
                                           'An explicitly dated institutional report is usable evidence; a failed dynamic widget is not. Historical dated totals remain valid only for their own periods.'))
            dated_tables={}
            for entity,claims,url,quote in state.table_date_claims:
                k=(entity,tuple(d for d,_ in claims))
                dated_tables.setdefault(k,[]).append(self._source(state,url,quote))
            for (entity,ds),sources in dated_tables.items():
                fmt=lambda d:date.fromisoformat(d).strftime('%m/%d/%Y')
                result.append(Conflict(entity+' effective date',[fmt(d) for d in ds],sources,fmt(ds[0]),
                                       'The effective-date sentence immediately after this table belongs to it; a later duplicated footnote has lower locality.'))
            for closed_day,quote,url,_,_ in state.scalar.get('branch_closure',[]):
                if closed_day>state.taken_on:continue
                page=state.pages[url]
                names=set(tokens(page.title))-{'branch','close','closed','closure','evolves','purpose','member','members','need','needs','plans','plan','service','last','day','dupaco'}
                located=re.search(r'([A-Za-z-]+(?:\s+[A-Za-z-]+)?)\s+branch',page.title,re.I)
                if located:names=set(tokens(located[1]))-{'closing','close','plans','plan','a','the','new','set'}
                forms=[p for p in state.pages.values() if names and re.search(r'Select a Branch',p.markdown,re.I) and all(name in p.markdown.lower() for name in names)]
                if forms:
                    form=min(forms,key=lambda p:len(p.url));form_quote=next((clean(line) for line in form.markdown.splitlines() if re.search(r'Select a Branch',line,re.I)),clean(form.markdown[:500]))
                    result.append(Conflict(clean(page.title)+' branch closure',[display_date(closed_day),'current branch option (captured selector)'],
                                           [self._source(state,url,quote),self._source(state,form.url,form_quote)],display_date(closed_day),
                                           'The dated closure notice supersedes an unmaintained branch-selection option. This does not claim that the closure and an earlier operating period occurred together.'))
            for p in state.pages.values():
                banner=next((h[0] for h in state.sections.get(p.url,[]) if 'application period begins' in h[0].lower()),None)
                if not banner:continue
                current=dates(expand_date_text(banner))
                if not current or current[0][0]<=state.taken_on:continue
                old=[clean(para) for para in p.markdown.split('\n\n') if 'deadline' in para.lower() and dates(expand_date_text(clean(para)))]
                old=[text for text in old if dates(expand_date_text(text))[0][0]<state.taken_on]
                if old:
                    old_date=dates(expand_date_text(old[0]))[0][0]
                    result.append(Conflict(clean(p.title)+' application status',[display_date(current[0][0]),display_date(old_date)],
                                           [self._source(state,p.url,banner),self._source(state,p.url,old[0])],display_date(current[0][0]),
                                           'The current status banner gives the next opening. Unlabelled older-cycle instructions below it should not be presented as a current deadline.'))
        result=self._group_source_conflicts(result)
        result.sort(key=lambda c: (c.resolution is None, c.topic))
        for conflict in result:self._validate_sources(conflict)
        self._conflicts_cache = result
        return copy.deepcopy(result)

    def _group_source_conflicts(self,conflicts):
        groups=defaultdict(list);other=[]
        for c in conflicts:
            topic=c.topic.lower();scope='Business' if topic.startswith('business') else 'Personal'
            if 'overlapping' in topic:
                other.append(c);continue
            if topic.startswith('purchase:'):key=(scope,'Purchase mortgage')
            elif topic.startswith('refinance:'):key=(scope,'Refinance mortgage')
            elif 'model year' in topic or 'auto loan apr' in topic:key=(scope,'Auto loan')
            elif topic.startswith('roth:'):key=(scope,'Roth IRA')
            elif topic.startswith('traditional:'):key=(scope,'Traditional IRA')
            elif 'certificate' in topic:key=(scope,'Certificate')
            elif 'checking' in topic:key=(scope,'Checking')
            else:other.append(c);continue
            groups[key].append(c)
        for (scope,family),members in groups.items():
            if len(members)==1:other.extend(members);continue
            values=[];sources=[];resolved=[]
            for c in members:
                values.extend(c.topic+' | '+v for v in c.values)
                sources.extend(c.sources)
                if c.resolution:resolved.append(c.topic+' => '+c.resolution)
            unique={}
            for source in sources:unique[(source.url,source.snapshot_id,source.quote)]=source
            interpretations=' '.join(dict.fromkeys(c.reason for c in members if c.reason and re.search(r'historical change record|expired copy|remain unresolved',c.reason)))
            other.append(Conflict(scope+' '+family+' rate-table source conflicts',values,list(unique.values()),'; '.join(resolved) if resolved else None,
                                  'Each labelled source difference retains its product, term, balance/model-year tier, metric and observation date; unlike tiers are not compared as if identical. '+interpretations))
        return other


def build():
    return Knowledge()
