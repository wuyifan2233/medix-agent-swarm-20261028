"""Small, explicit intent and applicability rules for this demo corpus."""
import re
import jieba

ALIASES={'扑热息痛':'对乙酰氨基酚','拉肚子':'腹泻','流行性感冒':'流感','血压高':'高血压','血糖高':'糖尿病'}
DRUGS=('对乙酰氨基酚','布洛芬','氯雷他定','口服补液盐','阿司匹林','阿莫西林')
TOPICS=DRUGS+('高血压','糖尿病','流感','感冒','鼻炎','哮喘','胃肠炎','腹泻','咳嗽','血压','血糖')

# Published registry terms keep medication boundaries in step with corpus growth.
def _registry_terms():
    import json
    from pathlib import Path
    docs=json.loads((Path(__file__).parent/'sources.json').read_text(encoding='utf8'))['documents']
    inventory_path=Path(__file__).parent/'coverage_inventory.json'
    inventory=json.loads(inventory_path.read_text(encoding='utf8')) if inventory_path.exists() else {}
    drugs=tuple(dict.fromkeys([d['title'] for d in docs if d.get('evidence_kind')=='drug_reference']+inventory.get('drugs',[])))
    generic={'饮食','运动','水果','血压计','测量','食盐','主食','鼻腔冲洗','健康科普','生活方式','全谷物','用药','治疗','症状'}
    topics=tuple(dict.fromkeys([t for d in docs for t in d.get('topics',[]) if t not in generic]+inventory.get('diseases',[])+list(drugs)))
    return drugs,topics

_drugs,_topics=_registry_terms()
DRUGS=tuple(dict.fromkeys(DRUGS+_drugs))
TOPICS=tuple(dict.fromkeys(TOPICS+_topics))


SLEEP_TERMS=('睡眠','睡不好','睡不着','失眠','入睡','早醒','夜醒')
NECK_TERMS=('肩颈','颈肩','颈部','颈椎','脖子','肩膀','肩部','肩周')
NECK_HABITS=('久坐','低头','姿势','坐姿','习惯','工位','电脑','工作','调整','放松','缓解')
NECK_ADVICE=('姿势','坐姿','久坐','低头','休息','锻炼','拉伸','预防','电脑','工作','枕头')
QUERY_FILLER={'怎么','怎样','如何','什么','哪些','为什么','可以','应该','需要','注意','日常','调整','习惯','情况','问题','最近','总是','感觉','不舒服','帮我','一下','一段','一个','推荐','建议','方法','快速','记录','观察','健康','身体','资料','内容','知识','还有','每天','是否','进行','现在','时候'}

def directly_relevant(query, row):
    title=row.get('metadata',{}).get('title','')
    content=row.get('content','')
    body=content.removeprefix(title).strip()
    # A title/credit alone does not supply supporting evidence.
    if not body or re.fullmatch(r'(?:审核|作者|来源|编辑|审校)[：:].*',body):
        return False
    if any(term in query for term in SLEEP_TERMS):
        return any(term in title for term in SLEEP_TERMS) and any(term in body for term in SLEEP_TERMS)
    if any(term in query for term in NECK_TERMS):
        if not any(term in title or term in body for term in NECK_TERMS):
            return False
        if any(term in query for term in NECK_HABITS):
            trauma=('损伤','外伤','骨折','急救','受伤')
            if any(term in title for term in trauma) and not any(term in query for term in trauma):
                return False
            if not any(term in body for term in NECK_ADVICE):
                return False
        return True
    # Known disease names must be central to the source, not incidental body tags.
    subjects={term for term in TOPICS if len(term)>=2 and term not in QUERY_FILLER
              and term not in ('饮食','运动','水果','测量','主食','食盐','用药','症状','治疗') and term in query}
    if subjects:
        return any(term in title for term in subjects)
    # For unregistered wording, check actual candidate text after dense recall.
    # No fixed corpus topic is required; generic request words are not evidence.
    anchors={term.lower() for term in jieba.cut(query) if len(term)>=2
             and term not in QUERY_FILLER and not term.isdigit()}
    return bool(anchors) and any(term in (title+' '+body).lower() for term in anchors)


def normalize_query(query):
    for old,new in ALIASES.items():query=query.replace(old,new)
    return query.strip()


