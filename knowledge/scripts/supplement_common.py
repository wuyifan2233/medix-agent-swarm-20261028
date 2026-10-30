"""Target known coverage gaps through a public Chinese medical-platform search."""
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from knowledge.scripts.expand_corpus import CACHE,DISEASES,DRUGS,get,harvest


def matching_links(html,group,term):
    soup=BeautifulSoup(html,'html.parser');matches=[]
    for a in soup.select('a[href]'):
        href=a.get('href','');m=re.fullmatch('/'+group+r'/(\d+)\.html',href)
        title=a.get_text(strip=True)
        if m and term in title:matches.append((title,href,m[1]))
    return sorted(matches,key=lambda x:(x[0]!=term,len(x[0])))


def main():
    candidates=json.loads((CACHE/'candidates.json').read_text(encoding='utf8'))
    previous=json.loads((CACHE/'supplement.json').read_text(encoding='utf8')) if (CACHE/'supplement.json').exists() else {}
    supplements=previous.get('documents',[]);missing=[]
    for group,terms in [('disease',DISEASES),('drug',DRUGS)]:
        for term in terms:
            if any(term in doc['title'] for doc in supplements):continue
            # Include first exact/containing matches even if in the base candidate pool,
            # so stopping at 3000 does not omit the known common inventory.
            matches=matching_links(get('https://www.dayi.org.cn/search',params={'keyword':term}).text,group,term)
            if not matches:missing.append({'kind':group,'term':term});continue
            title,href,identifier=matches[0]
            source={'id':'dayi_'+group+'_'+identifier,'title':title,'url':urljoin('https://www.dayi.org.cn',href),'publisher':'中国医药信息查询平台','published_at':None,'kind':group}
            result=harvest(source)
            if 'error' not in result:supplements.append(result)
            else:missing.append({'kind':group,'term':term,'error':result['error']})
            (CACHE/'supplement.json').write_bytes(json.dumps({'documents':supplements,'missing':missing},ensure_ascii=False).encode('utf8'))
            if len(supplements)%20==0:print('common source supplements',len(supplements),'gaps',len(missing),flush=True)
    print('Supplement finished',len(supplements),'unresolved',len(missing),flush=True)


if __name__=='__main__':main()
