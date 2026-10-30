"""Resumable Chinese corpus harvesting. No QA records or generated text count as originals."""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import threading
import time
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from knowledge.corpus import LOCAL, REGISTRY, digest
from knowledge.scripts.fetch_sources import fetch

CACHE=LOCAL/'bulk'
DISEASES='高血压 糖尿病 冠心病 心绞痛 心肌梗死 心力衰竭 心律失常 高脂血症 脑卒中 脑梗死 脑出血 感冒 流感 咳嗽 肺炎 支气管炎 哮喘 慢性阻塞性肺疾病 肺结核 鼻炎 鼻窦炎 咽炎 扁桃体炎 中耳炎 结膜炎 干眼症 白内障 青光眼 近视 胃炎 胃溃疡 胃食管反流 肠炎 腹泻 便秘 痔疮 脂肪肝 乙肝 丙肝 胆囊炎 胆结石 胰腺炎 阑尾炎 肾结石 尿路感染 肾炎 肾病综合征 慢性肾脏病 前列腺增生 前列腺炎 痛风 骨关节炎 类风湿关节炎 骨质疏松 腰椎间盘突出 颈椎病 肩周炎 扭伤 湿疹 荨麻疹 痤疮 足癣 带状疱疹 银屑病 过敏 贫血 缺铁性贫血 甲状腺功能亢进 甲状腺功能减退 肥胖 失眠 抑郁症 焦虑症 偏头痛 癫痫 帕金森病 阿尔茨海默病 月经不调 痛经 子宫肌瘤 阴道炎 乳腺增生 多囊卵巢综合征 手足口病 水痘 麻疹 百日咳 肺癌 胃癌 结直肠癌 乳腺癌 宫颈癌 肝癌 胃肠炎'.split()
DRUGS='对乙酰氨基酚 布洛芬 阿司匹林 氯雷他定 西替利嗪 左西替利嗪 非索非那定 氯苯那敏 孟鲁司特 布地奈德 氟替卡松 沙丁胺醇 特布他林 异丙托溴铵 氨溴索 乙酰半胱氨酸 右美沙芬 阿莫西林 阿莫西林克拉维酸钾 头孢氨苄 头孢克洛 头孢呋辛 头孢克肟 头孢地尼 阿奇霉素 克拉霉素 多西环素 左氧氟沙星 莫西沙星 甲硝唑 奥硝唑 奥司他韦 阿昔洛韦 伐昔洛韦 奥美拉唑 埃索美拉唑 泮托拉唑 雷贝拉唑 法莫替丁 铝碳酸镁 硫糖铝 多潘立酮 莫沙必利 蒙脱石散 口服补液盐 洛哌丁胺 乳果糖 聚乙二醇 开塞露 二甲双胍 阿卡波糖 格列美脲 格列齐特 瑞格列奈 西格列汀 达格列净 恩格列净 利拉鲁肽 司美格鲁肽 胰岛素 氨氯地平 硝苯地平 非洛地平 缬沙坦 氯沙坦 厄贝沙坦 替米沙坦 奥美沙坦 贝那普利 依那普利 培哚普利 美托洛尔 比索洛尔 氢氯噻嗪 吲达帕胺 呋塞米 螺内酯 阿托伐他汀 瑞舒伐他汀 辛伐他汀 非诺贝特 依折麦布 氯吡格雷 替格瑞洛 华法林 利伐沙班 阿哌沙班 硝酸甘油 硝酸异山梨酯 曲美他嗪 地高辛 别嘌醇 非布司他 秋水仙碱 塞来昔布 双氯芬酸 依托考昔 阿仑膦酸钠 碳酸钙 维生素D 骨化三醇 硫酸亚铁 叶酸 甲钴胺 维生素B12 左甲状腺素 甲巯咪唑 丙硫氧嘧啶 泼尼松 地塞米松 氢化可的松 他克莫司 甲氨蝶呤 羟氯喹 氟康唑 伊曲康唑 特比萘芬 克霉唑 酮康唑 莫匹罗星 夫西地酸 阿达帕林 维A酸 过氧苯甲酰 氧化锌 炉甘石 氯霉素 左氧氟沙星滴眼液 人工泪液 拉坦前列素 坦索罗辛 非那雄胺 舍曲林 艾司西酞普兰 氟西汀 文拉法辛 度洛西汀 劳拉西泮 艾司唑仑 唑吡坦 丙戊酸钠 左乙拉西坦 卡马西平 加巴喷丁 普瑞巴林 左旋多巴 多奈哌齐 美金刚 复方氨酚烷胺 氨咖黄敏 复方甘草 复方鲜竹沥 连花清瘟 藿香正气 六味地黄丸 逍遥丸 归脾丸 板蓝根 蒲地蓝'.split()
VOCAB=DISEASES+DRUGS
_lock=threading.Lock();_last={}


