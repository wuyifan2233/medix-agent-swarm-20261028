"""医学知识库模块。默认使用证据库，初始化失败不自动降级。"""
from .mini_kb import MiniKnowledgeBase, get_knowledge_base

try:
    from .milvus_kb import MedicalKnowledgeBase
except Exception:  # pragma: no cover - optional heavy dependency
    MedicalKnowledgeBase = None

__all__ = ["MedicalKnowledgeBase", "MiniKnowledgeBase", "get_knowledge_base"]
