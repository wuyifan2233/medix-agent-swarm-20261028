"""Versioned local case facts, separate from chat history and medical guidelines."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid
from web.report_identity import item_key, dates_in, normalized

DB_PATH = None  # Explicit path overrides are used only by standalone synthetic tests.
TABLES = {name: "report_" + name for name in ("cases", "bindings", "facts", "versions", "turns", "analyses")}
FACT_FIELDS = ("name", "value", "unit", "reference", "method", "date", "conditions", "certainty", "report_id")


@contextmanager
def database():
    from storage.business import connect
    db = connect(tables=TABLES, test_path=DB_PATH)
    try:
        if DB_PATH is not None:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,owner TEXT NOT NULL,name TEXT NOT NULL,created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bindings(owner TEXT,chat_id TEXT,case_id TEXT,PRIMARY KEY(owner,chat_id));
            CREATE TABLE IF NOT EXISTS facts(id TEXT PRIMARY KEY,owner TEXT NOT NULL,case_id TEXT NOT NULL,revision INTEGER NOT NULL,
              data TEXT NOT NULL,source TEXT NOT NULL,quote TEXT NOT NULL,updated TEXT NOT NULL,dirty INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS versions(fact_id TEXT,revision INTEGER,data TEXT,source TEXT,quote TEXT,created TEXT,
              PRIMARY KEY(fact_id,revision));
            CREATE TABLE IF NOT EXISTS turns(owner TEXT,request_id TEXT,case_id TEXT,outcome TEXT,PRIMARY KEY(owner,request_id));
            CREATE TABLE IF NOT EXISTS analyses(id TEXT PRIMARY KEY,owner TEXT,case_id TEXT,refs TEXT,answer TEXT,created TEXT);
            CREATE INDEX IF NOT EXISTS facts_case ON facts(owner,case_id);
            """)
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def now():
    return datetime.now(timezone.utc).isoformat()


def text(value, max_length=400):
    if value is None:
        return ""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError("病例字段格式不正确。")
    value = str(value).strip()
    if len(value) > max_length:
        raise ValueError("病例字段过长。")
    return value


def clean_fact(raw):
    if not isinstance(raw, dict):
        raise ValueError("病例字段格式不正确。")
    data = {key: text(raw.get(key)) for key in FACT_FIELDS}
    if not data["name"] or not data["value"]:
        raise ValueError("病例项目与结果不能为空。")
    data["certainty"] = "uncertain" if data["certainty"] == "uncertain" else "clear"
    if data["date"]:
        try:
            data["date"] = datetime.strptime(data["date"], "%Y-%m-%d").date().isoformat()
        except ValueError:
            data["date"] = ""
    return data


def normalized_evidence(value):
    return re.sub(r"[^\w.]+", "", str(value)).replace("_", "").lower()


def source_anchor(quote, raw, source, evidence):
    """Ignore formatting without associating a result with a different table row."""
    name, value = str(raw.get("name", "")), str(raw.get("value", ""))
    if source == "image" and name and value:
        chinese = "".join(re.findall(r"[\u4e00-\u9fff]+", name))
        names = [normalized_evidence(name)]
        if len(chinese) >= 2:
            names.append(normalized_evidence(chinese))
        for line in evidence.splitlines():
            if not any(candidate and candidate in normalized_evidence(line) for candidate in names):
                continue
            present = bool(re.search(r"(?<![\d.])" + re.escape(value) + r"(?![\d.])", line)) if re.fullmatch(NUMBER, value) else value in line
            if present:
                return line
    clean_quote = normalized_evidence(quote)
    if clean_quote and clean_quote in normalized_evidence(evidence):
        return quote
    return ""


def anchored_metadata(raw, evidence, before=None, date_evidence=None):
    """Do not turn model-supplied common ranges/methods into patient facts."""
    before = before or {}
    result = dict(raw)
    def normalized(value):
        return re.sub(r"\s+", "", str(value)).replace("–", "-").replace("—", "-").replace("～", "-").replace("~", "-").replace("μ", "u").replace("µ", "u").lower()
    original = normalized(evidence)
    for key in ("unit", "reference", "method", "conditions"):
        value = result.get(key)
        if value and value != before.get(key) and normalized(value) not in original:
            result[key] = before.get(key, "")
    value = result.get("date")
    if value and value != before.get("date"):
        evidence = date_evidence if date_evidence is not None else evidence
        dates = set(re.findall(r"\d{4}-\d{2}-\d{2}", evidence))
        for year, month, day in re.findall(r"(\d{4})[年/.-](\d{1,2})[月/.-](\d{1,2})", evidence):
            dates.add(f"{year}-{int(month):02}-{int(day):02}")
        today = datetime.now(timezone.utc).date()
        if "今天" in evidence:
            dates.add(today.isoformat())
        if "昨天" in evidence:
            dates.add((today-timedelta(days=1)).isoformat())
        if value not in dates:
            result["date"] = before.get("date", "")
    return result


