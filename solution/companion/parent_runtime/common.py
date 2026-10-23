"""Shared, snapshot-local helpers. No external data or dependencies."""
import re
import html
import difflib
import copy
from urllib.parse import urlsplit
from evidence import raw_spans


def clean(text):
    text = html.unescape(html.unescape(text))
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'<[^>]+>', '', text)
    return re.sub(r'\s+', ' ', text.replace('**', '').replace('__', '')).strip()


class Context:
    def __init__(self, snapshot):
        self.sid = snapshot.snapshot_id
        self.date = snapshot.taken_on
        # Keep indexed text and provenance on owned observation objects.
        self.pages = copy.deepcopy(list(snapshot.pages))
        self.by_path = {}
        for p in self.pages:
            parsed=urlsplit(p.url)
            path=parsed.path.rstrip('/')
            old=self.by_path.get(path)
            old_url=urlsplit(old.url) if old else None
            rank=(bool(parsed.fragment),bool(parsed.query),len(p.url))
            old_rank=(bool(old_url.fragment),bool(old_url.query),len(old.url)) if old else None
            if old_rank is None or rank<old_rank:
                self.by_path[path]=p
        self.cache = {}
        self._alias_pages={}

    def find(self, *paths):
        for path in paths:
            p = self.by_path.get(path.rstrip('/'))
            if p is not None:
                return p
        # Stable semantic labels can route renamed URLs. A tie remains unknown;
        # URL order must never silently resolve ambiguous equally suitable pages.
        for path in paths:
            if path in self._alias_pages:
                p=self._alias_pages[path]
                if p is not None:return p
                continue
            words=set(re.findall(r'[a-z]+',path.lower()))-{'personal','business','account','accounts','loans','loan'}
            scored=[]
            for page in self.pages:
                label=(page.title+' '+' '.join(page.markdown.splitlines()[:3])).lower()
                requested_business=path.startswith('/business')
                declared_business=bool(re.search(r'\bbusiness\b|\bcommercial\b',label))
                declared_personal=bool(re.search(r'\bpersonal\b|\bconsumer\b',label))
                if declared_business and not requested_business or declared_personal and requested_business:continue
                title=set(re.findall(r'[a-z]+',page.title.lower()))
                header=set(re.findall(r'[a-z]+',' '.join(page.markdown.splitlines()[:3]).lower()))
                score=len(words & (title|header))
                if score>=max(1,len(words)) and not re.search(r'blog|news|calculator',page.title,re.I):
                    scored.append((score,page))
            best=max((n for n,_ in scored),default=0)
            candidates=[p for n,p in scored if n==best]
            p=candidates[0] if len(candidates)==1 else None
            self._alias_pages[path]=p
            if p:return p
        return None

    def reply(self, text, pages=(), confident=True, note=None, quote=None):
        text = re.sub(r'(?<=\d)\s*[-–—]\s*(?=\$?\d)', '-', text)
        text = re.sub(r'(?<=%)\s*[-–—]\s*(?=\d)', '-', text)
        # Normalize capitalized table product names; ordinary narrative units
        # such as "24 to 60 months" stay grammatical and preserve source terms.
        text = re.sub(r'\b(\d+)\s+Months?\b', r'\1-month', text)
        if not isinstance(pages, (list, tuple)):
            pages = [pages]
        sources = []
        for p in pages:
            if p is not None and p in self.pages and p.url not in {s['url'] for s in sources}:
                spans=raw_spans(p.markdown,quote,clean)
                # The optional contract quote is one real span, never a
                # manufactured combination of unrelated rows or sentences.
                excerpt=spans[0].text if spans else None
                sources.append({'url': p.url, 'snapshot_id': self.sid,
                                'quote': excerpt})
        return {'text': text, 'sources': sources, 'confident': confident,
                'conflict_note': note}


def numbers(text):
    return re.findall(r'(?:\$\s*)?\d[\d,]*(?:\.\d+)?\s*%?', text)


def requested_metrics(question, family='deposit'):
    """Identify positive metric requests before formatting source values.

    Explicit exclusions do not count as requests. The ambiguous word 'rate'
    retains both deposit measures, while mortgage rate and APR stay separate.
    """
    q = question.lower()
    patterns = ({'dividend': r'dividends?(?:\s+rate)?|nominal(?:\s+(?:interest\s+)?rate)?',
                 'apy': r'apys?|annual\s+(?:percentage\s+)?yield|yield(?=\s+(?:on|for|of|at|in)\b)'} if family == 'deposit' else
                {'rate': r'(?:nominal\s+)?interest\s+rate|nominal\s+rate|rates?',
                 'apr': r'aprs?|annual\s+percentage\s+rate'})
    exclusions = set()
    for metric, pattern in patterns.items():
        neg = r"\b(?:not|excluding|exclude|without|rather than|instead of|do not(?: give(?: me)?)?|don't(?: give(?: me)?)?|dont(?: give(?: me)?)?)\s+(?:(?:the|its|their|my|your)\s+)?(?:" + pattern + r')\b'
        if re.search(neg, q):
            exclusions.add(metric)
        q = re.sub(neg, ' ', q)
    # Remove the long APR label before searching the generic word rate.
    positive = set()
    if family == 'deposit' and re.search(r'\brate\s*(?:and|/|,)\s*(?:the\s+)?(?:apy|yield)\b|\b(?:apy|yield)\s*(?:and|/|,)\s*(?:the\s+)?rate\b', q):
        positive.add('dividend')
        positive.add('apy')
    if family == 'deposit' and re.search(r'\byield\s*(?:and|/|,)\s*(?:the\s+)?dividend|\bdividend(?: rate)?\s*(?:and|/|,)\s*(?:the\s+)?yield\b',q):
        positive.add('apy')
    for metric in (['apy', 'dividend'] if family == 'deposit' else ['apr', 'rate']):
        pattern = patterns[metric]
        if re.search(r'\b(?:' + pattern + r')\b', q):
            positive.add(metric)
            q = re.sub(r'\b(?:' + pattern + r')\b', ' ', q)
    return (positive or set(patterns)) - exclusions


