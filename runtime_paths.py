"""FAISS on Windows requires an ASCII index path; keep source data intact."""
import hashlib
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
project_id = hashlib.sha256(str(ROOT).encode("utf-8")).hexdigest()[:12]
DEFAULT_DB_PATH = str(Path(tempfile.gettempdir()) / ("medix-" + project_id) / "milvus_v3.db")
DB_PATH = os.environ.get("MEDIX_DB_PATH", DEFAULT_DB_PATH)
