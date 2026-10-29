"""Build or verify an immutable evidence index. Never migrates legacy rows."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from knowledge.evidence import EvidenceKnowledgeBase

if __name__ == '__main__':
    kb=EvidenceKnowledgeBase()
    print(json.dumps({'version':kb.version,'documents':len(kb.documents),'chunks':kb.count_documents(),'path':kb.db_path,'embedding':kb.embedding_model.identity},ensure_ascii=False))
    kb.milvus_client.close()
    kb.embedding_model.close()
    if kb.reranker:kb.reranker.close()
