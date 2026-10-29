"""Lightweight local-text knowledge base used when Milvus is unavailable."""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCS = ROOT / "knowledge" / "data" / "documents"
FALLBACK_SNIPPETS = [
    {
        "id": "mini_medication",
        "content": "用药提醒说明\n用药提醒只记录用户自己设定的时间，不构成医嘱。药名和剂量只使用用户说过的内容。\n常见咨询包括阿司匹林、维生素C、降压药的服用时间。",
        "metadata": {"filename": "mini_medication.txt", "type": "lifestyle"},
    },
    {
        "id": "mini_visit",
        "content": "就诊与复诊提醒\n就诊、复诊提醒帮助用户记住预约时间。提醒不能替代急诊处理。胸痛、呼吸困难、大出血时应立即就医。",
        "metadata": {"filename": "mini_visit.txt", "type": "guideline"},
    },
]


def _terms(text: str) -> set:
    terms = set()
    for match in re.finditer(r"[A-Za-z0-9]{2,}|[\u4e00-\u9fff]{2,}", text.lower()):
        token = match.group(0)
        terms.add(token)
        if re.fullmatch(r"[\u4e00-\u9fff]{2,}", token):
            for index in range(len(token) - 1):
                terms.add(token[index:index + 2])
    return terms


class MiniKnowledgeBase:
    """Keyword retrieval over the project's local medical text files."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, docs_dir: Optional[str] = None):
        if hasattr(self, "_initialized"):
            return
        self.docs_dir = Path(docs_dir) if docs_dir else DEFAULT_DOCS
        self.documents = self._load_documents()
        self.backend = "mini"
        self._initialized = True
        logger.warning("Using mini knowledge base with {} snippets", len(self.documents))

    def _load_documents(self) -> List[Dict[str, Any]]:
        documents = []
        if self.docs_dir.is_dir():
            for path in sorted(self.docs_dir.glob("*.txt")):
                text = path.read_text(encoding="utf-8").strip()
                if not text:
                    continue
                documents.append({
                    "id": path.stem,
                    "content": text,
                    "metadata": {"filename": path.name, "type": "local_text"},
                })
        if not documents:
            documents = [dict(item) for item in FALLBACK_SNIPPETS]
        return documents

    def count_documents(self) -> int:
        return len(self.documents)

    def search(self, query: str, top_k: int = 5, filter_type: Optional[str] = None) -> List[Dict[str, Any]]:
        query_terms = _terms(query or "")
        if not query_terms:
            return []
        scored = []
        for document in self.documents:
            if filter_type and document["metadata"].get("type") != filter_type:
                continue
            content_terms = _terms(document["content"])
            overlap = query_terms & content_terms
            if not overlap:
                continue
            score = len(overlap) / len(query_terms)
            if any(term in document["content"].lower() for term in query_terms if len(term) >= 2):
                score = max(score, 0.45)
            scored.append({
                "id": document["id"],
                "content": document["content"],
                "metadata": document["metadata"],
                "score": round(min(score, 1.0), 4),
            })
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]


def get_knowledge_base():
    """Prefer Milvus; fall back to the local mini index for reminder/chat testing."""
    try:
        from knowledge.milvus_kb import MedicalKnowledgeBase
        kb = MedicalKnowledgeBase()
        kb.backend = "milvus"
        return kb
    except Exception as exc:
        logger.warning("Milvus knowledge base unavailable ({}); using mini fallback", type(exc).__name__)
        return MiniKnowledgeBase()
