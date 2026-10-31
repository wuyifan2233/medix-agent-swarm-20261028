"""Opt-in local source journal. Store observations, never assistant diagnoses."""
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

TOPICS = {
    "感冒": ("感冒", "伤风", "流鼻涕", "鼻塞", "打喷嚏", "咽痛", "喉咙痛"),
    "头晕": ("头晕", "眩晕"), "头痛": ("头痛", "头疼"), "血压": ("血压", "降压"),
    "血糖": ("血糖", "糖尿病"), "咳嗽": ("咳嗽", "干咳"), "发热": ("发热", "发烧", "体温"),
    "睡眠": ("睡不", "失眠", "睡眠", "早醒"), "腹痛": ("腹痛", "肚子痛", "肚子疼"),
    "胸部不适": ("胸痛", "胸闷"), "心悸": ("心悸", "心慌"), "恶心": ("恶心", "呕吐"),
    "过敏": ("过敏",), "肾功能": ("肌酐", "肾功能"), "血脂": ("血脂", "胆固醇"),
    "肩颈": ("肩颈", "颈痛", "颈椎"), "腰痛": ("腰痛", "腰疼"),
    "腹泻": ("腹泻", "拉肚子"), "皮疹": ("皮疹", "起疹"), "乏力": ("乏力", "疲劳"),
}
PATIENTS = {"self": "本人", "father": "父亲", "mother": "母亲", "other": "其他人"}


def topics(text):
    return sorted(key for key, aliases in TOPICS.items() if any(a in text for a in aliases))


def patient_for(text, selected="self"):
    # Multiple/unspecified third parties cannot safely share a persistent profile.
    father = bool(re.search(r"父亲|爸爸|我爸", text))
    mother = bool(re.search(r"母亲|妈妈|我妈", text))
    if (father and mother) or ((father or mother) and re.search(r"我也|我自己|本人", text)):
        return "other"
    if father: return "father"
    if mother: return "mother"
    if re.search(r"朋友|妻子|丈夫|孩子|女儿|儿子|同事|患者|病例|案例|他|她", text):
        return "other"
    return selected if selected in PATIENTS else "other"


class MemoryConflict(ValueError):
    """The editor is based on an older version of this source."""


