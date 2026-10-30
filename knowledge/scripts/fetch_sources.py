"""Fetch only the reviewed registry; snapshots stay local, not redistributed."""
import concurrent.futures
import datetime
import json
import re
import tempfile
import shutil
import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import requests
from bs4 import BeautifulSoup
from knowledge.corpus import LOCAL, REGISTRY, digest


def fetch(source,destination=LOCAL):
    response = requests.get(source['url'], timeout=45)
    response.raise_for_status()
    if urlparse(response.url).hostname != urlparse(source['url']).hostname:
        raise ValueError('Unexpected redirect: ' + response.url)
    response.encoding = response.apparent_encoding
    soup = BeautifulSoup(response.text, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'footer']):
        tag.decompose()
    selectors = ['.TRS_Editor', '.view.TRS_UEDITOR', '.pages_content', '#UCAP-CONTENT', '.article-content', '.article_content', '#vsb_content', '.v_news_content', '.content', '#zoom']
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


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--incremental',action='store_true',help='Reuse unchanged hash-verified local snapshots')
    args=parser.parse_args(argv)
    LOCAL.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.stage-',dir=LOCAL))
    for folder in ['documents', 'snapshots']:
        (staging / folder).mkdir(parents=True, exist_ok=True)
    sources = json.loads(REGISTRY.read_text(encoding='utf-8'))['documents']
    previous={};old_root=LOCAL
    if args.incremental and (LOCAL/'manifest.json').exists():
        old=json.loads((LOCAL/'manifest.json').read_text(encoding='utf8'))
        previous={d['id']:d for d in old['documents']}
        generation=old.get('generation')
        if generation and not re.fullmatch(r'[a-f0-9]{16}',generation):raise ValueError('Invalid old generation')
        old_root=LOCAL/'generations'/generation if generation else LOCAL
    def fetch_or_reuse(source):
        old=previous.get(source['id'])
        if old and all(old.get(k)==v for k,v in source.items()):
            document=old_root/'documents'/(source['id']+'.md')
            snapshot=old_root/'snapshots'/(source['id']+'.html')
            if document.exists() and snapshot.exists() and digest(document.read_text(encoding='utf8'))==old['content_sha256'] and __import__('hashlib').sha256(snapshot.read_bytes()).hexdigest()==old['snapshot_sha256']:
                shutil.copy2(document,staging/'documents'/document.name)
                shutil.copy2(snapshot,staging/'snapshots'/snapshot.name)
                return old
        return fetch(source,staging)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        docs = list(pool.map(fetch_or_reuse, sources))
    manifest = {'documents': sorted(docs, key=lambda d: d['id'])}
    generation=digest(json.dumps(manifest,sort_keys=True,ensure_ascii=False))[:16]
    target=LOCAL/'generations'/generation
    target.parent.mkdir(parents=True,exist_ok=True)
    if not staging.resolve().is_relative_to(LOCAL.resolve()) or not target.resolve().is_relative_to(LOCAL.resolve()):
        raise ValueError('Corpus generation must remain within the local corpus directory')
    staging.replace(target)
    manifest['generation']=generation
    temp_manifest=LOCAL/'manifest.pending.json'
    temp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    temp_manifest.replace(LOCAL/'manifest.json')
    print(json.dumps({'fetched': len(docs), 'directory': str(LOCAL)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
