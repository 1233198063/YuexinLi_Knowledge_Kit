"""Temporal, source-grounded knowledge system for the supplied snapshots."""
import importlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from urllib.parse import urlsplit
from types import SimpleNamespace

from common import Context, clean, normalize_question
from evidence import explicit_effective_date,currently_valid


@dataclass
class Source:
    url: str
    snapshot_id: Optional[str] = None
    quote: Optional[str] = None


@dataclass
class Answer:
    text: str
    sources: list = field(default_factory=list)
    confident: bool = True
    conflict_note: Optional[str] = None


@dataclass
class Conflict:
    topic: str
    values: list
    sources: list
    resolution: Optional[str] = None
    reason: Optional[str] = None


try:
    # The official runner exposes these classes and uses isinstance in its
    # repeat check; use its exact types when available. Standalone usage keeps
    # the compatible local dataclasses above.
    from contract import Answer, Source, Conflict
except ImportError:
    pass


STOP = set('a an the what which who where when is are was were be been do does did can could would should tell me i my your our you it its to of on in for and or with at about now current currently please have has how much rate rates account dupaco'.split())
ALIASES = {'cd':'certificate','cds':'certificate','certificates':'certificate',
           'cars':'auto','car':'auto','vehicle':'auto','vehicles':'auto',
           'automobile':'auto','automobiles':'auto','mortgages':'mortgage',
           'branches':'branch','locations':'branch','fees':'fee','charges':'fee',
           'lending':'loan','loans':'loan','apys':'apy','dividends':'dividend',
           'cellphone':'mobile','app':'mobile','wallets':'wallet','hours':'hour',
           'joining':'join','membership':'member','students':'student',
           'lost':'replacement','replace':'replacement','replacement':'replacement'}


def tokens(s):
    return [ALIASES.get(w,w) for w in re.findall(r'[a-z]+|\d+(?:\.\d+)?',s.lower()) if w not in STOP]


def authority(page):
    path=urlsplit(page.url).path.lower()
    if path in ('','/contact','/about','/about/join') or path.startswith(('/personal/','/business/')):
        return 1.3
    if path in ('/rates','/business-rates','/earn-more','/switch-and-earn'):
        return 1.25
    if '/newsroom/' in path:
        return 0.8
    if '/learn/blog/' in path or re.match(r'/20\d\d/',path):
        return 0.55
    return 1.0


