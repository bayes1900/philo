import re
import json
import httpx
from typing import Any
from philo.utils.log import log
from philo.tools.base import ToolBase
from philo.utils.misc import stripTags, normalize, validateUrl


class BochaWebSearchTool(ToolBase):
    name = "web_search"
    description = "Search the web. Returns object of search results."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "count": {"type": "integer", "description": "Results (1-10)", "minimum": 1, "maximum": 10}
        },
        "required": ["query"]
    }

    def __init__(self, apiKey, maxResults=5, proxy=None):
        self.apiKey = apiKey
        self.maxResults = maxResults
        self.proxy = proxy

    async def execute(self, query, count=None, **kwargs) -> str:
        try:
            n = min(max(count or self.maxResults, 1), 10)
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.post(
                    "https://api.bocha.cn/v1/web-search",
                    headers = {
                        "Authorization": f"Bearer {self.apiKey}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "query": f"{query}",
                        "summary": True,
                        "freshness": "noLimit",
                        "count": n,
                    },
                    timeout=10.0,
                )
                r.raise_for_status()

            data = r.json().get("data", {})
            if not data:
                return f"No search results for query: {query}"
            return json.dumps(data)
        except httpx.ProxyError as e:
            log.red("WebSearch proxy error: {}", e)
            return f"Proxy error: {e}"
        except Exception as e:
            log.red("WebSearch error: {}", e)
            return f"Error: {e}"


class WebFetchTool(ToolBase):
    name = "web_fetch"
    description = "Fetch URL and extract readable content (HTML → markdown/text)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "extractMode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
            "maxChars": {"type": "integer", "minimum": 100}
        },
        "required": ["url"]
    }

    def __init__(self, maxChars: int = 50000, proxy: str | None = None):
        self.maxChars = maxChars
        self.proxy = proxy
        self.maxRedirects = 5

    async def execute(self, url: str, extractMode: str = "markdown", maxChars: int | None = None, **kwargs: Any) -> str:
        from readability import Document

        maxChars = maxChars or self.maxChars
        isValid, errorMsg = validateUrl(url)
        if not isValid:
            return json.dumps({"error": f"URL validation failed: {errorMsg}", "url": url}, ensure_ascii=False)

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=self.maxRedirects,
                timeout=30.0,
                proxy=self.proxy,
            ) as client:
                r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"})
                r.raise_for_status()

            ctype = r.headers.get("content-type", "")

            if "application/json" in ctype:
                text, extractor = json.dumps(r.json(), indent=2, ensure_ascii=False), "json"
            elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
                doc = Document(r.text)
                content = self.toMarkdown(doc.summary()) if extractMode == "markdown" else stripTags(doc.summary())
                text = f"# {doc.title()}\n\n{content}" if doc.title() else content
                extractor = "readability"
            else:
                text, extractor = r.text, "raw"

            truncated = len(text) > maxChars
            if truncated: text = text[:maxChars]

            return json.dumps({"url": url, "finalUrl": str(r.url), "status": r.status_code,
                              "extractor": extractor, "truncated": truncated, "length": len(text), "text": text}, ensure_ascii=False)
        except httpx.ProxyError as e:
            log.red("WebFetch proxy error for {}: {}", url, e)
            return json.dumps({"error": f"Proxy error: {e}", "url": url}, ensure_ascii=False)
        except Exception as e:
            log.red("WebFetch error for {}: {}", url, e)
            return json.dumps({"error": str(e), "url": url}, ensure_ascii=False)

    def toMarkdown(self, html: str) -> str:
        # Convert links, headings, lists before stripping tags
        text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                      lambda m: f'[{stripTags(m[2])}]({m[1]})', html, flags=re.I)
        text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                      lambda m: f'\n{"#" * int(m[1])} {stripTags(m[2])}\n', text, flags=re.I)
        text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {stripTags(m[1])}', text, flags=re.I)
        text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
        text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
        return normalize(stripTags(text))
