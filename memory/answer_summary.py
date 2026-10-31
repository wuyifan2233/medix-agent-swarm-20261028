"""Bounded extractive summaries: never invent or paraphrase medical facts."""
import re


def summarize_answer(answer, max_chars=1000):
    text = re.sub(r'[*`#]+', '', answer or '').strip()
    units = [s.strip() for s in re.split(r'(?<=[。！？；])|\n+', text) if s.strip()]
    units = list(dict.fromkeys(units))
    if not units:
        return '本次未生成可用解读。'
    # Keep complete original sentences. Do not cut a date, value, negation or unit.
    eligible = [(i,s) for i,s in enumerate(units) if len(s) <= max_chars-80]
    if not eligible:
        return '原回答无法在摘要长度内可靠摘录，请查看聊天原文；此摘要不包含医学结论。'
    def score(item):
        i,s = item
        return (5 * bool(re.search(r'不确定|未确认|待核实|不能|无法|不代表|看不清|可能|需.*确认',s))
                + 4 * bool(re.search(r'建议|复查|就医|急诊|下一步',s))
                + 3 * bool(re.search(r'偏高|偏低|异常|\d{4}年|\d{4}-\d{2}|结论',s)) + (2 if i==0 else 0))
    selected=[];length=0
    count=min(6, max(1, (len(units)+1)//2))
    for i,s in sorted(eligible, key=lambda item:(-score(item),item[0])):
        if len(selected)>=count:break
        if length+len(s)+3 <= max_chars-80:
            selected.append((i,s));length+=len(s)+3
    selected.sort()
    return 'AI 分析摘要（非患者事实）：\n'+'\n'.join(s for _,s in selected)+'\n（摘录摘要，完整上下文及其余限制请查看原回答。）'