def decode(row):
    result = dict(row)
    result["data"] = json.loads(result["data"])
    return result


def list_cases(owner):
    with database() as db:
        cases = [dict(row) for row in db.execute(
            "SELECT c.id,c.name,c.created,(SELECT count(*) FROM facts f WHERE f.case_id=c.id AND f.owner=c.owner) AS records "
            "FROM cases c WHERE owner=? ORDER BY created DESC LIMIT 100", (owner,))]
        for case in cases:
            facts = [json.loads(row['data']) for row in db.execute(
                'SELECT data FROM facts WHERE owner=? AND case_id=? ORDER BY updated DESC', (owner, case['id']))]
            case['name'] = case_title(facts)
        return cases


def case_title(facts):
    """Use recorded diagnoses only; lab abnormalities never invent a disease label."""
    diagnoses = [fact['value'] for fact in facts if fact.get('name') in {'既往诊断', '明确诊断', '医生诊断', '既往疾病'}
                 and fact.get('certainty') == 'clear' and fact.get('value')]
    if diagnoses:
        title = '、'.join(dict.fromkeys(diagnoses))[:40]
    else:
        names = ' '.join(fact.get('name', '') for fact in facts)
        groups = [('肝胆功能', ('胆红素', '转氨酶', 'TBIL', 'ALT')),
                  ('肾功能', ('肌酐', '尿素', '尿酸', 'CysC')),
                  ('血脂', ('胆固醇', '甘油三酯', '脂蛋白')),
                  ('血糖', ('葡萄糖', '血糖')), ('血压', ('收缩压', '舒张压', '血压'))]
        topics = [label for label, words in groups if any(word in names for word in words)]
        title = '、'.join(topics[:3]) + '记录' if topics else (facts[0].get('name', '健康咨询')[:24] + '记录' if facts else '待补充资料的病例')
    dates = sorted({fact.get('date', '') for fact in facts} - {''})
    return title + (' · ' + dates[-1] if dates else ' · 检查日期待补充')


def require_case(owner, case_id):
    with database() as db:
        row = db.execute("SELECT id,name,created FROM cases WHERE id=? AND owner=?", (case_id, owner)).fetchone()
        if row is None:
            raise LookupError("当前浏览器无法访问此病例，请重新选择。")
        return dict(row)


def bound_case(owner, chat_id, selected=""):
    if selected:
        return require_case(owner, selected)["id"]
    with database() as db:
        row = db.execute("SELECT case_id FROM bindings WHERE owner=? AND chat_id=?", (owner, chat_id)).fetchone()
        return row["case_id"] if row else ""


def fact_pages(owner, case_id, page_size=200):
    """Read every current record in stable pages; callers still check case ownership."""
    if not case_id:
        return
    require_case(owner, case_id)
    with database() as db:
        cursor = db.execute("SELECT * FROM facts WHERE owner=? AND case_id=? ORDER BY updated DESC,id", (owner, case_id))
        while True:
            rows = cursor.fetchmany(page_size)
            if not rows:
                break
            yield [decode(row) for row in rows]


def current_facts(owner, case_id, limit=None):
    if not case_id:
        return []
    rows = []
    for page in fact_pages(owner, case_id):
        rows.extend(page)
        if limit is not None and len(rows) >= limit:
            return rows[:limit]
    return rows


def related_facts(facts, query, limit=64):
    """Deterministic SQLite fallback; prefer named projects and requested dates."""
    aliases = (("血糖", "葡萄糖", "GLU"), ("肌酐", "CR"), ("尿酸", "UA"),
               ("总胆红素", "TBIL"), ("直接胆红素", "DBIL"))
    query_key = normalized_evidence(query)
    dates = dates_in(query)
    def score(fact):
        data = fact["data"]
        name = item_key(data["name"])
        matched = bool(name and name in query_key)
        matched |= any(any(normalized_evidence(alias) in query_key for alias in group)
                       and any(item_key(alias) == name for alias in group) for group in aliases)
        date_match = bool(data["date"] and data["date"] in dates)
        return int(matched) * 8 + int(date_match) * 4
    ranked = sorted(facts, key=score, reverse=True)  # preserves recent-first ordering for ties
    relevant = [fact for fact in ranked if score(fact)]
    return (relevant or ranked)[:limit]


def previous_turn(owner, request_id):
    with database() as db:
        row = db.execute("SELECT outcome FROM turns WHERE owner=? AND request_id=?", (owner, request_id)).fetchone()
        return json.loads(row["outcome"]) if row else None