class CaseMemory:
    def __init__(self, path=None, demo=False):
        self.path = Path(path) if path else None
        self.demo = demo

    def connect(self):
        from storage.business import connect
        prefix = 'demo_memory_' if self.demo else 'memory_'
        connection = connect(tables={name:prefix+name for name in ('cases','exclusions','demo_seeds','case_edits')}, test_path=self.path)
        if self.path is not None:
            connection.execute("""CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, session TEXT NOT NULL,
                patient TEXT NOT NULL, content TEXT NOT NULL, observations TEXT NOT NULL,
                topics TEXT NOT NULL, created TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS exclusions (
                owner TEXT NOT NULL, session TEXT NOT NULL, memory_id TEXT NOT NULL,
                PRIMARY KEY(owner, session, memory_id))""")
            connection.execute("CREATE TABLE IF NOT EXISTS demo_seeds (owner TEXT PRIMARY KEY)")
            connection.execute("CREATE TABLE IF NOT EXISTS case_edits(id TEXT PRIMARY KEY, owner TEXT NOT NULL, edited_at TEXT, revision INTEGER NOT NULL)")
        return connection

    def save(self, owner, session, question, patient="self", observations="", created=None):
        # General advice and unidentified people are not personal clinical facts.
        tags = topics(question + "\n" + observations)
        if patient == "other" or not tags or not (observations or re.search(r"我|最近|今天|昨日|昨天|这几天|持续|出现|测得|检查结果", question)):
            return None
        entry = dict(id=uuid.uuid4().hex, owner=owner, session=session, patient=patient,
                     content=question, observations=observations, topics=json.dumps(tags, ensure_ascii=False),
                     created=created or datetime.now(timezone.utc).isoformat())
        with self.connect() as db:
            db.execute("""INSERT INTO cases(id,owner,session,patient,content,observations,topics,created)
                VALUES(:id,:owner,:session,:patient,:content,:observations,:topics,:created)""", entry)
        return entry["id"]

    def list(self, owner, include_inactive=False, scope="all"):
        if scope not in {"all", "self", "family"}:
            raise ValueError("Unknown memory scope")
        patient_filter = {"all": "", "self": "AND patient='self' ", "family": "AND patient IN ('father','mother') "}[scope]
        with self.connect() as db:
            rows = db.execute("SELECT cases.*, case_edits.edited_at, COALESCE(case_edits.revision,0) AS revision FROM cases LEFT JOIN case_edits ON cases.id=case_edits.id AND cases.owner=case_edits.owner WHERE cases.owner=? " + ("" if include_inactive else "AND active=1 ") + patient_filter + "ORDER BY created DESC LIMIT 100", (owner,)).fetchall()
        return [self.public(row) for row in rows]

    @staticmethod
    def public(row):
        result = {key: (json.loads(row[key]) if key == "topics" else row[key])
                  for key in ("id", "session", "patient", "content", "observations", "topics", "created", "active")}
        result.update(revision=row["revision"] if "revision" in row.keys() else 0,
                      edited_at=row["edited_at"] if "edited_at" in row.keys() else None)
        return result

    def update(self, owner, memory_id, content, observations, expected_revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT cases.*, case_edits.edited_at, COALESCE(case_edits.revision,0) AS revision FROM cases LEFT JOIN case_edits ON cases.id=case_edits.id AND cases.owner=case_edits.owner WHERE cases.id=? AND cases.owner=?", (memory_id, owner)).fetchone()
            if row is None: return None
            if row["revision"] != expected_revision:
                raise MemoryConflict("这条记忆已被修改，请重新打开最新记录后编辑。")
            edited_at = datetime.now(timezone.utc).isoformat()
            db.execute("UPDATE cases SET content=?, observations=?, topics=? WHERE id=? AND owner=?",
                       (content, observations, json.dumps(topics(content+'\n'+observations), ensure_ascii=False), memory_id, owner))
            db.execute("INSERT OR REPLACE INTO case_edits VALUES(?,?,?,?)", (memory_id, owner, edited_at, expected_revision+1))
            record = self.public(row)
            record.update(content=content, observations=observations, topics=topics(content+'\n'+observations), edited_at=edited_at, revision=expected_revision+1)
            return record

    def related(self, owner, session, question, patient):
        if patient == "other": return []
        tags = set(topics(question))
        if not tags: return []
        with self.connect() as db:
            excluded = {row[0] for row in db.execute("SELECT c.session FROM exclusions e JOIN cases c ON c.id=e.memory_id AND c.owner=e.owner WHERE e.owner=? AND e.session=?", (owner, session))}
        matches = []
        seen = set()
        for row in self.list(owner):
            common = sorted(tags.intersection(row["topics"]))
            if row["patient"] != patient or row["session"] in excluded or not common:
                continue
            fingerprint = (row["session"], row["content"])
            if fingerprint in seen: continue
            seen.add(fingerprint)
            row["highlight_terms"] = sorted({alias for topic in common for alias in TOPICS[topic]})
            row["reason"] = "本次与历史记录都提到：" + "、".join(common)
            matches.append(row)
        # Preserve repeated observations across dates; they are not duplicates.
        return matches[:3]

    def seed_demo(self, owner, created):
        with self.connect() as db:
            cursor = db.execute("INSERT OR IGNORE INTO demo_seeds VALUES(?)", (owner,))
            first = cursor.rowcount == 1
        if first and not self.list(owner, include_inactive=True):
            self.save(owner, "synthetic-previous-session", "最近三天晚上头晕，准备记录出现的时间。", "self", created=created)

    def change(self, owner, memory_id, action, session=""):
        with self.connect() as db:
            exists = db.execute("SELECT 1 FROM cases WHERE id=? AND owner=?" + ("" if action == "delete" else " AND active=1"), (memory_id, owner)).fetchone()
            if not exists: return False
            if action == "exclude":
                db.execute("INSERT OR IGNORE INTO exclusions VALUES(?,?,?)", (owner, session, memory_id))
            elif action == "delete":
                db.execute("DELETE FROM cases WHERE id=? AND owner=?", (memory_id, owner))
                db.execute("DELETE FROM case_edits WHERE id=? AND owner=?", (memory_id, owner))
                db.execute("DELETE FROM exclusions WHERE owner=? AND memory_id=?", (owner, memory_id))
            elif action == "retire":
                db.execute("UPDATE cases SET active=0 WHERE id=? AND owner=?", (memory_id, owner))
            else: raise ValueError("Unknown memory action")
        return True


def memory_context(rows):
    return [{"reference": f"M{i}", "citation": f"[M{i}]", **row} for i, row in enumerate(rows, 1)]


def referenced(answer, rows):
    used = [row for row in rows if f"[{row['reference']}]" in answer]
    # Never render an unverified source marker.
    clean = re.sub(r"\[M\d+\]", "", answer)
    clean = re.sub(r"[ \t]+([。，；！？])", r"\1", clean)
    return clean, used