class SearchIndex:
    """Deterministic BM25 fallback over clean source passages, built during ingest."""
    def __init__(self,ctx):
        self.ctx=ctx
        self.chunks=[]
        self.df=Counter()
        seen=set()
        for p in ctx.pages:
            md=p.markdown
            # Marketing recommendation links and country-picker widgets are not facts.
            md=md.split('## Handpicked for You')[0]
            blocks=re.split(r'\n\s*\n',md)
            heading=clean(p.title)
            for b in blocks:
                if b.lstrip().startswith('#'):
                    heading=clean(b.lstrip('# ').strip())
                if b.count('🇺') or len(b)>18000 or re.match(r'^\s*!\[',b):
                    continue
                text=clean(b)
                if len(text)<30 or re.match(r'^\[',b) and len(text)<100:
                    continue
                if text in seen:
                    continue
                seen.add(text)
                ts=tokens(text)
                title=set(tokens(heading+' '+p.title+' '+urlsplit(p.url).path.replace('-',' ')))
                counts=Counter(ts)
                self.df.update(counts.keys())
                self.chunks.append((p,text,counts,len(ts),title))
        self.n=len(self.chunks)
        self.avg=sum(c[3] for c in self.chunks)/max(1,self.n)

    def answer(self,q):
        terms=set(tokens(q))
        if not terms:
            return self.ctx.reply("I don't know. Please contact Dupaco for help.",confident=False)
        ranked=[]
        for p,text,counts,length,title in self.chunks:
            hits=terms & counts.keys()
            if not hits:
                continue
            score=0.0
            for t in hits:
                idf=math.log(1+(self.n-self.df[t]+.5)/(self.df[t]+.5))
                tf=counts[t]
                score+=idf*tf*2.2/(tf+1.2*(.25+.75*length/max(1,self.avg)))
            score*=authority(p)
            score*=1+0.16*len(terms & title)
            # Extra weight for retaining a requested named entity or amount.
            score*=.55+.45*len(hits)/len(terms)
            if len(hits)<min(2,len(terms)):
                continue
            ranked.append((score,p,text,hits))
        ranked.sort(key=lambda x:-x[0])
        if not ranked:
            return self.ctx.reply("I don't know. The selected website snapshot does not provide that information. Please contact Dupaco.",confident=False)
        _,p,text,hits=ranked[0]
        numeric_request=bool(re.search(r'\blimits?\b|\b(?:maximum|minimum)\b|\bhow much\b|\b(?:cost|price|premium)\b',q.lower()))
        if numeric_request and not re.search(r'\bwhy\b|\bwhat affects\b|\bhow (?:do|does|can)\b',q.lower()):
            # A named service's limit cannot be answered by a different
            # product's limit merely because both mention transfers. Require
            # the specific question terms and a published quantified claim.
            explicit_amount=bool(re.search(r'\$\s*\d|\d+(?:\.\d+)?\s*%|\b\d+\b',text))
            explicit_unbounded=bool(re.search(r'\bunlimited\b|\bno (?:minimum|maximum|monthly fee|service fee)\b|\bfree\b',text.lower()))
            if len(hits)/len(terms)<.8 or not (explicit_amount or explicit_unbounded):
                return self.ctx.reply("I don't know. The selected snapshot does not publish a matching amount or limit for that service. Please contact Dupaco.",confident=False)
        # A rate request without a structured product match must not pick numbers
        # from a vaguely related loan, promotion, or educational article.
        if re.search(r'\b(apr|apy|interest rate|dividend rate|rate on|rate for)\b',q.lower()):
            if len(hits)/len(terms)<.7:
                return self.ctx.reply("I don't know. A matching rate is not listed in this snapshot; please contact Dupaco.",[p],confident=False)
        if text.startswith('|'):
            lines=[clean(s) for s in text.split('|') if clean(s)]
            # Unstructured tables can contain unrelated tiers. Let the product
            # modules decide them rather than expose a whole table blindly.
            return self.ctx.reply("I don't know. Please contact Dupaco to confirm the applicable option.",[p],confident=False)
        sentences=re.split(r'(?<=[.!?])\s+(?=[A-Z])',text)
        if len(text)>1300:
            sentences=sorted(enumerate(sentences),key=lambda x:(-len(set(tokens(x[1]))&terms),x[0]))[:3]
            text=' '.join(s for _,s in sorted(sentences))[:1600]
        return self.ctx.reply(text,[p],quote=text[:400])


MONTHS={m:i for i,m in enumerate(['january','february','march','april','may','june','july','august','september','october','november','december'],1)}


def normalize_calendar_words(question):
    """Normalize calendar grammar without altering amounts or model years."""
    q=question.lower()
    aliases={name[:3]:name for name in MONTHS}
    aliases['sept']='september'
    # Slash calendar dates are not deposit amounts or model-year bands.
    q=re.sub(r'\b(\d{1,2})/(\d{1,2})/(20\d{2})\b',
             lambda m:f'{int(m[3]):04d}-{int(m[1]):02d}-{int(m[2]):02d}',q)
    pattern=r'\b('+ '|'.join(aliases)+r')\.?(?=\s+\d{1,4}(?:st|nd|rd|th)?\b)'
    q=re.sub(pattern,lambda m:aliases[m[1]],q)
    names='|'.join(MONTHS)
    def approximate(m):
        import calendar
        month,year=m[2],m[3]
        day=15 if m[1]=='mid' else 1 if m[1]=='early' else calendar.monthrange(int(year),MONTHS[month])[1] if year else 28
        return month+' '+str(day)+(', '+year if year else '')
    q=re.sub(r'\b(mid|early|late)[- ]('+names+r')(?:\s+(20\d{2}))?\b',approximate,q)
    q=re.sub(r'\b('+names+r')\s+(\d{1,2})(?:st|nd|rd|th)\b',r'\1 \2',q)
    q=re.sub(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+('+names+r')(?:[,]?\s+(20\d{2}))?\b',
             lambda m:m[2]+' '+m[1]+(', '+m[3] if m[3] else ''),q)
    return q


