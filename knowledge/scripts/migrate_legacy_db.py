"""Copy legacy Milvus 2.x rows/vectors into a separate Milvus 3.x database.

The source SQLite database is read-only. No embeddings are trained or recomputed.
"""
import json
import sys
from pathlib import Path
from pymilvus import MilvusClient

DATA = Path(__file__).resolve().parents[1] / "data"
sys.path.insert(0, str(DATA.parents[1]))
from runtime_paths import DB_PATH
from knowledge.bootstrap import ensure_knowledge_collection, validate_target

def migrate():
    target = validate_target(DB_PATH)
    client = MilvusClient(target)
    try:
        result = ensure_knowledge_collection(client)
        print(json.dumps({"migrated_rows": result["rows"], "target": target, **result}, ensure_ascii=False))
        return result
    finally:
        client.close()

if __name__ == "__main__":
    migrate()
