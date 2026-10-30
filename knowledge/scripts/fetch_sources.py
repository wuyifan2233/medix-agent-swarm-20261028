"""Fetch only the reviewed registry; snapshots stay local, not redistributed."""
import concurrent.futures
import datetime
import json
import re
import tempfile
import shutil
import argparse
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import requests
from bs4 import BeautifulSoup
from knowledge.corpus import LOCAL, REGISTRY, MINIMUM_DOCUMENTS, digest, registry_digest


_request_lock=threading.Lock()
_last_request={}


def _download(url):
    host=urlparse(url).hostname
    for attempt in range(3):
        with _request_lock:
            delay=max(0,.3-(time.monotonic()-_last_request.get(host,0)))
            if delay:time.sleep(delay)
            _last_request[host]=time.monotonic()
        try:
            response=requests.get(url,timeout=45,headers={'User-Agent':'MediX-local-research/1.0'})
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            code=getattr(getattr(exc,'response',None),'status_code',None)
            if attempt==2 or (code is not None and code not in (429,500,502,503,504)):raise
            time.sleep(.75*(2**attempt))


def fetch(source,destination=LOCAL):
    response = _download(source['url'])
    if urlparse(response.url).hostname != urlparse(source['url']).hostname:
        raise ValueError('Unexpected redirect: ' + response.url)
    response.encoding = response.apparent_encoding
    soup = BeautifulSoup(response.text, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'footer']):
        tag.decompose()
    selectors = ['article.article-detail-container', '.TRS_Editor', '.view.TRS_UEDITOR', '.pages_content', '#UCAP-CONTENT', '.article-content', '.article_content', '#vsb_content', '.v_news_content', '.article', '.content', '#zoom']
    if source.get('body_selector'):selectors=[source['body_selector']]
    nodes = [soup.select_one(s) for s in selectors]
    nodes = [n for n in nodes if n and len(n.get_text(strip=True)) > 150]
    if not nodes:
        raise ValueError('Article body selector missing: ' + source['id'])
    node = nodes[0]
    paragraphs = [re.sub(r'[ \t\xa0\u3000]+', ' ', line).strip() for line in node.get_text('\n').splitlines()]
    paragraphs = [p for p in paragraphs if p]
    text = '\n\n'.join(paragraphs)
    if any(term not in text for term in source['required_terms']):
        raise ValueError('Content verification failed: ' + source['id'])
    # Mark only genuine short section labels; do not invent medical summaries.
    paragraphs = [('## ' + p if len(p) < 65 and re.match(r'^(?:[一二三四五六七八九十]+[、．.]|[（(][一二三四五六七八九十]+[）)])', p) else p) for p in paragraphs]
    text = '# ' + source['title'] + '\n\n' + '\n\n'.join(paragraphs) + '\n'
    html_path = destination / 'snapshots' / (source['id'] + '.html')
    html_path.write_bytes(response.content)
    (destination / 'documents' / (source['id'] + '.md')).write_text(text, encoding='utf-8')
    return {**source, 'retrieved_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'content_sha256': digest(text), 'snapshot_sha256': __import__('hashlib').sha256(response.content).hexdigest(),
            'source_checked': True, 'clinical_reviewed': False,
            'use_conditions': source.get('use_conditions','公开可读；未确认再分发许可，仅本地演示使用，不随仓库分发。'),
            'document_kind': source.get('document_kind','官方发布或官方转载科普，非药品说明书；不代表最新临床指南')}


def _verified(source,metadata,root):
    try:
        if not metadata or not all(metadata.get(k)==v for k,v in source.items()):return False
        document=root/'documents'/(source['id']+'.md')
        snapshot=root/'snapshots'/(source['id']+source.get('snapshot_extension','.html'))
        return (document.is_file() and snapshot.is_file()
                and digest(document.read_text(encoding='utf8'))==metadata['content_sha256']
                and __import__('hashlib').sha256(snapshot.read_bytes()).hexdigest()==metadata['snapshot_sha256'])
    except (OSError,KeyError,ValueError):return False


def _read_metadata(path):
    try:return json.loads(path.read_text(encoding='utf8'))
    except (OSError,ValueError):return None


