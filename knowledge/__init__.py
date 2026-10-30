"""医学知识库模块。优先 Milvus，不可用时回落到本地迷你检索。"""
from .mini_kb import MiniKnowledgeBase, get_knowledge_base

try:
    from .milvus_kb import MedicalKnowledgeBase
except Exception:  # pragma: no cover - optional heavy dependency
    MedicalKnowledgeBase = None

__all__ = ["MedicalKnowledgeBase", "MiniKnowledgeBase", "get_knowledge_base"]