def apply_changes(owner, chat_id, selected, request_id, proposal, message, observed):
    """Atomic edits + revision audit. An extractor proposal never grants data access."""
    old_turn = previous_turn(owner, request_id)
    if old_turn:
        return old_turn
    case_id = bound_case(owner, chat_id, selected)
    operations = proposal.get("operations", [])
    if not isinstance(operations, list) or len(operations) > 2000:
        raise ValueError("本次病例记录过多，请拆分资料。")
    questions = [text(value) for value in proposal.get("questions", [])[:3]]
    # Switches start a fresh case; no operation may correct the previous patient.
    switching = proposal.get("new_patient") is True
    if switching:
        case_id = ""
    changes = []
    with database() as db:
        if db.execute("SELECT 1 FROM turns WHERE owner=? AND request_id=?", (owner, request_id)).fetchone():
            return previous_turn(owner, request_id)
        if switching:
            case_id = uuid.uuid4().hex
            db.execute("INSERT INTO cases VALUES (?,?,?,?)", (case_id, owner, "新病例 " + now()[:16].replace("T", " ") + " UTC", now()))
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            action = operation.get("action")
            quote = text(operation.get("quote"), 1000)
            source = operation.get("source")
            evidence = observed if source == "image" else message if source == "user" else ""
            raw = operation.get("fact", {})
            if not isinstance(raw, dict):
                continue
            anchor = source_anchor(quote, raw, source, evidence) if quote else ""
            if not anchor:
                questions.append("有一条病例信息的来源无法核实，请补充原文或清晰图片。")
                continue
            quote = anchor
            if source == "image" and not result_cell_matches(raw, anchor):
                questions.append("有一项图片结果与结果列不一致，未入库；请提供该项目的清晰图片。")
                continue
            if action in {"correct", "supplement"}:
                target = db.execute("SELECT * FROM facts WHERE id=? AND owner=? AND case_id=?",
                                    (operation.get("target_id", ""), owner, case_id)).fetchone()
                if target is None or target["revision"] != operation.get("expected_revision"):
                    questions.append("需要确认你要修改的是哪一次记录，请补充项目或检查日期。")
                    continue
                before = json.loads(target["data"])
                merged = {**before, **{key: value for key, value in raw.items() if key in FACT_FIELDS and value not in (None, "")}}
                # A correction to a value must be anchored in the human's own statement.
                if merged.get("value") != before["value"] and (source != "user" or str(merged["value"]) not in message):
                    questions.append("更正值尚未在你的文字中明确，请说明正确数值。")
                    continue
                if action == "supplement" and merged.get("value") != before["value"]:
                    questions.append("补充条件不能覆盖检查结果，请说明是更正旧值还是新增测量。")
                    continue
                if merged.get("unit") != before["unit"] and not raw.get("reference"):
                    merged["reference"] = ""
                data = clean_fact(anchored_metadata(merged, evidence, before))
                fact_id, revision = target["id"], target["revision"] + 1
                if data == before:
                    continue
            elif action == "add":
                data = clean_fact(anchored_metadata(raw, anchor if source == "image" else evidence, date_evidence=evidence))
                if data["value"] not in evidence:
                    questions.append("有一项结果缺少明确原文，请补充该项目的实际结果。")
                    continue
                # Re-uploading exactly the same known observation does not create duplicates.
                duplicate = db.execute("SELECT 1 FROM facts WHERE owner=? AND case_id=? AND data=?",
                                       (owner, case_id, json.dumps(data, ensure_ascii=False))).fetchone()
                if source == "image" and data.get("report_id"):
                    existing = db.execute("SELECT data,revision FROM facts WHERE owner=? AND case_id=?", (owner,case_id)).fetchall()
                    duplicate = duplicate or any(
                        json.loads(r["data"]).get("report_id") == data["report_id"]
                        and item_key(json.loads(r["data"])["name"]) == item_key(data["name"])
                        and (r["revision"] > 1 or normalized(json.loads(r["data"])["value"]) == normalized(data["value"]))
                        for r in existing)
                if duplicate and source == "image":
                    continue
                fact_id, revision = uuid.uuid4().hex, 1
            else:
                continue
            if not case_id:
                case_id = uuid.uuid4().hex
                db.execute("INSERT INTO cases VALUES (?,?,?,?)", (case_id, owner, "病例 " + now()[:16].replace("T", " ") + " UTC", now()))
            stamp = now()
            encoded = json.dumps(data, ensure_ascii=False)
            db.execute("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET "
                       "revision=excluded.revision,data=excluded.data,source=excluded.source,quote=excluded.quote,updated=excluded.updated,dirty=1",
                       (fact_id, owner, case_id, revision, encoded, source, quote, stamp))
            db.execute("INSERT INTO versions VALUES (?,?,?,?,?,?)", (fact_id, revision, encoded, source, quote, stamp))
            changes.append({"id": fact_id, "revision": revision, "action": action, "name": data["name"]})
        if case_id:
            db.execute("INSERT INTO bindings VALUES (?,?,?) ON CONFLICT(owner,chat_id) DO UPDATE SET case_id=excluded.case_id", (owner, chat_id, case_id))
        outcome = {"case_id": case_id, "changes": changes, "questions": list(dict.fromkeys(questions))[:3], "switched": switching}
        db.execute("INSERT INTO turns VALUES (?,?,?,?)", (owner, request_id, case_id, json.dumps(outcome, ensure_ascii=False)))
    return outcome


