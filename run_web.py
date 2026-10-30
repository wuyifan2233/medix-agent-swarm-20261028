"""Unified local entry point; business data and vector indexes are separate."""
import argparse
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def configure_database(port, override=None):
    import runtime_paths
    target = override or os.environ.get('MEDIX_DB_PATH')
    if not target:
        target = str(Path(runtime_paths.DEFAULT_DB_PATH).with_name(f'milvus_web_{port}.db'))
    target = str(Path(target).resolve())
    os.environ['MEDIX_DB_PATH'] = target
    runtime_paths.DB_PATH = target
    return target


def main(default_port=8765, evidence=False):
    if evidence:
        os.environ['MEDIX_KB_MODE'] = 'evidence'
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env.local', override=False)
    load_dotenv(ROOT / '.env.sms', override=False)
    parser = argparse.ArgumentParser(description='MediX local integration')
    parser.add_argument('--port', type=int, default=default_port)
    parser.add_argument('--data-dir', help='Shared account and business data directory')
    parser.add_argument('--db-path', help='Vector index path, NOT the business database')
    if evidence:
        parser.add_argument('--prepare-only', action='store_true', help='Prepare evidence sources and index, then exit')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535: parser.error('port must be between 1 and 65535')
    os.chdir(ROOT)
    bypass = os.environ.get('NO_PROXY', os.environ.get('no_proxy', ''))
    os.environ['NO_PROXY'] = ','.join(filter(None,[bypass,'127.0.0.1','localhost','::1']))
    os.environ['no_proxy'] = os.environ['NO_PROXY']
    os.environ.setdefault('HF_HOME', str(ROOT / '.medix-model-cache'))
    os.environ.setdefault('MEDIX_ALLOWED_ORIGINS', f'http://127.0.0.1:{args.port},http://localhost:{args.port}')
    if args.data_dir: os.environ['MEDIX_DATA_DIR'] = str(Path(args.data_dir).resolve())
    configure_database(args.port, args.db_path)
    if evidence and args.prepare_only:
        from knowledge.initialize import ensure_sources
        from knowledge.evidence import EvidenceKnowledgeBase
        ensure_sources()
        kb=EvidenceKnowledgeBase()
        try:
            print({'version':kb.version,'documents':len(kb.documents),'chunks':kb.count_documents(),'database':kb.db_path})
        finally:
            kb.milvus_client.close()
            kb.embedding_model.close()
            if kb.reranker:kb.reranker.close()
        return
    import uvicorn
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level='WARNING', format='{time:HH:mm:ss} | {level} | {message}')
    print(f'MediX: http://127.0.0.1:{args.port}', flush=True)
    uvicorn.run('web.app:app', host='127.0.0.1', port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