_SMALL = dict(zip('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(),range(20)))
_TENS = dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(),range(20,100,10)))
_SCALES = {'hundred':100,'thousand':1000,'million':1000000,'billion':1000000000,'grand':1000}


def _word_number(words):
    total, part = 0, 0
    for w in re.split(r'[\s-]+',words):
        if w in _SMALL:part += _SMALL[w]
        elif w in _TENS:part += _TENS[w]
        elif w == 'hundred':part = (part or 1)*100
        elif w in _SCALES:total += (part or 1)*_SCALES[w];part = 0
    return total+part


def normalize_question(question, vocabulary=()):
    """Normalize language, never source facts. Preserve explicitly named entities."""
    q=question.lower().replace('’',"'").replace('–','-').replace('—',' ')
    # Spoken model years have a different grammar from ordinary addition.
    year_words='|'.join(list(_SMALL)+list(_TENS))
    def spoken_year(m):
        return str(2020+_word_number(m[1]))
    q=re.sub(r'\btwenty[ -]+twenty[ -]+((?:'+year_words+r')(?:[ -]+(?:'+year_words+r'))?)\b',spoken_year,q)
    q=re.sub(r"(?<!\w)'(\d{2})(?=\s+(?:model|car|vehicle|auto|truck|motorcycle))",lambda m:str(2000+int(m[1])),q)
    frac={'half':.5,'a half':.5,'one half':.5,'three quarter':.75,'three quarters':.75,'quarter':.25,'a quarter':.25,'one quarter':.25}
    q=re.sub(r'\b(three[ -]+quarters?|(?:(?:a|one)[ -]+)?(?:half|quarter))\s*[- ]\s*(thousand|million|billion)\b',
             lambda m:format(frac[m[1].replace('-',' ')]*_SCALES[m[2]],'g'),q)
    q=re.sub(r'\b(\d+(?:\.\d+)?)\s*[- ]\s*(hundred|thousand|million|billion|grand)\b',lambda m:format(float(m[1])*_SCALES[m[2]],'g'),q)
    number_words='|'.join(list(_SMALL)+list(_TENS)+list(_SCALES))
    q=re.sub(r'\b(?:'+number_words+r')(?:[ -]+(?:and[ -]+)?(?:'+number_words+r'))*\b',lambda m:str(_word_number(m[0])),q)
    aliases={'cert':'certificate','certs':'certificates','reg':'regular','yr':'year','yrs':'years','mo':'month','mos':'months',
             'mth':'month','mths':'months','svc':'service','doc':'document','pls':'please','ur':'your','w':'with',
             'notarize':'notary','notarise':'notary','min':'minimum','max':'maximum'}
    # General abbreviations; content names and values come from the snapshot.
    q=re.sub(r'\b[a-z]+\b',lambda m:aliases.get(m[0],m[0]),q)
    # Repeated units in enumerations: 48-,60-,72-,and84-month -> explicit terms.
    def listed_units(m):
        nums=re.findall(r'\d+',m[1])
        return ', '.join(n+'-'+m[2] for n in nums)
    q=re.sub(r'((?:\d+\s*-?\s*,\s*)+(?:and\s*)?\d+)\s*-?\s*(months?|years?)\b',listed_units,q)
    vocab=set(vocabulary)
    ordinary=set('count counts counter total how many what which where when who latest older earlier current newer freshest precise complete set types approaches amount balance exactly figure figures requirements materials documents package choices uses application applications guarantee guarantees return returns year years month months timing period status page pages table tables snapshot snapshots history baseline changes changed compare comparison versus all every shortest longest standard personal business regular minimum maximum reported publication available offered showed shown delivered membership members source sources shared sharing network networks large'.split())
    if vocab:
        def correct(m):
            word=m[0]
            if word in vocab or word in ordinary or len(word)<4:return word
            candidates=[]
            sk=lambda s:re.sub('[aeiouy]','',s.replace('gh',''))
            for v in vocab:
                if abs(len(word)-len(v))>2:continue
                similarity=difflib.SequenceMatcher(None,word,v).ratio()
                if similarity>=.78 or similarity>=.7 and sk(word)==sk(v):candidates.append((similarity,v))
            candidates.sort(reverse=True)
            if candidates and (len(candidates)==1 or candidates[0][0]-candidates[1][0]>=.1):return candidates[0][1]
            return word
        q=re.sub(r'\b[a-z]+\b',correct,q)
    return re.sub(r'\s+',' ',q).strip()


def term_months(question):
    q = question.lower().replace('–', '-').replace('‑', '-')
    m = re.search(r'(\d+)\s*[- ]?\s*(month|mo\b|year|yr\b)', q)
    if m:
        return int(m[1]) * (12 if m[2] in ('year', 'yr') else 1)
    for word, n in [('six',6),('twelve',12),('seventeen',17),('ten',10),('thirty',30),('sixty',60),('eighty-four',84)]:
        m=re.search(r'\b'+word+r'\s*[- ]?\s*(month|year)',q)
        if m:
            return n * (12 if m[1]=='year' else 1)
    return None