def mark_indexed(fact):
    with database() as db:
        db.execute("UPDATE facts SET dirty=0 WHERE id=? AND owner=? AND revision=?", (fact["id"], fact["owner"], fact["revision"]))


def save_analysis(owner, case_id, answer, facts):
    if not case_id:
        return
    refs = [{"id": fact["id"], "revision": fact["revision"]} for fact in facts]
    with database() as db:
        db.execute("INSERT INTO analyses VALUES (?,?,?,?,?,?)", (uuid.uuid4().hex, owner, case_id, json.dumps(refs), answer, now()))


def analysis_is_stale(owner, analysis_id):
    with database() as db:
        row = db.execute("SELECT refs FROM analyses WHERE id=? AND owner=?", (analysis_id, owner)).fetchone()
        if row is None:
            raise LookupError("未找到分析。")
        for ref in json.loads(row["refs"]):
            current = db.execute("SELECT revision FROM facts WHERE id=? AND owner=?", (ref["id"], owner)).fetchone()
            if current is None or current["revision"] != ref["revision"]:
                return True
    return False


NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"


def result_cell_matches(raw, line):
    """A reference-bound number appearing on the same row is not result evidence."""
    value = str(raw.get("value", ""))
    if not re.fullmatch(NUMBER, value):
        return bool(value and value in line)
    # New transcription uses an explicit result column. Accept legacy OCR conservatively.
    if "【结果】" in line:
        cell = line.split("【结果】", 1)[1].split("【单位】", 1)[0].strip()
        return cell == value
    prefix = re.split(r"参考|\(|（|\[|【参考", line, maxsplit=1)[0]
    name = str(raw.get("name", ""))
    candidates = [name, "".join(re.findall(r"[\u4e00-\u9fff]+", name))]
    for candidate in candidates:
        if candidate and candidate in prefix:
            prefix = prefix.split(candidate, 1)[1]
            break
    else:
        return False
    numbers = re.findall(NUMBER, prefix)
    return bool(numbers and numbers[0] == value)


def numeric(value):
    if not re.fullmatch(NUMBER, value):
        return None
    try:
        number = Decimal(value)
        return number if number.is_finite() else None
    except InvalidOperation:
        return None


def range_check(fact):
    data = fact["data"]
    value = numeric(data["value"])
    reference = data["reference"].replace("～", "-").replace("–", "-").replace("—", "-")
    match = re.fullmatch(rf"\s*({NUMBER})\s*[-~至]\s*({NUMBER})\s*", reference)
    if value is None or not data["unit"] or data["certainty"] != "clear" or not match:
        return "参考范围、单位或结果不足，不自动判定"
    low, high = map(Decimal, match.groups())
    if low > high:
        return "参考范围待核实"
    return "低于单据范围" if value < low else "高于单据范围" if value > high else "单据范围内"


def trends(facts):
    output = []
    groups = {}
    for fact in facts:
        groups.setdefault(fact["data"]["name"], []).append(fact)
    for name, group in groups.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda fact: (fact["data"]["date"], fact["updated"]))
        before, after = group[-2:]
        a, b = before["data"], after["data"]
        comparable = bool(a["date"] and b["date"] and a["date"] < b["date"]
                          and a["certainty"] == b["certainty"] == "clear"
                          and all(a[key] and a[key] == b[key] for key in ("unit", "method", "reference", "conditions"))
                          and numeric(a["value"]) is not None and numeric(b["value"]) is not None)
        output.append({"name": name, "before": a, "after": b, "comparable": comparable,
                       "delta": str(numeric(b["value"]) - numeric(a["value"])) if comparable else None,
                       "note": "仅数值变化，不代表整体健康改善" if comparable else "日期、单位、方法、参考范围或测量条件不一致／缺失，仅并列展示"})
    return output
