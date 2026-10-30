"""Copy legacy Milvus 2.x rows/vectors into a separate Milvus 3.x database.

The source SQLite database is read-only. No embeddings are trained or recomputed.
"""
import json
import sqlite3
import sys
from pathlib import Path
from pymilvus import MilvusClient
from pymilvus.grpc_gen import schema_pb2

DATA = Path(__file__).resolve().parents[1] / "data"
sys.path.insert(0, str(DATA.parents[1]))
from runtime_paths import DB_PATH

def migrate():
    source = DATA / "milvus_lite.db"
    target = Path(DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as connection:
        connection.text_factory = bytes
        blobs = connection.execute('SELECT data FROM medical_knowledge').fetchall()
    rows = []
    for (blob,) in blobs:
        record = schema_pb2.StructArrayField.FromString(blob)
        fields = {field.field_name: field for field in record.fields}
        row = json.loads(fields["$meta"].scalars.json_data.data[0])
        metadata = row["metadata"]
        metadata = json.loads(metadata) if isinstance(metadata, str) else metadata
        rows.append({"vector": list(fields["vector"].vectors.float_vector.data),
                     "content": row["content"], "metadata": json.dumps(metadata, ensure_ascii=False),
                     "doc_type": metadata.get("type", "general")})
    assert rows and all(len(row["vector"]) == 512 for row in rows)
    client = MilvusClient(str(target), grpc_options={"grpc.keepalive_time_ms": 120000, "grpc.keepalive_permit_without_calls": False})
    try:
        name = "medical_knowledge"
        if not client.has_collection(name):
            client.create_collection(collection_name=name, dimension=512,
                                     metric_type="COSINE", auto_id=True)
        count = client.get_collection_stats(name)["row_count"]
        if count == 0:
            client.insert(name, rows)
            client.flush(name)
        elif count != len(rows):
            raise RuntimeError(f"Target contains {count} rows; expected {len(rows)}. Refusing to overwrite.")
        count = client.get_collection_stats(name)["row_count"]
        assert count == len(rows), (count, len(rows))
        print(json.dumps({"migrated_rows": count, "target": str(target)}, ensure_ascii=False))
    finally:
        client.close()

if __name__ == "__main__":
    migrate()
