"""Source registry, reproducible local snapshots and tokenizer-aware chunks."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / 'sources.json'
LOCAL = ROOT / '.local'
CHUNK_VERSION = 'heading-token384-overlap48-v1'


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def load_corpus():
    manifest = json.loads((LOCAL / 'manifest.json').read_text(encoding='utf-8'))
    generation=manifest.get('generation')
    if generation and not re.fullmatch(r'[a-f0-9]{16}',generation):raise ValueError('Invalid corpus generation')
    content_root=LOCAL/'generations'/generation if generation else LOCAL
    registry = json.loads(REGISTRY.read_text(encoding='utf-8'))['documents']
    labels=json.loads((ROOT/'applicability.json').read_text(encoding='utf-8'))['documents']
    expected = {d['id']: d for d in registry}
    if {d['id'] for d in manifest['documents']} != set(expected):
        raise ValueError('Local corpus does not match source registry; fetch sources again')
    docs = []
    for metadata in manifest['documents']:
        source = expected[metadata['id']]
        if any(metadata.get(k) != source.get(k) for k in source):
            raise ValueError('Source registry changed; fetch sources again')
        text = (content_root / 'documents' / (metadata['id'] + '.md')).read_text(encoding='utf-8')
        if digest(text) != metadata['content_sha256']:
            raise ValueError('Snapshot hash mismatch: ' + metadata['id'])
        docs.append({'id': metadata['id'], 'content': text, 'metadata': {**metadata,**labels.get(metadata['id'],{})}})
    return docs


def chunk_document(doc, tokenizer, max_tokens=384, overlap=48):
    if max_tokens < 32 or not 0 <= overlap < max_tokens // 2:
        raise ValueError('Invalid chunk budget')
    title = doc['metadata']['title']
    text = doc['content']
    heading = title
    chunks, pending, start_offset = [], [], 0

    def emit(parts, section, start):
        body = '\n\n'.join(parts)
        if not body.strip():
            return
        content = title + ('\n' + section if section != title else '') + '\n\n' + body
        if len(tokenizer.encode(content, add_special_tokens=True)) > max_tokens:
            raise ValueError('Chunk exceeds budget')
        cid = digest(doc['id'] + '\n' + CHUNK_VERSION + '\n' + str(start) + '\n' + content)[:24]
        chunks.append({'id': cid, 'content': content, 'metadata': {
            **doc['metadata'], 'doc_id': doc['id'], 'chunk_id': cid,
            'section': section, 'start_char': start, 'end_char': start + len(body),
            'chunk_version': CHUNK_VERSION, 'filename': doc['id'] + '.md',
            'source': doc['metadata']['publisher']}})

    # Offsets refer to the normalized Markdown snapshot, not source HTML.
    for match in re.finditer(r'[^\n]+(?:\n(?!\n)[^\n]+)*', text):
        paragraph = match.group().strip()
        if paragraph.startswith('#'):
            emit(pending, heading, start_offset)
            pending = []
            heading = paragraph.lstrip('# ').strip()
            continue
        prefix = title + ('\n' + heading if heading != title else '') + '\n\n'
        # Character windows checked by the actual tokenizer preserve original spelling.
        pos = 0
        while pos < len(paragraph):
            candidate = paragraph[pos:]
            if len(tokenizer.encode(prefix + '\n\n'.join(pending + [candidate]))) <= max_tokens:
                if not pending:
                    start_offset = match.start() + pos
                pending.append(candidate)
                break
            if pending:
                emit(pending, heading, start_offset)
                pending = []
                continue
            lo, hi = 1, len(candidate)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if len(tokenizer.encode(prefix + candidate[:mid])) <= max_tokens:
                    lo = mid
                else:
                    hi = mid - 1
            end = lo
            boundary = max(candidate.rfind('。', 0, end), candidate.rfind('；', 0, end), candidate.rfind('！', 0, end))
            if boundary >= end // 2:
                end = boundary + 1
            emit([candidate[:end]], heading, match.start() + pos)
            tail = end
            while tail > 0 and len(tokenizer.encode(candidate[tail-1:end], add_special_tokens=False)) <= overlap:
                tail -= 1
            pos += max(1, tail)
    emit(pending, heading, start_offset)
    for chunk in chunks:
        chunk['metadata']['total_chunks'] = len(chunks)
    return chunks
