"""Conservative, shared normalization of report cells and explicit dates."""
import re
import unicodedata
from datetime import date

def normalized(value):
    value=unicodedata.normalize('NFKC',str(value)).lower()
    return re.sub(r'\s+','',value).replace('～','~').replace('–','~').replace('−','-').replace('μ','u').replace('µ','u')

def item_key(name):
    # Strip a separated Latin laboratory code only when a Chinese label follows.
    name=re.sub(r'^[A-Za-z][A-Za-z0-9_-]*\s+(?=[\u4e00-\u9fffγ])','',name.strip())
    key=normalized(name)
    aliases={'ua':'尿酸','glu':'血糖','葡萄糖':'血糖','空腹血糖':'血糖','cr':'肌酐','tbil':'总胆红素','dbil':'直接胆红素'}
    return aliases.get(key,key)

def dates_in(text):
    found=set()
    for y,m,d in re.findall(r'(\d{4})[年/.-](\d{1,2})[月/.-](\d{1,2})(?:日)?',text):
        try:found.add(date(int(y),int(m),int(d)).isoformat())
        except ValueError:pass
    return found

def unique_date(text):
    dates=dates_in(text)
    return next(iter(dates)) if len(dates)==1 else ''

def deduplicate(rows):
    groups={}
    for row in rows:groups.setdefault(item_key(row['name']),[]).append(row)
    accepted=[]; conflicts=[]
    for key,items in groups.items():
        if len({normalized(r['result']) for r in items})>1:
            conflicts.append(key);continue
        merged=dict(max(items,key=lambda r:sum(bool(r.get(k)) for k in ('unit','reference'))))
        for field in ('unit','reference'):
            values={normalized(r[field]) for r in items if r.get(field)}
            if len(values)>1:conflicts.append(key);break
        else:accepted.append(merged)
    return accepted,conflicts

def report_rows(observed):
    for group in re.split(r'(?=【图片 \d+】)',observed):
        marker=re.search(r'【报告标识 ([a-f0-9]{64})】',group)
        if not marker:continue
        metadata='\n'.join(l for l in group.splitlines() if '【结果】' not in l)
        for line in group.splitlines():
            match=re.fullmatch(r'(.*?)【结果】(.*?)【单位】(.*?)【参考】(.*)',line)
            if match:
                name,value,unit,reference=match.groups()
                yield line,dict(name=name,value=value,unit=unit,reference=reference,date=unique_date(metadata),report_id=marker[1])
