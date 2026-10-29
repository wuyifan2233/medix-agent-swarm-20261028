"""Verify cloud memory using an isolated synthetic user, then remove test rows."""
import json
import os
import sys
import time
import uuid
from pathlib import Path
from loguru import logger
sys.path.insert(0, str(Path(__file__).resolve().parent))

logger.remove()
logger.add(lambda msg: print(str(msg).replace(os.environ.get("MEM0_API_KEY", "[unset]"), "[REDACTED]"), end=""), level="WARNING")

def rows(response):
    if isinstance(response, list):
        return response
    return response.get("results", []) if isinstance(response, dict) else []

def main():
    from mem0.memory.telemetry import telemetry
    telemetry.posthog.disabled = True
    from memory.long_term import LongTermMemory
    user_id = "medix-envcheck-" + uuid.uuid4().hex
    config = {"api_key": os.environ["MEM0_API_KEY"], "user_id": user_id}
    result = {"check": "mem0_write_cross_session_search", "status": "failed", "test_user": user_id}
    client = None
    try:
        first = LongTermMemory(config)
        assert first.enabled, "Mem0 client initialization failed"
        client = first.mem0
        native_add = client.add
        def observed_add(*args, **kwargs):
            response = native_add(*args, **kwargs)
            result["add_response"] = response
            return response
        client.add = observed_add
        memory_id = first.add_session_summary(
            session_id="synthetic-env-check",
            question="My favorite color is blue.",
            answer="Remember that my favorite color is blue.",
            metadata={"synthetic_test": True},
        )
        assert memory_id, "Mem0 did not return a memory ID"
        second = LongTermMemory(config)
        assert second.enabled
        matches = []
        for attempt in range(4):
            matches = second.search_similar_sessions("测试用户喜欢什么颜色？", limit=3)
            if matches:
                break
            time.sleep(3)
        assert matches, "No memory found from a new client/session"
        assert any("蓝" in row["content"] or "blue" in row["content"].lower() for row in matches), "Retrieved memory did not contain the synthetic fact"
        result.update(status="passed", memory_id_returned=True, retrieved_records=len(matches))
    except Exception as exc:
        result["error"] = str(exc).replace(os.environ["MEM0_API_KEY"], "[REDACTED]")
    finally:
        if client:
            try:
                created = rows(client.get_all(user_id=user_id))
                for row in created:
                    client.delete(row["id"])
                remaining = rows(client.get_all(user_id=user_id))
                result.update(test_memories_deleted=len(created), test_memories_remaining=len(remaining))
                if remaining:
                    result.update(status="failed", error="Test memory cleanup incomplete")
            except Exception as exc:
                result.update(status="failed", cleanup_error=str(exc).replace(os.environ["MEM0_API_KEY"], "[REDACTED]"))
    Path(__file__).with_name("verification_mem0.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return int(result["status"] != "passed")

if __name__ == "__main__":
    raise SystemExit(main())
