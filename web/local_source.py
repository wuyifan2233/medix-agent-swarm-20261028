"""Read a verified full article from the local evidence corpus, without network I/O."""
import html
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from knowledge.corpus import LOCAL, digest


def read_article(filename, root=None):
    if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9_-]+\.md", filename):
        return None
    root = Path(root or LOCAL)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    source_id = filename[:-3]
    meta = next((row for row in manifest['documents'] if row['id'] == source_id), None)
    if meta is None: return None
    generation = manifest.get('generation')
    if generation and not re.fullmatch(r'[a-f0-9]{16}', generation):
        raise ValueError('Invalid corpus generation')
    folder = root / 'generations' / generation if generation else root
    content = (folder / 'documents' / filename).read_text(encoding='utf-8')
    if digest(content) != meta.get('content_sha256'):
        raise ValueError('Local article integrity check failed')
    return {'title': meta.get('title') or source_id, 'publisher': meta.get('publisher') or '本地资料', 'content': content, 'url': meta.get('url', '')}


def article_html(article):
    title, publisher, content = (html.escape(str(article[k])) for k in ('title', 'publisher', 'content'))
    url = str(article.get('url') or '').strip()
    try:
        parsed = urlsplit(url)
        valid_url = parsed.scheme in {'https', 'http'} and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        valid_url = False
    link = (f'<a class="latest-link" href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">查看官网最新版本 ↗</a>' if valid_url else '')
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title} · MediX 本地原文</title>
<style>body{{margin:0;background:#f5f7fc;color:#344565;font:16px/1.9 system-ui,sans-serif}}main{{max-width:900px;margin:32px auto;background:white;padding:32px;border-radius:18px}}h1{{line-height:1.4;margin:0}}.article-header{{display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap;margin:20px 0}}.latest-link{{display:inline-block;padding:9px 16px;border-radius:10px;background:#625eeb;color:white;text-decoration:none;font-size:14px;font-weight:600;box-shadow:0 3px 10px #625eeb25}}.latest-link:hover{{background:#514dcc}}.latest-link:focus-visible{{outline:3px solid #a9a5ff;outline-offset:3px}}.publisher{{color:#5064ad;font-weight:600}}.note{{font-size:14px;color:#71809c}}pre{{font:inherit;white-space:pre-wrap;overflow-wrap:anywhere}}@media(max-width:600px){{main{{margin:0;padding:20px;border-radius:0}}}}</style>
<main><header class="article-header"><h1>{title}</h1>{link}</header><p class="publisher">{publisher}</p><p class="note">本地知识库收录全文，可离线阅读。内容为收录版本，不代表网站最新版本。</p><pre>{content}</pre></main></html>"""