def query_dates(q,default_year):
    q=normalize_calendar_words(q)
    dates=[]
    for iso in re.findall(r'\b20\d\d-\d\d-\d\d\b',q):
        try:dates.append(date.fromisoformat(iso).isoformat())
        except ValueError:pass
    for m in re.finditer(r'\b('+ '|'.join(MONTHS)+r')\b(?:\s+(\d{1,2})(?!\d))?(?:[\s,]+(20\d{2}))?',q.lower()):
        month,day,year=MONTHS[m[1]],m[2],m[3]
        year=int(year or default_year)
        import calendar
        when=int(day) if day else 15 if re.search(r'mid[- ]?$',q[max(0,m.start()-5):m.start()].lower()) else calendar.monthrange(year,month)[1]
        try:dates.append(date(year,month,when).isoformat())
        except ValueError:pass
    return list(dict.fromkeys(dates))


def date_in_question(q, default_year=None):
    q=normalize_calendar_words(q)
    # A date attached to a news event is not automatically an instruction to
    # reconstruct the website at that date. Historical event facts can be
    # described in a later snapshot. Explicit as-of requests always take
    # precedence; ordinary dated rate/fee/hour questions can infer as-of.
    explicit=bool(re.search(r'\b(?:as of|as at|back in)\b',q))
    time_value=bool(re.search(r'\b(?:apy|apr|rate|interest|dividend|yield|fee|hours?|snapshots?|crawl)\b',q))
    if not explicit and not time_value:
        return None
    year=default_year or date.today().year
    named=r'(?:'+ '|'.join(MONTHS)+r')(?:\s+\d{1,2}(?!\d))?(?:[\s,]+20\d{2})?'
    literal=r'(?:20\d{2}-\d{2}-\d{2}|'+named+r')'
    # The explicit target is stronger than dates mentioned as stale examples.
    target=re.search(r'\b(?:as of|as at|back in)\s+('+literal+r')\b',q)
    if target:
        found=query_dates(target[1],year)
        return found[0] if found else '__invalid_question_date__'
    if re.search(r'\bas (?:of|at) (?:the )?(?:latest|current|most recent) (?:available )?snapshot\b',q):return None
    found=query_dates(q,year)
    if len(found)>=2 and re.search(r'\bchange(?:s|d)?\b|\bbetween\b|\bover time\b|\bacross\b|\bboth\b|\beach\b',q):return max(found)
    target=re.search(r'\b(?:on|in|during|for)\s+('+literal+r')\b',q)
    if target:
        chosen=query_dates(target[1],year)
        return chosen[0] if chosen else None
    if re.search(r'\b(?:latest|current|today|most recent|freshest|right now)\b',q):return None
    if re.search(r'\bsnapshots?\b|\bcrawl\b',q):return found[-1] if found else None
    return None


def without_query_dates(q):
    # An as-of day/year is not a deposit balance, vehicle model year, or term.
    q=normalize_calendar_words(q)
    named=r'(?:'+ '|'.join(MONTHS)+r')(?:\s+\d{1,2}(?!\d),?)?(?:\s+20\d{2})?'
    q=re.sub(r'\b20\d{2}-\d{2}-\d{2}\b',' ',q)
    return re.sub(r'\b'+named+r'\b',' ',q,flags=re.I)


