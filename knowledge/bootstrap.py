"""Initialize the bundled knowledge collection without changing the legacy source."""
import json
from pathlib import Path
import sqlite3

LEGACY_SOURCE = Path(__file__).resolve().parent / "data" / "milvus_lite.db"
DEFAULT_COLLECTION = "medical_knowledge"
DEFAULT_EMBEDDING = "BAAI/bge-small-zh-v1.5"


def validate_target(target, source=LEGACY_SOURCE):
    target = Path(target).expanduser().resolve()
    if target == Path(source).resolve():
        raise ValueError("MEDIX_DB_PATH points to the read-only legacy source. Select a separate V3 database directory.")
    if target.is_file():
        raise ValueError(f"V3 requires a database directory, but this path is a file: {target}. Keep milvus_lite.db as the legacy source; use a separate milvus_v3.db directory.")
    target.parent.mkdir(parents=True, exist_ok=True)
    return str(target)


def read_legacy_rows(source=LEGACY_SOURCE, dimension=512):
    from pymilvus.grpc_gen import schema_pb2

    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Bundled knowledge source is missing: {source}. Restore knowledge/data/milvus_lite.db from the repository.")
    try:
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as connection:
            # Legacy Milvus stores protobuf bytes with SQLite TEXT storage class.
            connection.text_factory = bytes
            blobs = connection.execute("SELECT data FROM medical_knowledge").fetchall()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"Cannot read legacy knowledge source: {source}") from exc
    rows = []
    for (blob,) in blobs:
        record = schema_pb2.StructArrayField.FromString(blob)
        fields = {field.field_name: field for field in record.fields}
        metadata = json.loads(fields["$meta"].scalars.json_data.data[0])
        vector = list(fields["vector"].vectors.float_vector.data)
        if len(vector) != dimension or not metadata.get("content", "").strip():
            raise ValueError("Bundled knowledge contains empty text or incompatible vector dimensions; refusing to import.")
        attributes = metadata["metadata"]
        attributes = json.loads(attributes) if isinstance(attributes, str) else attributes
        rows.append({"vector": vector, "content": metadata["content"],
                     "metadata": json.dumps(attributes, ensure_ascii=False),
                     "doc_type": attributes.get("type", "general")})
    if not rows:
        raise ValueError("Bundled knowledge source has no records; refusing to initialize an empty default knowledge base.")
    return rows


def ensure_knowledge_collection(client, collection_name=DEFAULT_COLLECTION, dimension=512,
                                bootstrap=True, source=LEGACY_SOURCE):
    exists = client.has_collection(collection_name)
    if exists:
        description = client.describe_collection(collection_name)
        vector = next((field for field in description.get("fields", []) if field.get("name") == "vector"), None)
        if vector is None or int(vector.get("params", {}).get("dim", 0)) != dimension:
            raise ValueError("Knowledge vector dimensions do not match the embedding model. Use a new database or rebuild the index.")
        client.load_collection(collection_name)
        count = int(client.get_collection_stats(collection_name)["row_count"])
        if count:
            # Preserve user-added documents, not just collections with exactly 180 rows.
            return {"status": "existing", "rows": count, "imported": 0}
    rows = read_legacy_rows(source, dimension) if bootstrap else []
    if not exists:
        client.create_collection(collection_name=collection_name, dimension=dimension,
                                 metric_type="COSINE", auto_id=True)
    if rows:
        client.insert(collection_name, rows)
        client.flush(collection_name)
    client.load_collection(collection_name)
    count = int(client.get_collection_stats(collection_name)["row_count"])
    if rows and count != len(rows):
        raise RuntimeError(f"Knowledge import did not finish: {count} records found, {len(rows)} expected. Refusing to report success.")
    return {"status": "seeded" if rows else "empty", "rows": count, "imported": len(rows)}
