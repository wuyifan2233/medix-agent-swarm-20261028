"""Async DeepSeek Search adapter. DDGS is available only by explicit selection."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from loguru import logger
from openai import APIError
from runtime_settings import load_setting

try:
    from ddgs import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False
    DDGS = None


class SearchError(APIError):
    """Safe provider errors, propagated instead of being presented as research."""
    def __init__(self, message):
        super().__init__(message, request=httpx.Request('POST', 'https://api.deepseek.com/v1/tools/search'), body=None)


def source_key(url):
    """Canonical key for duplicate source URLs; preserve meaningful query strings."""
    parts = urlsplit(url)
    return (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip('/'), parts.query)


def unique_sources(rows):
    seen = set()
    for row in rows:
        key = source_key(row.url)
        if key not in seen:
            seen.add(key)
            yield row


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str = 'web'
    summary: str = ''
    content: str = ''
    site_name: Optional[str] = None
    date: Optional[str] = None
    authority: Optional[int] = None
    rerank_score: Optional[float] = None


class WebSearchTool:
    def __init__(self, timeout=30, provider=None, api_key=None, transport=None):
        self.timeout = timeout
        self.provider = provider or load_setting('MEDIX_SEARCH_PROVIDER', 'deepseek')
        if self.provider not in {'deepseek', 'ddgs'}:
            raise ValueError('MEDIX_SEARCH_PROVIDER 必须是 deepseek 或 ddgs。')
        self.api_key = api_key
        self.transport = transport
        self.medical_domains = ['pubmed.ncbi.nlm.nih.gov', 'mayoclinic.org', 'webmd.com', 'who.int',
                                'cdc.gov', 'nih.gov', 'uptodate.com', 'medscape.com', 'healthline.com',
                                'medicalnewstoday.com']

    async def search(self, query, max_results=10, region='cn-zh', safesearch='on',
                     timelimit=None, retry_count=0, need_content=False, ori_question=None):
        if not isinstance(query, str) or not query.strip():
            raise ValueError('搜索词不能为空。')
        if type(max_results) is not int or not 1 <= max_results <= 50:
            raise ValueError('搜索条数必须为 1–50。')
        if timelimit not in {None, 'd', 'w', 'm', 'y'}:
            raise ValueError('不支持的搜索时间范围。')
        if self.provider == 'ddgs':
            return await self._search_ddgs(query, max_results, region, safesearch, timelimit, retry_count)
        if timelimit:
            days = {'d': 1, 'w': 7, 'm': 30, 'y': 365}[timelimit]
            after = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
            query = f'{query} after:{after}'
        if len(query) > 128:
            raise ValueError('DeepSeek 搜索词最多128个字符，请缩短后重试。')
        if type(need_content) is not bool:
            raise ValueError('need_content 必须是布尔值。')
        if ori_question is not None and (not isinstance(ori_question, str) or not ori_question.strip() or len(ori_question) > 128):
            raise ValueError('原始搜索问题必须为1–128个字符。')
        key = self.api_key if self.api_key is not None else load_setting('DEEPSEEK_SEARCH_API_KEY', load_setting('DEEPSEEK_API_KEY'))
        if not key or key.lower() in {'xxx', 'not-configured'}:
            raise SearchError('尚未配置 DeepSeek 网页搜索密钥。')
        payload = {'query': query, 'count': max_results, 'need_content': need_content}
        if ori_question is not None:
            payload['ori_question'] = ori_question
        from core.chat_runtime import service_usage
        from core.token_pricing import search_price
        async with service_usage('deepseek-search', search_price()) as receipt:
            try:
                async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport, follow_redirects=False) as client:
                    response = await client.post('https://api.deepseek.com/v1/tools/search',
                                                 headers={'Authorization': 'Bearer ' + key}, json=payload)
            except httpx.HTTPError:
                raise SearchError('DeepSeek 网页搜索连接失败或超时，请稍后重试。') from None
            if response.status_code != 200:
                receipt.cost = '0'  # Published tariff: unsuccessful requests are not billed.
                messages = {400: '网页搜索参数未通过校验。', 401: 'DeepSeek 网页搜索鉴权失败，请检查密钥。',
                            402: 'DeepSeek 搜索服务余额不足。', 403: 'DeepSeek 网页搜索请求被拒绝。',
                            429: 'DeepSeek 网页搜索请求过于频繁，请稍后重试。'}
                raise SearchError(messages.get(response.status_code, 'DeepSeek 网页搜索暂时不可用，请稍后重试。'))
            try:
                data = response.json()
                raw = data['results']
                if not isinstance(raw, list):
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise SearchError('DeepSeek 网页搜索响应格式异常，费用待核对。') from None
            # Charge the upstream result, even when later validation/filtering removes items.
            receipt.cost = receipt.price['request'] if raw else '0'
            rows = []
            for item in raw:
                if not isinstance(item, dict) or not isinstance(item.get('url'), str):
                    continue
                try:
                    parsed = urlsplit(item['url'])
                    valid = parsed.scheme in {'https', 'http'} and bool(parsed.hostname) and not parsed.username and not parsed.password
                except ValueError:
                    valid = False
                if not valid:
                    continue
                rows.append(SearchResult(str(item.get('title') or ''), item['url'], str(item.get('snippet') or ''),
                            summary=str(item.get('summary') or ''), content=str(item.get('content') or '') if need_content else '',
                            site_name=item.get('site_name'), date=item.get('date'), authority=item.get('authority'),
                            rerank_score=item.get('rerank_score')))
            return list(unique_sources(rows))[:max_results]

    async def _search_ddgs(self, query, count, region, safesearch, timelimit, retries):
        if not DDGS_AVAILABLE:
            return []
        for attempt in range(retries + 1):
            for backend in ('bing', 'duckduckgo', 'auto'):
                def run():
                    return list(DDGS(timeout=self.timeout).text(query, max_results=count * 2,
                                safesearch=safesearch, region=region, backend=backend, timelimit=timelimit))
                try:
                    raw = await asyncio.wait_for(asyncio.to_thread(run), self.timeout + 1)
                    rows = [SearchResult(item.get('title', ''), item.get('href', ''), item.get('body', '')) for item in raw]
                    if rows:
                        return list(unique_sources(rows))[:count]
                except asyncio.CancelledError:
                    raise
                except Exception:
                    continue
            if attempt < retries:
                await asyncio.sleep(min(2 ** attempt, 4))
        return []

    def filter_by_domain(self, results, allowed_domains=None):
        allowed = self.medical_domains if allowed_domains is None else allowed_domains
        allowed = [domain.lower().rstrip('.') for domain in allowed]
        rows = []
        for result in results:
            try:
                parts = urlsplit(result.url)
                host = (parts.hostname or '').lower().rstrip('.')
                if parts.scheme in {'http', 'https'} and any(host == domain or host.endswith('.' + domain) for domain in allowed):
                    rows.append(result)
            except ValueError:
                continue
        return rows

    async def fetch_content(self, url, max_length=2000):
        """Optional legacy page retrieval, not a DeepSeek Fetch API request."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            for element in soup(['script', 'style']):
                element.decompose()
            text = ' '.join(soup.stripped_strings)
            return text[:max_length] + ('...' if len(text) > max_length else '')
        except httpx.HTTPError:
            return None

    async def search_with_content(self, query, max_results=5, fetch_full_content=False):
        # Official search can return content itself; never silently add a paid Fetch call.
        rows = await self.search(query, max_results=max_results, **({'need_content': True} if fetch_full_content and self.provider == 'deepseek' else {}))
        output = []
        for row in rows:
            full = row.content or None
            if fetch_full_content and self.provider == 'ddgs':
                full = await self.fetch_content(row.url)
            output.append({'title': row.title, 'url': row.url, 'snippet': row.snippet, 'summary': row.summary,
                           'source': row.source, 'full_content': full})
        return output


async def search_medical_web(query, max_results=10):
    return await WebSearchTool().search(query, max_results=max_results)


def search_status():
    provider = load_setting('MEDIX_SEARCH_PROVIDER', 'deepseek')
    key = load_setting('DEEPSEEK_SEARCH_API_KEY', load_setting('DEEPSEEK_API_KEY'))
    configured = bool(key and key.lower() not in {'xxx', 'not-configured'}) if provider == 'deepseek' else DDGS_AVAILABLE if provider == 'ddgs' else False
    return {'search_provider': provider, 'search_configured': configured}
