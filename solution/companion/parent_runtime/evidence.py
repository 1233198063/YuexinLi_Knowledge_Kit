"""Shared fact identities and exact raw spans; no evaluation or filesystem data."""
import re
from dataclasses import dataclass
from typing import Optional


def normalize_label(value):
    s=str(value or '').lower().replace('’',"'").replace('–','-').replace('—','-')
    s=re.sub(r'(?<=\d),(?=\d)','',s)
    s=re.sub(r'(?<=\d)\.00\b','',s)
    return re.sub(r'\s+',' ',re.sub(r'\s*-\s*','-',s)).strip()


def canonical_identity(category,scope,product,qualifier,metric,phase=''):
    def normalized(value):
        if isinstance(value,(tuple,list)):return tuple(normalized(v) for v in value)
        return normalize_label(value) if isinstance(value,str) else value
    measure=metric.lower()
    if measure=='rate' and category in ('deposit','certificate','ira'):measure='dividend'
    return (category,scope,normalize_label(product),normalized(qualifier),measure,normalize_label(phase))


@dataclass(frozen=True)
class RawSpan:
    start:int
    end:int
    text:str


@dataclass(frozen=True)
class Evidence:
    identity:tuple
    metric:str
    value:str
    display_text:str
    url:str
    snapshot_id:Optional[str]
    spans:tuple
    effective_from:Optional[str]=None
    effective_until:Optional[str]=None
    observed_on:Optional[str]=None
    authority:int=0


def raw_spans(markdown,candidate,normalize):
    """Locate exact source spans; transformed or unsupported assertions vanish."""
    if not candidate:return ()
    position=markdown.find(candidate)
    if position>=0:return (RawSpan(position,position+len(candidate),candidate),)
    spans=[]
    for part in candidate.splitlines():
        if not part.strip():continue
        position=markdown.find(part)
        if position>=0:
            span=RawSpan(position,position+len(part),part)
        else:
            target=normalize(part)
            if not target:continue
            span=None;offset=0
            for line in markdown.splitlines(keepends=True):
                if target in normalize(line):
                    text=line.rstrip('\r\n')
                    span=RawSpan(offset,offset+len(text),text)
                    break
                offset+=len(line)
            if span is None:continue
        if span not in spans:spans.append(span)
    return tuple(spans)


def make_evidence(page,snapshot_id,identity,metric,value,quote,normalize,effective=None,observed=None,authority=0):
    return Evidence(identity,metric,str(value),str(value),page.url,snapshot_id,
                    raw_spans(page.markdown,quote,normalize),effective,None,observed,authority)


def deposit_identity(row,metric):
    name=normalize_label(row['name'])
    scope='business' if row.get('business') or 'business' in name else 'personal'
    family=row.get('family','deposit')
    if family in ('certificate','ira'):
        kind='jumbo special' if 'jumbo' in name else 'special' if 'special' in name else 'regular'
        product='certificate '+kind
        if family=='ira':
            typ='roth' if 'roth' in name else 'traditional' if 'traditional' in name else ''
            product=(typ+' IRA '+kind).strip()
        qualifier=(row.get('term'),row.get('minimum') or '')
    else:
        product=re.sub(r'\s*\(business\)|\bbusiness\s+','',name).strip()
        qualifier=(row.get('tier',''),)
    return canonical_identity(family,scope,product,qualifier,metric,row.get('phase') or row.get('period') or '')


def iso_day(value):
    from datetime import datetime
    for fmt in ('%Y-%m-%d','%m/%d/%Y','%m/%d/%y'):
        try:return datetime.strptime(value or '',fmt).date().isoformat()
        except ValueError:pass
    return value or ''


def explicit_effective_date(text):
    """Read an explicitly labelled source date, independent of display format."""
    from datetime import datetime
    numeric=r'\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}'
    named=r'[A-Za-z]+\.?\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4}'
    m=re.search(r'\b(?:effective(?:\s+as\s+of)?|as of[,]?)\s+('+numeric+'|'+named+r')\b',text,re.I)
    if not m:return ''
    raw=re.sub(r'(?<=\d)(?:st|nd|rd|th)\b','',m[1],flags=re.I).replace('.','')
    raw=raw.replace('Sept ','Sep ')
    for fmt in ('%Y-%m-%d','%m/%d/%Y','%m/%d/%y','%B %d, %Y','%b %d, %Y','%B %d %Y','%b %d %Y'):
        try:return datetime.strptime(raw,fmt).date().isoformat()
        except ValueError:pass
    return ''


def currently_valid(effective,observed,quote=''):
    day=iso_day(effective)
    if day and observed and day>observed[:10]:return False
    ended=re.search(r'\b(?:offer|promotion) (?:ended|expired)\s*[: ]\s*(20\d\d-\d{2}-\d{2})',quote,re.I)
    return not(ended and observed and ended[1]<observed[:10])