def contextualize_query(query,history):
    """Only inherit a user's explicit topic for an elliptical follow-up."""
    query=normalize_query(query)
    if any(t in query for t in (*TOPICS,*SLEEP_TERMS,*NECK_TERMS)):return query,False
    if re.match(r'^(那|那么|这个|这种|它|还有|应该|需要|要注意|怎么|可以|能不能|为什么)',query) and len(query)<100:
        for message in reversed(history[-6:]):
            if message.get('role')!='user':continue
            previous=normalize_query(message.get('content',''))[:300]
            if any(t in previous for t in TOPICS):return previous+'；追问：'+query,True
    return query,False


def insufficient_medication(query):
    query=normalize_query(query)
    drug=any(t in query for t in DRUGS) or bool(re.search(r'药|胶囊|口服液|片剂',query))
    if not drug:return False
    action=bool(re.search(r'吃几|吃多少|用多少|多少毫[克升]|几毫[克升]|加量|停药|换药|能吃吗|能不能吃|可以吃吗|一起吃|混着吃|一起服|联合用|合用|联用',query))
    personal=bool(re.search(r'我|孩子|宝宝|孕|肾功能|肝功能|老人|岁',query))
    taken=bool(re.search(r'吃了|服了|误服|过量|吃过',query))
    return action or (personal and taken) or (personal and '剂量' in query)


def requested_audience(query):
    if re.search(r'孕|哺乳',query):return 'pregnancy_lactation'
    if re.search(r'儿童|小孩|孩子|宝宝|婴儿|幼儿',query):return 'children'
    if re.search(r'老人|老年',query):return 'older_adults'
    if re.search(r'成人|成年人',query):return 'adults'
    return 'unspecified'


def applicability(metadata,audience):
    populations=metadata.get('audiences',['unspecified'])
    if 'general' in populations:return 'general'
    if audience=='unspecified':return 'needs_confirmation'
    if audience in populations:return 'matched'
    if 'unspecified' in populations:return 'needs_confirmation'
    if audience=='adults' and 'older_adults' in populations:return 'needs_confirmation'
    return 'mismatch'


def knowledge_gap(query,documents):
    drugs=[d for d in DRUGS if d in query]
    detail=bool(re.search(r'禁忌|相互作用|说明书|规格|剂型|不良反应',query))
    if drugs and detail and not any(d['metadata'].get('evidence_kind')=='product_label' for d in documents):
        return {'kind':'missing_product_label','missing':'具体制剂的核准说明书',
                'message':'当前有相关科普或专业平台药物资料，未收录该药具体制剂的核准说明书，不能据此完整回答说明书级问题。',
                'suggested_inputs':['药品通用名','剂型与规格','对应的核准说明书']}
    if '水果' in query:
        topics=[t for t in TOPICS if t in query]
        relevant=[d for d in documents if any(t in d['metadata'].get('topics',[]) for t in topics)]
        if relevant and not any('水果' in d.get('content','') for d in relevant):
            return {'kind':'missing_subtopic','missing':'该疾病的水果或饮食专题资料','message':'当前相关资料没有覆盖水果问题，不能用其他主题的片段代替饮食依据。','suggested_inputs':['该疾病的饮食管理原始资料']}
    return None


def evidence_links(answer,sources):
    """Expose links without equating citation validity with clinical support."""
    links=[]
    sentences=[s for block in answer.splitlines() for s in re.findall(r'.+?(?:[。！？](?:\s*\[\d+\])*|$)',block)]
    for sentence in sentences:
        ids=list(dict.fromkeys(int(n) for n in re.findall(r'\[(\d+)\]',sentence)))
        if not ids:
            if len(sentence.strip())>=8:links.append({'text':sentence.strip(),'citations':[],'status':'uncited','quotes':[]})
            continue
        text=re.sub(r'\[\d+\]','',sentence).strip()
        linked=[s for s in sources if s['citation'] in ids]
        if not linked:continue
        exact=[{'citation':s['citation'],'quote':text} for s in linked if len(text)>=8 and text in s['content']]
        links.append({'text':sentence.strip(),'citations':[s['citation'] for s in linked],
                      'status':'verbatim_match' if exact else 'needs_review','quotes':exact})
    return links