def independent_requests(question):
    """Split independent question clauses, not metric lists or comparisons."""
    head=r'(?:as (?:of|at)\b|what\b|which\b|how\b|quote\b|give\b|list\b|tell\b|show\b|when\b|where\b)'
    boundary=r';\s*(?=(?:(?:and|separately)\s+)?'+head+r')|,?\s+and\s+(?='+head+r')'
    parts=re.split(boundary,question,flags=re.I)
    if len(parts)<2:
        scoped=re.split(r'\s+and\s+(?=(?:the\s+)?(?:top|highest|maximum|best)\b)',question,flags=re.I)
        if len(scoped)==2 and all(re.search(r'savings|checking|money market|certificate|\bira\b',p,re.I) for p in scoped):
            # The superlative clause repeats its product. Its local possessive
            # refers to that product, not a missing object in the first clause.
            parts=[scoped[0],'What is '+re.sub(r'\bits\b','the',scoped[1],flags=re.I)]
    if len(parts)<2 and len(re.findall(r'\bmortgage\b',question,re.I))>=2:
        # Noun-form mortgage requests can carry independent amounts and terms
        # without repeating "what". Split only when every clause supplies its
        # own complete purpose, duration and amount; never build a cross product.
        clauses=re.split(r'\s+(?:and|versus|vs\.?)\s+(?=(?:a\s+|an\s+)?(?:\$\s*\d|\d+\s*[- ]?\s*(?:year|month)))',question,flags=re.I)
        complete=lambda part: (re.search(r'\bmortgage\b',part,re.I) and
                              re.search(r'\bpurchase\b|\brefinanc',part,re.I) and
                              re.search(r'\d+\s*[- ]?\s*(?:year|month)',part,re.I) and
                              re.search(r'\$\s*\d',part))
        if len(clauses)>=2 and all(complete(p) for p in clauses):
            metrics=[]
            for pattern,label in [(r'\baprs?\b','APR'),(r'\binterest rate\b|\brate\b','interest rate'),
                                  (r'\bpayments?\b','payment'),(r'\bpoints\b','points')]:
                if re.search(pattern,clauses[0],re.I):metrics.append(label)
            if not metrics:return []
            parts=[clauses[0]]+['Quote '+ ' and '.join(metrics)+' for '+part for part in clauses[1:]]
    if len(parts)<2 or len(parts)>8:return []
    cleaned=[re.sub(r'^\s*(?:and|separately)\s+','',p,flags=re.I).strip() for p in parts]
    if any(re.search(r'\b(?:should you tell|what should|them|the team|card.services team|their|its)\b',p,re.I) for p in cleaned[1:]):return []
    # Do not invent omitted material context. Each part must name a product,
    # entity or service, rather than only request "its other rate".
    topic=r'savings|certificate|\bcd\b|\bira\b|checking|loan|mortgage|visa|card|branch|wallet|wire|fee|routing|grant|scholarship|assets|membership'
    return cleaned if all(re.search(topic,p,re.I) for p in cleaned) else []


