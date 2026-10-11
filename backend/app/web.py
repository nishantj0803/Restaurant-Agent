import asyncio
import hashlib
import io
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from pypdf import PdfReader

from .config import Settings
from .llm import ProviderError
from .schemas import Source, Usage


def public_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if parsed.scheme not in ("http", "https") or not host or parsed.username or parsed.password:
            return False
        if parsed.port not in (None, 80, 443):
            return False
        if host.lower() == "localhost" or host.lower().endswith(
            (".local", ".localhost", ".internal")
        ):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return "." in host
    except ValueError:
        return False


def normalize_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), parsed.query, "")
    )


class Web:
    def __init__(self, client: httpx.AsyncClient, settings: Settings, usage: Usage):
        self.client = client
        self.settings = settings
        self.usage = usage
        self.sources: dict[str, Source] = {}
        self.cache: dict[str, Source] = {}
        self.errors: list[str] = []

    def add_source(
        self, url: str, title: str, text: str, coverage: str, published_date: str | None = None
    ) -> Source | None:
        if not public_url(url) or not text.strip():
            return None
        key = normalize_url(url) + ":" + coverage
        if coverage == "search_excerpt":
            key += ":" + hashlib.sha256(text.encode()).hexdigest()[:12]
        if key in self.cache:
            return self.cache[key]
        source = Source(
            id=f"s{len(self.sources) + 1}",
            url=url,
            title=title or url,
            text=text[:24000],
            coverage=coverage,
            published_date=published_date,
        )
        self.sources[source.id] = source
        self.cache[key] = source
        return source

    async def request(self, endpoint: str, payload: dict) -> dict:
        try:
            response = await self.client.post(
                f"https://api.tavily.com/{endpoint}",
                headers={
                    "Authorization": f"Bearer {self.settings.tavily_api_key.get_secret_value()}"
                },
                json=payload,
                timeout=35,
            )
        except httpx.HTTPError:
            raise ProviderError("Tavily could not be reached. Please retry.") from None
        if response.status_code >= 400:
            if response.status_code in (401, 403):
                raise ProviderError("Tavily authentication failed. Check TAVILY_API_KEY.")
            if response.status_code in (429, 432, 433):
                raise ProviderError(
                    "Tavily's credit or rate limit was reached. Check your account limits."
                )
            raise ProviderError("Tavily returned a service error.")
        return response.json()

    async def search(self, query: str, max_results: int = 5) -> list[Source]:
        if self.usage.searches >= 16:
            self.errors.append("The search limit was reached; some evidence could not be checked.")
            return []
        self.usage.searches += 1
        data = await self.request(
            "search",
            {
                "query": query[:500],
                "search_depth": "basic",
                "max_results": max_results,
                "include_answer": False,
                "include_raw_content": False,
                "auto_parameters": False,
            },
        )
        sources = []
        for row in data.get("results", []):
            source = self.add_source(
                row.get("url", ""),
                row.get("title", ""),
                row.get("content", ""),
                "search_excerpt",
                row.get("published_date"),
            )
            if source:
                sources.append(source)
        return sources

    async def read(self, urls: list[str]) -> list[Source]:
        cached = []
        pending = []
        for url in dict.fromkeys(urls):
            if not public_url(url):
                continue
            existing = self.cache.get(normalize_url(url) + ":extracted_page") or self.cache.get(
                normalize_url(url) + ":pdf"
            )
            if existing:
                cached.append(existing)
            else:
                pending.append(url)
        remaining = max(0, 12 - self.usage.documents)
        if len(pending) > remaining:
            self.errors.append("The document limit was reached; some pages could not be read.")
        pending = pending[:remaining]
        if not pending:
            return cached
        self.usage.documents += len(pending)
        try:
            data = await self.request(
                "extract",
                {"urls": pending, "extract_depth": "basic", "format": "markdown", "timeout": 25},
            )
        except ProviderError as exc:
            self.errors.append(f"Page extraction failed: {exc}")
            data = {"results": []}
        successful = set()
        for row in data.get("results", []):
            url = row.get("url", "")
            source = self.add_source(
                url, urlsplit(url).hostname or url, row.get("raw_content", ""), "extracted_page"
            )
            if source:
                successful.add(normalize_url(url))
                cached.append(source)
        for url in pending:
            if normalize_url(url) in successful:
                continue
            if urlsplit(url).path.lower().endswith(".pdf"):
                source = await self.read_pdf(url)
                if source:
                    cached.append(source)
                    continue
            self.errors.append(f"Could not read {url}. Only available search excerpts may be used.")
        return cached

    async def read_pdf(self, url: str) -> Source | None:
        try:
            for _ in range(4):
                if not public_url(url):
                    return None
                parsed = urlsplit(url)
                addresses = await asyncio.get_running_loop().getaddrinfo(
                    parsed.hostname,
                    parsed.port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
                if not addresses or any(
                    not ipaddress.ip_address(row[4][0]).is_global for row in addresses
                ):
                    return None
                async with self.client.stream(
                    "GET", url, follow_redirects=False, timeout=20
                ) as response:
                    if response.is_redirect:
                        url = str(response.url.join(response.headers.get("location", "")))
                        continue
                    response.raise_for_status()
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 5_000_000:
                            return None
                if not bytes(content).startswith(b"%PDF"):
                    return None
                text = await asyncio.to_thread(self.pdf_text, bytes(content))
                return self.add_source(url, "Menu PDF", text, "pdf")
        except (httpx.HTTPError, OSError, ValueError, ExceptionGroup):
            return None
        except Exception:
            return None
        return None

    @staticmethod
    def pdf_text(content: bytes) -> str:
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in list(reader.pages)[:20])[:24000]

    def known_url(self, url: str) -> bool:
        if not public_url(url):
            return False
        if any(normalize_url(source.url) == normalize_url(url) for source in self.sources.values()):
            return True
        return any(url in source.text for source in self.sources.values())

    @staticmethod
    def likely_official(source: Source, name: str) -> bool:
        host = (urlsplit(source.url).hostname or "").removeprefix("www.")
        name_parts = re.findall(r"[a-z0-9]+", name.casefold())
        distinctive = [
            part
            for part in name_parts
            if part not in {"the", "restaurant", "restaurante", "food", "fine", "bar", "cafe"}
            and len(part) > 3
        ]
        return any(part in host.replace("-", "") for part in distinctive)

    @staticmethod
    def menu_links(sources: list[Source], website: str) -> list[str]:
        host = (urlsplit(website).hostname or "").removeprefix("www.")
        links = []
        for source in sources:
            for label, target in re.findall(r"(?<!!)\[([^\]]*)\]\(([^\s)]+)\)", source.text):
                url = urljoin(source.url, target)
                if re.search(
                    r"menu|menú|carta|speise|karte|\.pdf", label + " " + url, re.I
                ) and public_url(url):
                    link_host = (urlsplit(url).hostname or "").removeprefix("www.")
                    if link_host == host or urlsplit(url).path.lower().endswith(".pdf"):
                        links.append(url)
        links = list(dict.fromkeys(links))
        links.sort(
            key=lambda url: (
                0 if urlsplit(url).path.lower().endswith(".pdf") else 1,
                1
                if any(
                    word in url.casefold() for word in ("group", "navidad", "valentin", "christmas")
                )
                else 0,
            )
        )
        return links[:3]
