from __future__ import annotations

from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from app.collectors.base import Collector
from app.schemas import RawItem
from app.services.freshness import freshness_decision, parse_text_date
from app.settings import get_settings

HTML_INTENT_TERMS = (
    "防关联",
    "关联",
    "登录环境",
    "环境异常",
    "多账号",
    "多店铺",
    "店群",
    "矩阵",
    "养号",
    "住宅ip",
    "动态住宅",
    "代理ip",
    "代理",
    "ip",
    "tiktok",
    "亚马逊",
    "amazon",
    "shopee",
    "lazada",
    "shopify",
    "指纹浏览器",
    "adspower",
    "比特浏览器",
    "爬虫",
    "采集",
    "cloudflare",
    "验证码",
    "403",
    "429",
    "blocked",
    "captcha",
    "proxy",
    "residential",
)

SOURCE_QUERY_NOISE = {
    "search",
    "intent",
    "p30",
    "p33",
    "p34",
    "cn",
    "en",
    "forum",
    "forums",
    "issues",
    "source",
}


class HtmlLinksCollector(Collector):
    def __init__(self, source_name: str, url: str) -> None:
        self.source_name = source_name
        self.url = url

    async def collect(self) -> list[RawItem]:
        settings = get_settings()
        try:
            async with httpx.AsyncClient(
                timeout=20,
                headers={"User-Agent": settings.user_agent},
                follow_redirects=True,
            ) as client:
                response = await client.get(self.url)
                response.raise_for_status()
        except Exception:
            return await self.collect_with_browser(settings.user_agent)

        return self.parse_html(response.text, str(response.url))

    def parse_html(self, html: str, response_url: str) -> list[RawItem]:
        soup = BeautifulSoup(html, "html.parser")
        page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
        base_host = urlparse(response_url).netloc
        items: list[RawItem] = []
        seen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            title = anchor.get_text(" ", strip=True)
            if len(title) < 6:
                continue

            url = urljoin(response_url, anchor["href"])
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                continue
            if not is_allowed_result_host(base_host, parsed.netloc):
                continue
            if not is_allowed_result_path(parsed.netloc, parsed.path):
                continue
            if is_content_marketing_path(parsed.path):
                continue
            if url in seen:
                continue
            seen.add(url)

            context = nearest_text(anchor)
            if should_use_context_as_title(title, context):
                title = context
            if not matches_source_intent(self.source_name, title, context, url):
                continue
            published_at = parse_text_date(context)
            freshness = freshness_decision(
                published_at=published_at,
                title=title,
                content=context,
                url=url,
            )
            if not freshness.allowed:
                continue
            items.append(
                RawItem(
                    source_name=self.source_name,
                    source_kind="html_links",
                    title=title[:300],
                    url=url,
                    author="",
                    content=context[:3000],
                    published_at=freshness.published_at,
                )
            )

            if len(items) >= 80:
                break

        return items

    async def collect_with_browser(self, user_agent: str) -> list[RawItem]:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(locale="zh-CN", user_agent=user_agent)
            page = await context.new_page()
            try:
                try:
                    await page.goto(self.url, wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    # Some public pages keep long-polling or ads open; extract whatever rendered.
                    pass
                await page.wait_for_timeout(2500)
                response_url = page.url
                base_host = urlparse(response_url).netloc
                rows = await page.locator("a[href]").evaluate_all(
                    """
                    anchors => anchors.map(anchor => {
                        let parent = anchor;
                        let context = "";
                        for (let i = 0; i < 5 && parent; i += 1) {
                            const name = (parent.tagName || "").toLowerCase();
                            if (["li", "article", "tr", "div", "section"].includes(name)) {
                                const text = (parent.innerText || "").replace(/\\s+/g, " ").trim();
                                if (text && text.length > context.length) context = text;
                            }
                            parent = parent.parentElement;
                        }
                        return {
                            title: (anchor.innerText || anchor.textContent || "").replace(/\\s+/g, " ").trim(),
                            href: anchor.href,
                            context,
                        };
                    })
                    """
                )
            finally:
                await context.close()
                await browser.close()

        items: list[RawItem] = []
        seen: set[str] = set()
        for row in rows:
            title = str(row.get("title") or "").strip()
            if len(title) < 6:
                continue
            url = urljoin(response_url, str(row.get("href") or ""))
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                continue
            if not is_allowed_result_host(base_host, parsed.netloc):
                continue
            if not is_allowed_result_path(parsed.netloc, parsed.path):
                continue
            if is_content_marketing_path(parsed.path):
                continue
            if url in seen:
                continue
            seen.add(url)

            context = str(row.get("context") or "")[:1000]
            if should_use_context_as_title(title, context):
                title = context
            if not matches_source_intent(self.source_name, title, context, url):
                continue
            published_at = parse_text_date(context)
            freshness = freshness_decision(
                published_at=published_at,
                title=title,
                content=context,
                url=url,
            )
            if not freshness.allowed:
                continue
            items.append(
                RawItem(
                    source_name=self.source_name,
                    source_kind="html_links",
                    title=title[:300],
                    url=url,
                    author="",
                    content=context[:3000],
                    published_at=freshness.published_at,
                )
            )
            if len(items) >= 80:
                break

        return items


def is_content_marketing_path(path: str) -> bool:
    lowered = path.lower()
    blocked_parts = [
        "/a/",
        "/article",
        "/articles",
        "/blog",
        "/blogs",
        "/news",
        "/post/",
        "/posts/",
    ]
    return any(part in lowered for part in blocked_parts)


def is_allowed_result_path(host: str, path: str) -> bool:
    lowered_host = host.lower()
    lowered_path = path.lower()
    if lowered_host.endswith("v2ex.com"):
        return lowered_path.startswith("/t/")
    if lowered_host.endswith("segmentfault.com"):
        return lowered_path.startswith("/q/")
    return True


def is_allowed_result_host(base_host: str, candidate_host: str) -> bool:
    if is_search_engine_host(base_host):
        return is_allowed_search_result_host(candidate_host)
    if candidate_host == base_host:
        return True
    sibling_domains = ("cnblogs.com", "csdn.net", "oschina.net")
    return any(base_host.endswith(domain) and candidate_host.endswith(domain) for domain in sibling_domains)


def is_search_engine_host(host: str) -> bool:
    lowered = host.lower()
    return lowered.endswith("bing.com") or lowered.endswith("google.com") or lowered.endswith("baidu.com")


def is_allowed_search_result_host(host: str) -> bool:
    lowered = host.lower()
    blocked = (
        "bing.com",
        "google.com",
        "baidu.com",
        "microsoft.com",
        "support.google.com",
        "translate.google",
        "cache",
    )
    if any(part in lowered for part in blocked):
        return False
    allowed = (
        "github.com",
        "gitee.com",
        "v2ex.com",
        "segmentfault.com",
        "learnku.com",
        "oschina.net",
        "cnblogs.com",
        "csdn.net",
        "wearesellers.com",
        "sellercentral.amazon.com",
        "community.shopify.com",
        "community.ebay.com",
        "community.etsy.com",
        "sellercentral.amazon",
        "reddit.com",
        "stackoverflow.com",
        "blackhatworld.com",
        "warriorforum.com",
        "bbs.fobshanghai.com",
    )
    return any(lowered == domain or lowered.endswith("." + domain) for domain in allowed)


def should_use_context_as_title(title: str, context: str) -> bool:
    if not context or len(context) <= len(title):
        return False
    if len(title) <= 14 and all(char.isascii() and (char.isalnum() or char in "_-.") for char in title):
        return True
    weak_titles = {"login", "register", "github", "twitter", "telegram"}
    return title.lower() in weak_titles


def matches_source_intent(source_name: str, title: str, context: str, url: str) -> bool:
    if not is_search_like_source(source_name):
        return True
    title_text = (title or "").lower()
    compact_title = title_text.replace(" ", "")
    context_text = (context or "").lower()
    combined = f"{title_text}\n{context_text}\n{url.lower()}"
    source_terms = source_intent_terms(source_name)
    title_hits = sum(1 for term in source_terms if term in title_text or term in compact_title)
    combined_hits = sum(1 for term in source_terms if term in combined)
    demand_hits = sum(1 for term in HTML_INTENT_TERMS if term in combined)

    # For search pages, generic result cards often carry page-wide sidebar text.
    # Require the result title itself to carry intent, or multiple independent
    # demand terms in the card.
    if title_hits:
        return True
    if combined_hits >= 2 and demand_hits >= 2:
        return True
    if demand_hits >= 3 and any(term in title_text for term in ("求", "怎么", "被封", "异常", "关联", "代理", "proxy")):
        return True
    return False


def is_search_like_source(source_name: str) -> bool:
    lowered = (source_name or "").lower()
    markers = (" search:", " intent:", "p30 bing search:", "p34 ")
    return any(marker in lowered for marker in markers)


def source_intent_terms(source_name: str) -> list[str]:
    raw = (source_name or "").split(":", 1)[-1]
    normalized = raw.lower().replace("/", " ").replace("_", " ").replace("-", " ")
    chunks = []
    for item in re_split_terms(normalized):
        term = item.strip()
        if len(term) < 2 or term in SOURCE_QUERY_NOISE:
            continue
        chunks.append(term)
    return unique_terms(chunks)[:12]


def re_split_terms(value: str) -> list[str]:
    import re

    return re.split(r"[\s,，。；;:：|()（）]+", value)


def unique_terms(values: list[str]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            rows.append(value)
    return rows


def nearest_text(anchor) -> str:
    for parent in anchor.parents:
        if getattr(parent, "name", "") in {"li", "article", "tr", "div"}:
            text = parent.get_text(" ", strip=True)
            if text and len(text) > len(anchor.get_text(" ", strip=True)):
                return text[:1000]
    return ""