class TemporalKnowledge:
    def __init__(self):
        self.contexts=[]
        self.modules=[]
        for name in ['features','deposits','loans','services','facts','product_details']:
            self.modules.append(importlib.import_module(name))
        self._answers={}
        self._conflicts=None

    def _prepare_context(self,ctx):
        for m in self.modules:
            prepare=getattr(m,'prepare',None)
            if prepare:
                prepare(ctx)
        ctx.cache['search']=SearchIndex(ctx)
        ctx.cache['simple_facts']=[]
        ctx.cache['unavailable_simple_facts']=[]
        for p in ctx.pages:
            effective=explicit_effective_date(clean(p.markdown))
            for line in p.markdown.splitlines():
                m=re.fullmatch(r'\s*([^:]{4,100}\b(?:APY|APR|rate|fee))\s*:\s*(\$?\s*\d+(?:\.\d+)?\s*%?)\s*',line,re.I)
                if m:
                    lane='simple_facts' if currently_valid(effective,ctx.date,p.markdown) else 'unavailable_simple_facts'
                    ctx.cache[lane].append((p,m[1],m[2],set(tokens(m[1])),effective))
        vocabulary={'checking','savings','certificate','dividend','interest','rate','regular','notary','withdrawal','transfer','month','year','statement'}
        for key in ('deposits','loans'):
            data=ctx.cache.get(key,[])
            rows=data.get('items',[]) if isinstance(data,dict) else data
            for row in rows:
                vocabulary.update(re.findall(r'[a-z]+',str(row.get('name','')).lower()))
        # Brand/entity words must not be corrected to another institution.
        brands={urlsplit(p.url).netloc.lower().removeprefix('www.').split('.')[0] for p in ctx.pages}
        ctx.cache['query_vocabulary']=vocabulary-brands
        return ctx

    def ingest(self,snapshot):
        ctx=self._prepare_context(Context(snapshot))
        self.contexts=[c for c in self.contexts if c.sid!=ctx.sid]
        self.contexts.append(ctx)
        self.contexts.sort(key=lambda c:(c.date,c.sid))
        self._answers.clear()
        self._conflicts=None

    def _at(self,as_of):
        if as_of is not None:
            try:as_of=date.fromisoformat(str(as_of)).isoformat()
            except (TypeError,ValueError):return None
        candidates=[c for c in self.contexts if as_of is None or c.date[:10]<=as_of]
        return candidates[-1] if candidates else None

    def _answer_ctx(self,ctx,q):
        if re.search(r'\brates?\s+(?:table|sheet|page)\b|\brates snapshot\b|\brate snapshot\b|\brates table\b',q.lower()):
            scope='/business-rates' if 'business' in q.lower() else '/rates'
            key='source_scope:'+scope
            if key not in ctx.cache:
                page=ctx.find(scope)
                child=Context(SimpleNamespace(snapshot_id=ctx.sid,taken_on=ctx.date,pages=[page] if page else []))
                # Scope is the selected source, not its routing alias. A
                # relocated rate table must retain its actual URL through
                # the product parser's source-local filtering step.
                child.question_page_scope=page.url if page else scope
                ctx.cache[key]=self._prepare_context(child)
            ctx=ctx.cache[key]
        # Product dates can otherwise be mistaken for balances/model years.
        # Event dates remain useful selectors for dated news (e.g. Forbes).
        if re.search(r'\b(?:apy|apr|rate|interest|dividend|yield|fee|balance|loan|mortgage|hours?|as of|as at|back in)\b',q.lower()):
            q=without_query_dates(q)
        q=normalize_question(q,ctx.cache.get('query_vocabulary',()))
        if re.search(r'\bapplications?\b|\bwindow\b',q) and re.search(r'\bopen\b|\bclosed\b|\bstatus\b',q):
            asked=set(tokens(q))
            for page in ctx.pages:
                identity=set(tokens(page.title))-{'application','applications','period','window','status'}
                body=clean(page.markdown)
                withheld=re.search(r'(?:not (?:yet )?(?:been )?announced|have not announced).{0,100}(?:whether.{0,50}open|(?:application|window).{0,40}open)|whether.{0,60}open.{0,60}(?:not (?:yet )?(?:been )?announced)',body,re.I)
                if identity and identity<=asked and withheld:
                    return ctx.reply("I don't know whether the current application window is open: this source explicitly says that status has not been announced.",[page],confident=False,quote=withheld[0])
        # Simple explicitly labelled facts also occur in small contract
        # fixtures. They require no vendor-specific URL or table structure.
        qt=set(tokens(q))
        def same_fact(lt):
            metric_words={'apy','apr','dividend','interest','fee','rate'}
            identity=lt-metric_words
            requested=qt & metric_words
            measured=lt & metric_words
            return (bool(identity) and identity<=qt and
                    (not requested or bool(requested & measured)) and
                    not (set(re.findall(r'\d+',q))-set(re.findall(r'\d+',' '.join(lt)))))
        matched=[row for row in ctx.cache.get('simple_facts',[]) if same_fact(row[3])]
        if matched:
            # Capture/row order is not factual authority. Compare the explicit
            # effective date among matching applicable facts, then source class;
            # equally ranked conflicting values remain unresolved.
            rank=lambda row:(row[4],authority(row[0]))
            top=max(map(rank,matched));best=[row for row in matched if rank(row)==top]
            values={(tuple(float(x) for x in re.findall(r'\d+(?:\.\d+)?',row[2])),
                     '$' if '$' in row[2] else '%' if '%' in row[2] else '') for row in best}
            if len(values)>1:
                pages={row[0].url:row[0] for row in best}
                return ctx.reply("I don't know which current value is correct: equally authoritative applicable sources disagree.",
                                 [pages[url] for url in sorted(pages)],confident=False,
                                 note='Unresolved same-identity simple facts at equal explicit effective date and source authority.')
            p,label,value,lt,effective=min(best,key=lambda row:row[0].url)
            return ctx.reply(label+': '+value+'.',[p],quote=label+': '+value)
        for p,label,value,lt,effective in ctx.cache.get('unavailable_simple_facts',[]):
            if same_fact(lt):
                return ctx.reply("I don't know a current value from this source: its explicit validity date is outside the selected snapshot.",[p],confident=False)
        modules={m.__name__:m for m in self.modules}
        rate_intent=bool(re.search(r'\b(?:apys?|aprs?|rates?|dividend rate|interest rate)\b',q))
        condition=bool(re.search(r'e[- ]?statement|eligib|qualif|requirement|new money|maturity funds',q))
        order=[]
        if re.search(r'business|commercial',q) and re.search(r'loan|financ',q) and not rate_intent:order.append('product_details')
        if re.search(r'calculator|scholarship|\bgrant\b|bright track|\bassets\b|net worth|\breserves\b|counties|county|\bboard\b|leadership|\bmission\b|\bfounded\b|\borganized\b|member(?:ship)?.*(?:count|total)',q):order.append('facts')
        if not rate_intent or re.search(r'\bfee\b|\bcharge\b|branch|lobby|wallet|routing|membership',q):order.append('services')
        if condition and not rate_intent:order.append('features')
        order+=['deposits','loans','features','facts','services','product_details']
        for name in dict.fromkeys(order):
            module=modules[name]
            ans=module.answer(ctx,q)
            if ans is not None:
                return ans
        return ctx.cache['search'].answer(q)

    def _history_answer(self,q,ctx):
        selected=[c for c in self.contexts if c.date<=ctx.date]
        # Limit a requested date range, retaining the last observation at the
        # start of that range so an unchanged first value is represented.
        dates=query_dates(q,ctx.date[:4])
        if len(dates)>=2 and re.search(r'\bsnapshots\b|\beach\b|\bevery\b',q.lower()) and len(dates)>2:
            selected=list(dict.fromkeys(self._at(d).sid for d in dates if self._at(d)))
            selected=[c for c in self.contexts if c.sid in selected and c.date<=ctx.date]
        elif len(dates)>=2:
            lo,hi=sorted(dates)[0],sorted(dates)[-1]
            if re.search(r'\bbaseline\b',q.lower()):lo=self.contexts[0].date
            import calendar
            if hi.endswith('-01'):
                yr,mo=map(int,hi[:7].split('-'))
                hi=f'{yr:04d}-{mo:02d}-{calendar.monthrange(yr,mo)[1]:02d}'
            before=[c for c in selected if c.date<=lo]
            selected=([before[-1]] if before else [])+[c for c in selected if lo<c.date<=hi]
        points=[]
        last_core=None
        for c in selected:
            raw=self._answer_ctx(c,q)
            if not raw.get('confident',True):
                continue
            numeric_pairs=re.findall(r'\$\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*%',raw['text'])
            core=tuple(float(value.replace(',','')) for pair in numeric_pairs for value in pair if value) or raw['text']
            if re.search(r'\ball (?:five |the )?snapshots\b|\beach time\b',q.lower()):last_core=None
            if core!=last_core:
                points.append((c,raw))
                last_core=core
        if not points:
            return self._answer_ctx(ctx,q)
        sources=[]
        for _,raw in points:
            sources.extend(s for s in raw.get('sources',[]) if s not in sources)
        text=' '.join(f'As of {date.fromisoformat(c.date).strftime("%B")} {int(c.date[8:10])}, {c.date[:4]} ({c.date}): {raw["text"]}' for c,raw in points)
        if len(points)==1:
            text+=' No change to this published answer was observed in the selected snapshots.'
        return {'text':text,'sources':sources,'confident':True,
                'conflict_note':'History compares the same requested product and qualifiers across dated full snapshots.'}

    def answer(self,question,as_of=None):
        q=str(question).strip()
        if as_of is not None:
            try:as_of=date.fromisoformat(str(as_of)).isoformat()
            except (TypeError,ValueError):
                return Answer("I don't know which snapshot to use: the requested as_of must be a valid ISO calendar date.",confident=False)
        private_completion=(re.search(r'\bmy\b',q,re.I) and re.search(r'identity|ownership|correction|profile|information change',q,re.I) and
                            re.search(r'\b(?:has|have|is|was|did|are)\s+my\b|\bconfirm\b.{0,35}\bmy\b',q,re.I) and
                            re.search(r'verified|completed|confirmed|done',q,re.I))
        if private_completion:
            return Answer("I cannot confirm your account's identity verification or whether a requested change has been completed from public website snapshots. Please use authenticated account support.",confident=False)
        parts=independent_requests(q)
        if parts:
            replies=[]
            for part in parts:
                explicit=date_in_question(part,self.contexts[-1].date[:4] if self.contexts else None)
                # The API date is authoritative for the entire call. Clause
                # dates select independent history only when the caller has
                # not supplied as_of; they cannot bypass its cutoff.
                replies.append(self.answer(part,as_of if as_of is not None else explicit))
            sources=[]
            for a in replies:
                for source in a.sources:
                    if source not in sources:sources.append(source)
            notes=list(dict.fromkeys(a.conflict_note for a in replies if a.conflict_note))
            return Answer(' '.join(f'Part {i+1}: {a.text}' for i,a in enumerate(replies)),sources,
                          all(a.confident for a in replies),' '.join(notes) or None)
        # Scope another named financial institution before spelling correction.
        brands={urlsplit(p.url).netloc.lower().removeprefix('www.').split('.')[0] for c in self.contexts[-1:] for p in c.pages}
        other=re.findall(r'\b([a-z][a-z-]+)\s+(?:community\s+)?(?:credit union|cu)\b',q.lower())
        correction=re.search(r'\b(?:i mean|for|of)\s+([a-z]+)[, ]+not\s+([a-z]+)',q.lower())
        if correction and correction[2] in brands:other.append(correction[1])
        generic={'other','another','any','the','a','your','our','this','their','its','participating','shared','community'}
        if re.search(r'routing|\baba\b|\bswift\b|\bbic\b',q.lower()) and any(n not in brands and n not in generic for n in other):
            return Answer("I don't know that institution's routing information from the supplied website snapshots. Please contact that institution.",confident=False)
        q=normalize_question(q)
        personal_approval=bool(re.search(r'\b(?:apr|rate|interest)\b',q.lower()) and
                               (re.search(r'\bpersonally\b|my (?:exact|approved)|individual(?:ly)? approved',q.lower()) or
                                re.search(r'\b(?:credit score|credit rating)\b',q.lower()) and
                                re.search(r'\b(?:i|my|me)\b',q.lower()) and
                                re.search(r'\b(?:approved|qualify|would|will)\b',q.lower())))
        if personal_approval:
            return Answer("I don't know your individually approved rate from public website snapshots. Please contact Dupaco for a personalized underwriting decision.",confident=False)
        personal_balance=bool(re.search(r'\b(?:what(?: is|\x27s)|check|tell me|show me|look up).{0,70}\bmy\b.{0,50}\b(?:balance|account number|member number|transactions?|payment status)\b',q.lower()))
        personal_balance=personal_balance or bool(re.search(r'\b(?:balance|account number|member number)\b.{0,35}\b(?:of|for) my\b',q.lower()))
        if personal_balance and not re.search(r'\b(?:apy|apr|rate|interest|dividend|earn)\b',q.lower()):
            return Answer("I don't know your private account information from these public website snapshots. Please use authenticated online or mobile banking, or contact Dupaco.",confident=False)
        as_of=as_of or date_in_question(q,self.contexts[-1].date[:4] if self.contexts else None)
        if as_of=='__invalid_question_date__':
            return Answer("I don't know which snapshot to use: the question contains an invalid calendar date.",confident=False)
        ctx=self._at(as_of)
        if ctx is None:
            return Answer("I don't know. No website snapshot is available for that date.",confident=False)
        key=(ctx.sid,q.lower())
        if key not in self._answers:
            history=bool(re.search(r'\b(changed|changes over|change over|increased|decreased|used to|previously|between snapshots|over time)\b',q.lower()))
            history=history or bool(re.search(r'\b(?:did|has|have)\b.{0,140}\bchange\b',q.lower()))
            dates=query_dates(q,ctx.date[:4])
            history=history or bool(len(dates)>=2 and re.search(r'\bcompar(?:e|ison)\b|\bdiffer\b|\bbetween\b|\bacross\b',q.lower()))
            history=history or bool(len(dates)>=2 and re.search(r'\bboth\b|\beach\b|\bsnapshots?\b|\bcrawls?\b',q.lower()) and
                                   re.search(r'\bgive\b|\blist\b|\bstate\b|\bshow\b|\bquote\b',q.lower()))
            history=history or bool(re.search(r'^\s*(?:please\s+)?track\b|\bacross (?:all |the )?(?:five |all )?snapshots\b',q.lower()))
            raw=self._history_answer(q,ctx) if history else self._answer_ctx(ctx,q)
            self._answers[key]=Answer(raw['text'],[Source(**s) for s in raw.get('sources',[])],
                                      raw.get('confident',True),raw.get('conflict_note'))
        a=self._answers[key]
        return Answer(a.text,list(a.sources),a.confident,a.conflict_note)

    def conflicts(self):
        if self._conflicts is None:
            engine=importlib.import_module('conflict_engine')
            self._conflicts=[]
            for c in engine.collect(self.contexts):
                sources=[]
                for s in c.get('sources',[]):
                    ctx=next((x for x in self.contexts if x.sid==s.get('snapshot_id')),None)
                    page=next((p for p in ctx.pages if p.url==s.get('url')),None) if ctx else None
                    if page:
                        checked=ctx.reply('',page,quote=s.get('quote'))['sources']
                        sources.extend(Source(**item) for item in checked)
                self._conflicts.append(Conflict(c['topic'],c['values'],sources,c.get('resolution'),c.get('reason')))
        return list(self._conflicts)


def build():
    return TemporalKnowledge()
