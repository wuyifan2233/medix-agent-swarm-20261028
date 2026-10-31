"""Publish verified original documents as a new corpus generation, preserving old snapshots."""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from knowledge.corpus import LOCAL, REGISTRY, digest
from knowledge.scripts.expand_corpus import CACHE, DISEASES, DRUGS


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--minimum',type=int,default=3000);args=parser.parse_args()
    old=json.loads((LOCAL/'manifest.json').read_text(encoding='utf8'))
    old_root=LOCAL/'generations'/old['generation'] if old.get('generation') else LOCAL
    harvest=json.loads((CACHE/'harvest.json').read_text(encoding='utf8'))['documents']
    if (CACHE/'supplement.json').exists():harvest+=json.loads((CACHE/'supplement.json').read_text(encoding='utf8'))['documents']
    docs=list(old['documents']);locations={d['id']:old_root for d in docs}
    urls={d['url'] for d in docs};hashes={d['content_sha256'] for d in docs}
    registry=json.loads(REGISTRY.read_text(encoding='utf8'));sources=list(registry['documents'])
    metadata_keys={'retrieved_at','content_sha256','snapshot_sha256','source_checked','clinical_reviewed','body_sha256','use_conditions'}
    for doc in harvest:
        if doc['url'] in urls or doc['content_sha256'] in hashes:continue
        urls.add(doc['url']);hashes.add(doc['content_sha256']);docs.append(doc);locations[doc['id']]=CACHE
        sources.append({k:v for k,v in doc.items() if k not in metadata_keys})
    if len(docs)<args.minimum:raise ValueError(f'Only {len(docs)} unique originals; refusing to publish below {args.minimum}')
    staging=Path(tempfile.mkdtemp(prefix='.bulk-stage-',dir=LOCAL))
    for folder in ['documents','snapshots']:(staging/folder).mkdir()
    for doc in docs:
        root=locations[doc['id']]
        text=(root/'documents'/(doc['id']+'.md')).read_text(encoding='utf8')
        if digest(text)!=doc['content_sha256']:raise ValueError('Content mismatch: '+doc['id'])
        for folder,extension in [('documents','.md'),('snapshots',doc.get('snapshot_extension','.html'))]:
            shutil.copy2(root/folder/(doc['id']+extension),staging/folder/(doc['id']+extension))
    generation=digest(json.dumps(docs,sort_keys=True,ensure_ascii=False))[:16]
    target=LOCAL/'generations'/generation
    if not target.exists():staging.replace(target)
    manifest={'documents':docs,'generation':generation}
    # Backups make registry/manifest publication recoverable if interrupted.
    for path in [REGISTRY,LOCAL/'manifest.json']:
        shutil.copy2(path,CACHE/(path.name+'.before-expansion'))
    for path,payload in [(REGISTRY,{**registry,'documents':sources}),(LOCAL/'manifest.json',manifest)]:
        pending=path.with_suffix('.pending.json');pending.write_bytes(json.dumps(payload,ensure_ascii=False,indent=2).encode('utf8'));pending.replace(path)
    coverage={'notice':'Mention-based coverage is not clinical completeness. Drug references are not product-specific approved labels.',
              'original_documents':len(docs),'unique_urls':len(urls),'generation':generation,'diseases':{},'drugs':{}}
    for group,terms in [('diseases',DISEASES),('drugs',DRUGS)]:
        for term in terms:
            matching=[d['id'] for d in docs if term in d['title']]
            coverage[group][term]={'title_matches':len(matching),'document_ids':matching[:8],'status':'covered_by_title' if matching else 'gap'}
    (LOCAL/'coverage.json').write_bytes(json.dumps(coverage,ensure_ascii=False,indent=2).encode('utf8'))
    print(json.dumps({'documents':len(docs),'generation':generation,'disease_gaps':sum(v['status']=='gap' for v in coverage['diseases'].values()),'drug_gaps':sum(v['status']=='gap' for v in coverage['drugs'].values())}),flush=True)


if __name__=='__main__':main()
