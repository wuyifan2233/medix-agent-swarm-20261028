"""Mem0 Platform backend for the web source journal (no optional SDK required)."""
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from .case_memory import CaseMemory, TOPICS, topics, MemoryConflict


class Mem0Error(RuntimeError):
    """Safe user-facing errors; provider bodies/credentials never leave this layer."""


class WebMem0Memory:
    APP = "medix-web-cases-v1"

    def __init__(self, local=None, api_key=None, transport=None):
        self.local = local or CaseMemory()
        self.api_key = api_key  # None reads the current server config, empty disables.
        self.transport = transport

    @property
    def configured(self):
        from config import MEM0_CONFIG
        return bool(self.api_key if self.api_key is not None else MEM0_CONFIG.get("api_key"))

    @classmethod
    def namespace(cls, owner, patient):
        from auth.settings import AuthSettings
        return f"{cls.APP}:{AuthSettings.from_env().namespace}:{owner}:{patient}"

    def _request(self, method, path, body=None, params=None, missing_ok=False):
        from config import MEM0_CONFIG
        key = self.api_key if self.api_key is not None else MEM0_CONFIG.get("api_key", "")
        if not key:
            raise Mem0Error("尚未配置 Mem0 密钥，请在本地 .env.local 填写 MEM0_API_KEY 后重启。")
        try:
            with httpx.Client(base_url="https://api.mem0.ai", headers={"Authorization": "Token " + key},
                              timeout=20, transport=self.transport, follow_redirects=False) as client:
                response = client.request(method, path, json=body, params=params)
            if missing_ok and response.status_code == 404: return None
            if response.status_code in (401, 403):
                raise Mem0Error("Mem0 鉴权失败，请检查服务端密钥及其项目权限。")
            if response.status_code == 429:
                raise Mem0Error("Mem0 请求过多或额度不足，请稍后重试并检查服务额度。")
            response.raise_for_status()
            return response.json() if response.content else {}
        except Mem0Error:
            raise
        except (httpx.HTTPError, ValueError):
            raise Mem0Error("Mem0 暂时无法连接或响应异常；未将本机保存冒充云端成功。") from None

    @staticmethod
    def _rows(response):
        if isinstance(response, list): return response
        return response.get("results", []) if isinstance(response, dict) else []

    def _settled(self, response):
        if not isinstance(response, dict) or not response.get("event_id"): return response
        # Raw imports are normally synchronous; accept asynchronous acknowledgements safely.
        deadline = time.monotonic() + 35
        event_id = quote(str(response["event_id"]), safe="")
        while time.monotonic() < deadline:
            event = self._request("GET", f"/v1/event/{event_id}/")
            if event.get("status") == "SUCCEEDED": return event
            if event.get("status") == "FAILED": raise Mem0Error("Mem0 写入失败，记录未确认保存。")
            time.sleep(1)
        raise Mem0Error("Mem0 写入仍在处理中，尚未确认成功；请稍后查看记忆列表。")

    def _owned(self, row, owner, patient=None):
        if not isinstance(row, dict): return False
        meta = row.get("metadata") or {}
        person = meta.get("patient")
        return (meta.get("source_app") == self.APP and meta.get("owner_id") == owner
                and person in {"self", "father", "mother"} and (patient is None or person == patient)
                and row.get("user_id", self.namespace(owner, person)) == self.namespace(owner, person))

    @staticmethod
    def _active(metadata):
        return metadata.get("active", True) not in (False, 0, "false", "False", "0")

    @staticmethod
    def _public(row):
        meta = row["metadata"]
        raw_topics = meta.get("topics", [])
        if isinstance(raw_topics, str):
            try:
                raw_topics = json.loads(raw_topics)
            except (ValueError, TypeError):
                raw_topics = None
        if not isinstance(raw_topics, list):
            raw_topics = topics(meta["original_content"] + "\n" + meta.get("observations", ""))
        canonical_topics = [tag for tag in raw_topics if isinstance(tag, str) and tag in TOPICS]
        return dict(id=row["id"], session=meta["session_id"], patient=meta["patient"],
                    content=meta["original_content"], observations=meta.get("observations", ""),
                    topics=canonical_topics, created=meta.get("recorded_at", row.get("created_at")),
                    active=int(WebMem0Memory._active(meta)), backend="mem0",
                    revision=int(meta.get("revision",0)), edited_at=meta.get("edited_at"))

    def _get(self, owner, memory_id):
        if not re.fullmatch(r"[a-fA-F0-9-]{36}", memory_id): return None
        row = self._request("GET", f"/v1/memories/{memory_id}/", missing_ok=True)
        return row if self._owned(row, owner) else None

    def save(self, owner, session, question, patient="self", observations="", created=None):
        tags = topics(question + "\n" + observations)
        # The web resolver already determines a personal health subject. Themes
        # annotate/restrict recall; they must not be a whitelist for cloud storage.
        if patient not in {"self", "father", "mother"} or not (question.strip() or observations.strip()):
            return None
        metadata = dict(source_app=self.APP, owner_id=owner, patient=patient, session_id=session,
                        original_content=question, observations=observations, topics=tags, active=True,
                        recorded_at=created or datetime.now(timezone.utc).isoformat())
        raw = question + ("\n\n【图片客观读取，可能有误差】\n" + observations if observations else "")
        response = self._settled(self._request("POST", "/v3/memories/add/", {
            "user_id": self.namespace(owner, patient), "run_id": session,
            "messages": [{"role": "user", "content": raw}], "infer": False, "metadata": metadata}))
        ids = [row.get("id") for row in self._rows(response) if isinstance(row, dict) and row.get("id")]
        if not ids and isinstance(response, dict) and response.get("id"): ids = [response["id"]]
        if not ids: raise Mem0Error("Mem0 未返回可核对的记忆编号，不能确认保存成功。")
        # Confirm the complete original and patient survived the round trip.
        stored = self._get(owner, ids[0])
        if not stored or stored["metadata"].get("original_content") != question:
            raise Mem0Error("Mem0 原文回读校验未通过，不能确认来源记录完整。")
        return ids[0]

    def cloud_list(self, owner, patient, include_inactive=True):
        results = []
        for page in range(1, 11):
            response = self._request("POST", "/v3/memories/", {"filters": {"user_id": self.namespace(owner, patient)}},
                                     params={"page": page, "page_size": 100})
            for row in self._rows(response):
                if self._owned(row, owner, patient) and (include_inactive or self._active(row["metadata"])):
                    results.append(self._public(row))
            if not isinstance(response, dict) or not response.get("next"): break
        return results

    def list(self, owner, include_inactive=False, scope="all"):
        if scope not in {"all", "self", "family"}: raise ValueError("Unknown memory scope")
        people = {"all": ("self", "father", "mother"), "self": ("self",), "family": ("father", "mother")}[scope]
        results = []
        for patient in people:
            results.extend(self.cloud_list(owner, patient, include_inactive))
        # Old local originals remain visible but are never silently uploaded.
        results.extend(dict(row, id="local:" + row["id"], backend="local_legacy")
                       for row in self.local.list(owner, include_inactive, scope))
        return sorted(results, key=lambda row: row["created"], reverse=True)[:100]

    def related(self, owner, session, question, patient):
        if patient not in {"self", "father", "mother"}: return []
        response = self._request("POST", "/v3/memories/search/", {
            "query": question, "filters": {"user_id": self.namespace(owner, patient)}, "top_k": 30})
        with self.local.connect() as db:
            if self.local.path is not None:
                db.execute("CREATE TABLE IF NOT EXISTS mem0_exclusions(owner TEXT, session TEXT, source_session TEXT, PRIMARY KEY(owner,session,source_session))")
            excluded = {row[0] for row in db.execute("SELECT source_session FROM mem0_exclusions WHERE owner=? AND session=?", (owner, session))}
        results, seen, checked_ids = [], set(), set()
        query_topics = set(topics(question))
        candidates = [dict(self._public(row),score=row.get('score')) for row in self._rows(response)
                      if self._owned(row,owner,patient)]
        # A saved turn in the current chat is still a valid source. Edits clear
        # prompt history, so excluding its session would discard the only copy.
        candidates.sort(key=lambda source: (source['session'] != session, not bool(source.get('edited_at'))))

        def collect(sources):
            for candidate in sources:
                if len(results) >= 3: break
                if candidate['id'] in checked_ids or candidate['session'] in excluded: continue
                # Cached search metadata can lag behind an edit. Always re-read
                # current-session/edited candidates before applying topic gates.
                if (not query_topics or (not query_topics.intersection(candidate['topics'])
                        and candidate['session'] != session and not candidate.get('edited_at'))): continue
                checked_ids.add(candidate['id'])
                current = self._get(owner,candidate['id'])
                if not current or not self._owned(current,owner,patient) or not self._active(current['metadata']): continue
                source = self._public(current)
                common = sorted(query_topics.intersection(source['topics']))
                if source['session'] in excluded or not common: continue
                fingerprint = (source['session'],source['content'])
                if fingerprint in seen: continue
                seen.add(fingerprint)
                source.update(reason=('参考你修改后的记忆，共同主题：' if source.get('edited_at') else 'Mem0 检索到相关记录，共同主题：') + '、'.join(common),
                              highlight_terms=sorted({alias for topic in common for alias in TOPICS[topic]}),
                              score=candidate.get('score'))
                results.append(source)

        collect(candidates)
        if not results and query_topics:
            # A just-edited record may not have reached the semantic index yet.
            # Recover only this owner/person's active, matching journal entries.
            fallback = self.cloud_list(owner,patient,include_inactive=False)
            fallback.sort(key=lambda source: (source['session'] == session,source.get('edited_at') or source['created']),reverse=True)
            collect(fallback)
        # Preserve access to old local memories, explicitly labelled as a separate source.
        for row in self.local.related(owner, session, question, patient):
            results.append(dict(row, id="local:" + row["id"], backend="local_legacy"))
        return results[:3]

    def update(self, owner, memory_id, content, observations, expected_revision):
        if memory_id.startswith("local:"):
            record = self.local.update(owner, memory_id[6:], content, observations, expected_revision)
            return dict(record, id=memory_id, backend="local_legacy") if record else None
        row = self._get(owner, memory_id)
        if row is None: return None
        if int(row["metadata"].get("revision",0)) != expected_revision:
            raise MemoryConflict("这条记忆已被修改，请重新打开最新记录后编辑。")
        metadata = dict(row["metadata"], original_content=content, observations=observations,
                        topics=topics(content+'\n'+observations), revision=expected_revision+1,
                        edited_at=datetime.now(timezone.utc).isoformat(), edited_by="user")
        raw = content + ("\n\n【图片客观读取，可能有误差】\n" + observations if observations else "")
        self._settled(self._request("PUT", f"/v1/memories/{memory_id}/", {"text":raw,"metadata":metadata}))
        confirmed = self._get(owner, memory_id)
        if (not confirmed or confirmed["memory"] != raw
                or confirmed["metadata"].get("original_content") != content
                or confirmed["metadata"].get("observations","") != observations
                or int(confirmed["metadata"].get("revision",0)) != expected_revision+1):
            raise Mem0Error("Mem0 覆盖写入尚未通过回读核验，请重新加载记录后确认。")
        return self._public(confirmed)

    def change(self, owner, memory_id, action, session=""):
        if action not in {"exclude", "retire", "delete"}: raise ValueError("Unknown memory action")
        if memory_id.startswith("local:"):
            return self.local.change(owner, memory_id[6:], action, session)
        row = self._get(owner, memory_id)
        if not row: return False
        if action == "exclude":
            with self.local.connect() as db:
                if self.local.path is not None:
                    db.execute("CREATE TABLE IF NOT EXISTS mem0_exclusions(owner TEXT, session TEXT, source_session TEXT, PRIMARY KEY(owner,session,source_session))")
                db.execute("INSERT OR IGNORE INTO mem0_exclusions VALUES(?,?,?)", (owner, session, row["metadata"]["session_id"]))
        elif action == "retire":
            metadata = dict(row["metadata"], active=False)
            self._settled(self._request("PUT", f"/v1/memories/{memory_id}/", {"text": row["memory"], "metadata": metadata}))
            confirmed = self._get(owner, memory_id)
            if not confirmed or self._active(confirmed["metadata"]):
                raise Mem0Error("Mem0 尚未确认停用，状态未标记为成功。")
        else:
            self._request("DELETE", f"/v1/memories/{memory_id}/")
            if self._get(owner, memory_id) is not None:
                raise Mem0Error("Mem0 尚未确认删除，状态未标记为成功。")
        return True
