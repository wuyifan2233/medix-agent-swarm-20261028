"""First-run evidence preparation; never publishes third-party originals."""
from knowledge.corpus import LOCAL, REGISTRY, MINIMUM_DOCUMENTS, load_corpus


def ensure_sources():
    if (LOCAL/'manifest.json').exists():
        try:
            docs=load_corpus()
            return {'status':'existing','documents':len(docs)}
        except ValueError as exc:
            if str(exc) not in ('Local corpus does not match source registry; fetch sources again','Source registry changed; fetch sources again'):
                raise
    from knowledge.scripts.fetch_sources import main
    print('First evidence preparation: fetching public originals; successful downloads are resumable.',flush=True)
    result=main(['--incremental','--minimum',str(minimum_sources())])
    return {'status':'prepared','documents':result['available'],'missing':len(result['failures'])}


def minimum_sources():
    import json
    return min(MINIMUM_DOCUMENTS,len(json.loads(REGISTRY.read_text(encoding='utf8'))['documents']))
