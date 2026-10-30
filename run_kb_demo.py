"""Opt-in evidence demo; the standard entry point retains legacy compatibility."""
import os
from pathlib import Path
os.environ['MEDIX_KB_MODE']='evidence'
os.environ.setdefault('HF_HOME',str(Path(__file__).resolve().parent/'.medix-model-cache'))
if __name__ == '__main__':
    import argparse
    import uvicorn
    from loguru import logger
    import sys
    parser=argparse.ArgumentParser(description='本地医学证据库演示')
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--prepare-only',action='store_true',help='Download missing originals and build local index, then exit')
    args=parser.parse_args()
    os.chdir(Path(__file__).resolve().parent)
    logger.remove()
    logger.add(sys.stderr,level='WARNING',filter=lambda record:record['name'].startswith('web.'))
    if args.prepare_only:
        from knowledge.initialize import ensure_sources
        ensure_sources()
        from knowledge.evidence import EvidenceKnowledgeBase
        kb=EvidenceKnowledgeBase()
        print({'version':kb.version,'documents':len(kb.documents),'chunks':kb.count_documents(),'database':kb.db_path})
        kb.milvus_client.close();kb.embedding_model.close()
        if kb.reranker:kb.reranker.close()
        raise SystemExit(0)
    print(f'MediX 证据库：http://127.0.0.1:{args.port}',flush=True)
    uvicorn.run('web.app:app',host='127.0.0.1',port=args.port,log_level='warning')
