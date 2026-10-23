"""Product conditions from source paragraphs, kept separate from rate tables."""
import re
from common import clean


def paragraphs(page):
    return [clean(p) for p in re.split(r'\n\s*\n',page.markdown.split('## Handpicked for You')[0])
            if p.strip() and not p.lstrip().startswith(('![','|'))]


def _passages(ctx,paths,patterns):
    for path in paths:
        page=ctx.find(path)
        if page:
            found=[]
            for pattern in patterns:
                for p in paragraphs(page):
                    if re.search(pattern,p,re.I) and p not in found:
                        found.append(p)
                        break
            if found:
                return page,found
    return None,[]


def answer(ctx,question):
    q=question.lower()
    if 'bright' in q and re.search(r'estatements|e-statements|require|eligible|eligibility|qualif|can .*open|who .*open|limit|maximum balance|monthly .*fee|how .*open|how .*dividend|receive dividends|must .*meet',q):
        if re.search(r'estatements|e-statements|dividend|require|must .*meet',q):
            patterns=[r'not enrolled in eStatements by the end of the month']
        elif re.search(r'eligible|eligibility|business|minor|fiduciary|estate|trust|consumer|limit|maximum',q):
            patterns=[r'available exclusively to consumer members']
        elif re.search(r'fee|minimum',q):
            patterns=[r'no monthly service fees']
        else:
            patterns=[r'quick and easy .*open online',r'available exclusively to consumer members']
        page,text=_passages(ctx,['/savings-account/online-savings-account','/personal/savings-account','/rates'],patterns)
        if text:
            return ctx.reply(' '.join(text),[page],quote='\n'.join(text))
        return ctx.reply("I don't know. The selected snapshot does not publish those Bright Savings conditions.",confident=False)
    if 'achieve' in q and re.search(r'qualif|new money|matur|eligible|eligibility|how .*open|require|how long|outside|past .*days',q):
        page,text=_passages(ctx,['/earn-more','/membermoneymarket-lp','/newmembermoneymarket-lp'],
                            [r'New Money is defined as|Eligible Term.Share Certificate Maturity Funds are defined as'])
        if text:
            # The same footer also lists rate tiers. Return the requested
            # condition sentences, excluding unrelated rate numbers.
            passage=text[0]
            sentences=re.split(r'(?<=[.!?])\s+(?=[A-Z])',passage)
            wanted=[s for s in sentences if re.search(r'New Money|Maturity Funds|matured|minimum balance to earn',s,re.I)]
            return ctx.reply(' '.join(wanted) or passage,[page],quote=' '.join(wanted) or passage)
        return ctx.reply("I don't know. The selected snapshot does not state those qualifying-fund conditions.",confident=False)
    if 'launchpad' in q and re.search(r'penalt|withdraw|tax|retirement|deposit|closed|closure|90.day|1000|1,000|limit',q) and not re.search(r'apy|dividend rate|interest rate',q):
        page,text=_passages(ctx,['/rates','/personal/savings-account'],[r'Launchpad Savings Rate:'])
        if text:
            return ctx.reply(' '.join(text),[page],quote='\n'.join(text))
    if re.search(r'\bhsa\b|health savings',q) and re.search(r'waiv|monthly .*fee|roll.?over|qualified|tax|debit|coverage',q):
        page,text=_passages(ctx,['/personal/savings-account'],[r'To waive the .*monthly service fee' if re.search(r'waiv|fee',q) else r'Open with .*tax.deductible|balance rolls over every year'])
        if text:
            return ctx.reply(' '.join(text),[page],quote='\n'.join(text))
    return None
