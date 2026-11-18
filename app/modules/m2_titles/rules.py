import re,unicodedata
from collections import defaultdict
from app.report import report,quarantine
from app.errors import BusinessError
from app.succession import titles_related
ALIASES={"环境监测技术":"环境监测技术","环境监测科技":"环境监测技术","数据工程月刊":"数据工程月刊","数据工程":"数据工程月刊"}
def canonical(title,issn):
    title=unicodedata.normalize("NFKC",title).replace(" ","").strip()
    if not re.fullmatch(r"[0-9]{4}-[0-9]{3}[0-9X]",issn):raise BusinessError("ISSN","ISSN格式无效")
    return ALIASES.get(title,title),issn

def _issue_set(text):
    from app.modules.m3_issues.rules import expand
    try:return set(expand(text))
    except BusinessError:return None

def apply(ctx):
    out=[];identity={};names_at=defaultdict(set)
    for r in ctx["raw"]:
        try:
            name,issn=canonical(r["title"],r["issn"])
            # 当期刊名按原样保留（仅做兼容归一），不被别名映射或后续版本改写。
            issue_title=unicodedata.normalize("NFKC",r["title"]).strip()
            x=dict(r);x["issue_title"]=issue_title;x["canonical"]=name;x["journal_key"]=issn;out.append(x)
            identity.setdefault(issn,[]).append(name)
            issues=_issue_set(r["issue"])
            key=(issn,tuple(sorted(issues)) if issues is not None else ("?",""))
            names_at[key].add(name)
        except BusinessError as e:quarantine(ctx,r,e.code)
    # 同一 ISSN 下互不相干的刊名只有在同一期次上并存才算身份冲突；
    # 若是年中改刊名、前后期次各自使用一个刊名，则允许共存并由年度链承接。
    conflicts=set()
    for (issn,_),names in names_at.items():
        unique=sorted(names)
        if len(unique)>1 and any(not titles_related(a,b) for i,a in enumerate(unique) for b in unique[i+1:]):conflicts.add(issn)
    ctx["canonical"]=out;ctx["identity_conflicts"]=sorted(conflicts)
    return report(out,期刊=len(identity),刊名冲突=len(conflicts))