def _install_generation(staging,target,docs):
    valid=target.is_dir() and all(_verified(d,d,target) for d in docs)
    if not valid:
        try:
            if not target.exists():staging.replace(target)
            else:shutil.copytree(staging,target,dirs_exist_ok=True)
        except PermissionError:
            # Windows scanners may hold a newly downloaded directory open.
            # The manifest is published only after the copied generation verifies.
            shutil.copytree(staging,target,dirs_exist_ok=True)
        if not all(_verified(d,d,target) for d in docs):raise ValueError('Published generation verification failed')
    if staging.exists():shutil.rmtree(staging,ignore_errors=True)


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--incremental',action='store_true',help='Reuse verified corpus and per-document download caches')
    parser.add_argument('--minimum',type=int,help='Allow an explicitly reported partial corpus, never below the 3000-original floor')
    args=parser.parse_args(argv)
    LOCAL.mkdir(parents=True,exist_ok=True)
    sources=json.loads(REGISTRY.read_text(encoding='utf8'))['documents']
    if not sources or len({s['id'] for s in sources})!=len(sources):raise ValueError('Empty or duplicate source registry')
    minimum=len(sources) if args.minimum is None else max(min(MINIMUM_DOCUMENTS,len(sources)),args.minimum)
    if minimum>len(sources):raise ValueError('Minimum exceeds registry size')
    previous={};previous_order={};old_root=LOCAL
    if args.incremental and (LOCAL/'manifest.json').exists():
        old=json.loads((LOCAL/'manifest.json').read_text(encoding='utf8'))
        previous={d['id']:d for d in old['documents']}
        previous_order={d['id']:i for i,d in enumerate(old['documents'])}
        generation=old.get('generation')
        if generation and not re.fullmatch(r'[a-f0-9]{16}',generation):raise ValueError('Invalid old generation')
        old_root=LOCAL/'generations'/generation if generation else LOCAL

    def fetch_or_reuse(source):
        try:
            key=digest(json.dumps(source,sort_keys=True,ensure_ascii=False))
            cache=LOCAL/'downloads'/key
            metadata_path=cache/'metadata.json'
            if args.incremental:
                old=previous.get(source['id'])
                if _verified(source,old,old_root):return old,old_root
                cached=_read_metadata(metadata_path)
                if _verified(source,cached,cache):return cached,cache
            for folder in ['documents','snapshots']:(cache/folder).mkdir(parents=True,exist_ok=True)
            metadata=fetch(source,cache)
            pending=metadata_path.with_suffix('.pending')
            pending.write_text(json.dumps(metadata,ensure_ascii=False),encoding='utf8');pending.replace(metadata_path)
            return metadata,cache
        except Exception as exc:
            return {'id':source['id'],'error':type(exc).__name__},None

    successful=[];failures=[];body_hashes=set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for metadata,location in pool.map(fetch_or_reuse,sources):
            if location is None:failures.append(metadata)
            else:
                text=(location/'documents'/(metadata['id']+'.md')).read_text(encoding='utf8')
                body_hash=digest(''.join(text.split('\n',1)[-1].split()))
                if body_hash in body_hashes:failures.append({'id':metadata['id'],'error':'DuplicateBody'})
                else:
                    body_hashes.add(body_hash);successful.append((metadata,location))
            done=len(successful)+len(failures)
            if done%25==0:print(f'Sources: {done}/{len(sources)}, available={len(successful)}, failed={len(failures)}',flush=True)
    status={'requested':len(sources),'available':len(successful),'minimum':minimum,'failures':failures}
    (LOCAL/'download-status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf8')
    if len(successful)<minimum:
        raise RuntimeError(f'Only {len(successful)}/{len(sources)} originals available; {minimum} required. Successful downloads are cached. Retry with --incremental; see knowledge/.local/download-status.json')
    staging=Path(tempfile.mkdtemp(prefix='.stage-',dir=LOCAL))
    for folder in ['documents','snapshots']:(staging/folder).mkdir()
    docs=[]
    for metadata,location in successful:
        docs.append(metadata)
        for folder,extension in [('documents','.md'),('snapshots',metadata.get('snapshot_extension','.html'))]:
            shutil.copy2(location/folder/(metadata['id']+extension),staging/folder/(metadata['id']+extension))
    manifest={'documents':sorted(docs,key=lambda d:(previous_order.get(d['id'],len(previous_order)),d['id']))}
    if failures:
        manifest.update(registry_sha256=registry_digest(sources),minimum_originals=minimum,missing_sources=failures)
    generation=digest(json.dumps(manifest,sort_keys=True,ensure_ascii=False))[:16]
    target=LOCAL/'generations'/generation;target.parent.mkdir(parents=True,exist_ok=True)
    if not staging.resolve().is_relative_to(LOCAL.resolve()) or not target.resolve().is_relative_to(LOCAL.resolve()):
        raise ValueError('Corpus generation must remain within the local corpus directory')
    _install_generation(staging,target,docs)
    manifest['generation']=generation
    pending=LOCAL/'manifest.pending.json'
    pending.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8');pending.replace(LOCAL/'manifest.json')
    print(json.dumps({**status,'generation':generation},ensure_ascii=False),flush=True)
    return status


if __name__=='__main__':main()
