"""Extract source-local application packages and product feature lists."""
import re
from common import clean


def answer(ctx,q):
    if not re.search(r'\bbusiness\b|commercial',q) or not re.search(r'loan|financ',q):return None
    if re.search(r'\bapr\b|interest rate|as.low.as rate',q):return None
    if not re.search(r'application|apply|materials|documents?|package|submission|guarantee|requirements?|uses|financing',q):return None
    targets=[(r'equipment|vehicle','/business/loans/equipment-vehicle-loans'),
             (r'real[- ]estate','/business/loans/real-estate-loans'),
             (r'small[- ]business','/business/loans/small-business-loans'),
             (r'construction','/business/loans/construction-loans')]
    page=next((ctx.find(path) for pattern,path in targets if re.search(pattern,q) and ctx.find(path)),None)
    if page is None:return None
    md=page.markdown
    selected=[]
    detail=r'tax returns?|financial statement|purchase agreement|environmental questionnaire|construction or build.out costs|application|upload|submit|guarantees? (?:are|is|required)|\bmember\b'
    for raw in re.split(r'\n\s*\n',md):
        text=clean(raw)
        if re.search(detail,text,re.I) and not text.lstrip().startswith(('![','- [')):
            if text not in selected:selected.append(text)
            for label,url in re.findall(r'\[([^\]]+)\]\((https?://[^)]+)\)',raw):
                if re.search(r'application|upload|submit|download',label,re.I):
                    link=label+': '+url
                    if link not in selected:selected.append(link)
    if re.search(r'uses|highlight|all (?:four|4)|financing',q):
        headings=[clean(line.lstrip('# ')) for line in md.splitlines() if re.match(r'^####\s+',line)]
        selected=headings+selected
    if not selected:
        return ctx.reply("I don't know. This snapshot does not publish that application package.",[page],confident=False)
    return ctx.reply(' '.join(selected),[page])