def get(url,**kwargs):
    host=__import__('urllib.parse',fromlist=['urlparse']).urlparse(url).hostname
    with _lock:
        delay=max(0,.25-(time.monotonic()-_last.get(host,0)))
        if delay:time.sleep(delay)
        _last[host]=time.monotonic()
    response=requests.get(url,timeout=35,headers={'User-Agent':'MediX-local-research/1.0','Accept-Encoding':'gzip, deflate'},**kwargs)
    response.raise_for_status();response.encoding='utf8'
    return response


def discover():
    results={}
    for start in range(1,1100,60):
        raw=get('https://www.cma.org.cn/module/web/jpage/dataproxy.jsp',params={'webid':1,'path':'/','columnid':4584,'unitid':325,'permissiontype':0,'startrecord':start,'endrecord':min(start+59,1095),'perpage':20}).text
        soup=BeautifulSoup(''.join(re.findall(r'<!\[CDATA\[(.*?)\]\]>',raw,re.S)),'html.parser')
        for a in soup.select('a[href]'):
            href=a.get('href','')
            match=re.search(r'/art/(\d{4})/(\d+)/(\d+)/art_4584_(\d+)\.html',href)
            if not match:continue
            for span in a.select('span'):span.decompose()
            title=a.get_text(' ',strip=True)
            url=urljoin('https://www.cma.org.cn',href)
            results[url]={'id':'cma_'+match[4],'title':title,'url':url,'publisher':'中华医学会科学普及部','published_at':f'{match[1]}-{int(match[2]):02}-{int(match[3]):02}','kind':'cma'}
    for category in [0,4]:
        for page in range(1,241):
            soup=BeautifulSoup(get(f'https://www.dayi.org.cn/list/{category}/{page}').text,'html.parser')
            for a in soup.select('a[href]'):
                href=a.get('href','')
                match=re.fullmatch(r'/(disease|drug)/(\d+)\.html',href)
                if not match:continue
                title=a.get_text(' ',strip=True)
                if not title:continue
                url=urljoin('https://www.dayi.org.cn',href)
                results[url]={'id':'dayi_'+match[1]+'_'+match[2],'title':title,'url':url,'publisher':'中国医药信息查询平台','published_at':None,'kind':match[1]}
            if page%40==0:print('discovered',category,page,len(results),flush=True)
    return list(results.values())


def harvest(candidate):
    key=candidate['id'];meta=CACHE/'metadata'/(key+'.json')
    if meta.exists():return json.loads(meta.read_text(encoding='utf8'))
    try:
        response=get(candidate['url']);soup=BeautifulSoup(response.text,'html.parser')
        if candidate['kind']=='cma':node=soup.select_one('.TRS_Editor') or soup.select_one('#zoom') or soup.select_one('.content')
        elif candidate['kind'] in ('disease','drug'):node=soup.select_one('article.article-detail-container')
        else:
            selectors=[candidate['body_selector']] if candidate.get('body_selector') else ['.TRS_Editor','.article-content','.article_content','#zoom','.pages_content','article','.article','.content']
            node=next((soup.select_one(selector) for selector in selectors if soup.select_one(selector) is not None),None)
        if node is None:raise ValueError('Missing article body')
        for tag in node.select('script,style,nav,footer,button,.article-catalog,.catalog'):tag.decompose()
        heading=soup.find('h1');title=heading.get_text(' ',strip=True) if heading and candidate['kind']!='other' else candidate['title']
        if len(title)>160 or not title:raise ValueError('Invalid title')
        paragraphs=[re.sub(r'[ \t\xa0\u3000]+',' ',x).strip() for x in node.get_text('\n').splitlines()]
        paragraphs=[x for x in paragraphs if x]
        body='\n\n'.join(paragraphs)
        if len(re.findall(r'[\u4e00-\u9fff]',body))<200:raise ValueError('Not a full Chinese article')
        if any(term not in body for term in candidate.get('required_terms',[])):raise ValueError('Required content missing')
        text='# '+title+'\n\n'+body+'\n'
        topics=[t for t in VOCAB if t in title]
        if not topics:topics=[t for t in VOCAB if t in body][:12]
        if candidate['kind'] in ['disease','drug']:topics=list(dict.fromkeys([title]+topics))
        if not topics:topics=['健康科普']
        source={k:v for k,v in candidate.items() if k!='kind'}
        source.update(title=title,type=candidate.get('type','drug_reference' if candidate['kind']=='drug' else 'health_education'),
                      evidence_kind=candidate.get('evidence_kind','drug_reference' if candidate['kind']=='drug' else 'medical_encyclopedia' if candidate['kind']=='disease' else 'popular_science'),
                      topics=topics,required_terms=[],audiences=['unspecified'],language='zh',jurisdiction='CN',
                      source_tier=candidate.get('source_tier','professional_platform' if candidate['kind']!='cma' else 'medical_society'),
                      document_kind='专业平台编辑条目，非政府数据库，非具体制剂核准说明书' if candidate['kind']!='cma' else '医学会健康科普，非药品说明书')
        metadata={**source,'retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'content_sha256':digest(text),'snapshot_sha256':hashlib.sha256(response.content).hexdigest(),
                  'body_sha256':digest(re.sub(r'\s+','',body)),
                  'source_checked':True,'clinical_reviewed':False,
                  'use_conditions':'仅本机非商业研究；未获全文再分发授权，不上传正文、快照或数据库。'}
        (CACHE/'documents'/(key+'.md')).write_bytes(text.encode('utf8'))
        (CACHE/'snapshots'/(key+'.html')).write_bytes(response.content)
        meta.write_bytes(json.dumps(metadata,ensure_ascii=False).encode('utf8'))
        return metadata
    except Exception as exc:
        return {'id':key,'error':type(exc).__name__}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--target',type=int,default=3100);parser.add_argument('--discover-only',action='store_true');args=parser.parse_args()
    for folder in ['documents','snapshots','metadata']:(CACHE/folder).mkdir(parents=True,exist_ok=True)
    registry=CACHE/'candidates.json'
    if registry.exists():candidates=json.loads(registry.read_text(encoding='utf8'))
    else:
        candidates=discover();registry.write_bytes(json.dumps(candidates,ensure_ascii=False,indent=2).encode('utf8'))
    print('candidate originals',len(candidates),flush=True)
    if args.discover_only:return
    import itertools
    groups=[]
    for kind in ['cma','disease','drug']:
        group=[c for c in candidates if c['kind']==kind]
        group.sort(key=lambda c:(0 if c['title'] in VOCAB else 1,c['id']))
        groups.append(group)
    candidates=[c for batch in itertools.zip_longest(*groups) for c in batch if c]
    successful=[];seen=set();failures=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        # Fixed batches prevent scheduling an unlimited crawl after the target.
        for offset in range(0,len(candidates),100):
            for result in pool.map(harvest,candidates[offset:offset+100]):
                if 'error' in result:failures.append(result);continue
                if result['body_sha256'] in seen:continue
                seen.add(result['body_sha256']);successful.append(result)
            print('harvested unique',len(successful),'rejected',len(failures),flush=True)
            (CACHE/'harvest.json').write_bytes(json.dumps({'documents':successful,'failures':failures},ensure_ascii=False).encode('utf8'))
            if len(successful)>=args.target:break
    print(json.dumps({'unique_originals':len(successful),'target':args.target,'met':len(successful)>=args.target}),flush=True)


if __name__=='__main__':main()
