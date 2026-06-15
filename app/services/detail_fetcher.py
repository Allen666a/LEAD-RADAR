from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.schemas import RawItem
from app.services.freshness import parse_text_date
from app.settings import get_settings


DETAIL_SKIP_KINDS = {"github", "gitee", "v2ex", "rss"}


@dataclass(frozen=True)
class DetailFetchResult:
    status: str
    reason: str
    title: str = ""
    content: str = ""
    published_at: datetime | None = None


def should_fetch_detail(item: RawItem) -> bool:
    if item.source_kind in DETAIL_SKIP_KINDS:
        return False
    parsed = urlparse(item.url or "")
    if parsed.scheme not in {"http", "https"}:
        return False
    if len(item.content or "") >= 600 and item.published_at is not None:
        return False
    return True


async def fetch_detail_item(item: RawItem, timeout: float = 8.0) -> tuple[RawItem, DetailFetchResult]:
    if not should_fetch_detail(item):
        return item, DetailFetchResult(
            "skipped",
            "来源已提供正文或不适合二跳。",
            item.title,
            item.content,
            item.published_at,
        )

    settings = get_settings()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=3.0),
            headers={"User-Agent": settings.user_agent},
            follow_redirects=True,
        ) as client:
            response = await client.get(item.url)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 403:
            return item, DetailFetchResult("blocked", "详情页 403，暂不重试。")
        if code == 404:
            return item, DetailFetchResult("failed", "详情页不存在或已删除。")
        if code == 429:
            return item, DetailFetchResult("blocked", "详情页频率受限。")
        return item, DetailFetchResult("failed", f"详情页 HTTP {code}。")
    except Exception as exc:  # noqa: BLE001
        text = str(exc) or exc.__class__.__name__
        if "timeout" in text.lower() or "timed out" in text.lower():
            return item, DetailFetchResult("failed", "详情页读取超时。")
        return item, DetailFetchResult("failed", f"详情页读取失败：{text[:120]}")

    detail = parse_detail_html(response.text, str(response.url))
    if detail.status != "ok":
        return item, detail

    merged = RawItem(
        source_name=item.source_name,
        source_kind=item.source_kind,
        title=(detail.title or item.title)[:300],
        url=item.url,
        author=item.author,
        content=(detail.content or item.content)[:5000],
        published_at=detail.published_at or item.published_at,
    )
    return merged, detail


def parse_detail_html(html: str, url: str) -> DetailFetchResult:
    soup = BeautifulSoup(html[:800_000], "html.parser")
    for selector in ("script", "style", "noscript", "nav", "footer", "header", "aside"):
        for node in soup.select(selector):
            node.decompose()

    title = extract_title(soup)
    published_at = extract_published_at(soup)
    content = extract_main_text(soup)
    page_type, page_reason = classify_page_type(url, title, content)
    if page_type != "detail":
        return DetailFetchResult("not_detail", page_reason, title, content[:1200], published_at)
    if len(content) < 80:
        return DetailFetchResult("failed", "详情页正文太短，无法作为证据。", title, content, published_at)
    if published_at is None:
        published_at = parse_text_date(f"{title}\n{content[:1200]}")
    return DetailFetchResult("ok", "已读取详情页正文。", title, content, published_at)


def classify_page_type(url: str, title: str, content: str) -> tuple[str, str]:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower()
    path = (parsed.path or "/").lower()
    title_text = (title or "").strip().lower()
    content_text = (content or "").lower()

    if is_known_detail_path(host, path):
        return "detail", "命中已知帖子详情页路径。"
    if is_known_list_path(host, path):
        return "not_detail", "这是分类、搜索、标签或列表页，不是具体客户需求帖。"
    if is_generic_title(title_text):
        return "not_detail", "页面标题过于泛化，像栏目页或导航页。"
    if looks_like_directory_page(content_text):
        return "not_detail", "页面包含大量导航、排行榜或推荐内容，像列表页。"
    if len(content_text) >= 180 and has_question_or_pain_signal(title_text + "\n" + content_text[:1200]):
        return "detail", "页面内容像具体问题或需求帖。"
    return "not_detail", "未能确认这是具体需求详情页。"


def is_known_detail_path(host: str, path: str) -> bool:
    rules = (
        ("segmentfault.com", ("/q/",)),
        ("v2ex.com", ("/t/",)),
        ("wearesellers.com", ("/question/",)),
        ("zhihu.com", ("/question/", "/pin/",)),
        ("tieba.baidu.com", ("/p/",)),
        ("github.com", ("/issues/",)),
        ("gitee.com", ("/issues/",)),
        ("sellercentral.amazon", ("/seller-forums/discussions/t/", "/forums/discussions/t/")),
        ("community.shopify.com", ("/t/",)),
        ("community.ebay.com", ("/t5/",)),
        ("community.etsy.com", ("/t5/",)),
        ("reddit.com", ("/comments/",)),
        ("stackoverflow.com", ("/questions/",)),
        ("blackhatworld.com", ("/seo/", "/threads/",)),
        ("warriorforum.com", ("/main-internet-marketing-discussion-forum/",)),
    )
    return any(host.endswith(domain) and any(path.startswith(prefix) for prefix in prefixes) for domain, prefixes in rules)


def is_known_list_path(host: str, path: str) -> bool:
    generic_parts = (
        "/category",
        "/categories",
        "/tag",
        "/tags",
        "/search",
        "/topics",
        "/topic",
        "/users",
        "/people",
        "/news",
        "/blog",
        "/blogs",
        "/article",
        "/articles",
        "/resources",
        "/ranking",
        "/rank",
        "/feed",
        "/explore",
        "/discover",
    )
    if path in {"", "/"}:
        return True
    if any(part in path for part in generic_parts):
        return True
    if host.endswith("wearesellers.com") and path.startswith("/category-"):
        return True
    if host.endswith("community.shopify.com") and path.startswith("/c/"):
        return False
    return False


def is_generic_title(title_text: str) -> bool:
    if not title_text:
        return True
    generic_titles = (
        "首页",
        "社区",
        "搜索",
        "标签",
        "分类",
        "drop shipping",
        "shopify",
        "magento",
        "amazon",
        "问答",
        "博客",
        "资讯",
        "资源",
    )
    return title_text in generic_titles or title_text.endswith("社区")


def looks_like_directory_page(content_text: str) -> bool:
    if not content_text:
        return True
    directory_terms = (
        "当天热门",
        "7天热门",
        "30天热门",
        "活动推荐",
        "热门资源",
        "排行榜",
        "最新入驻",
        "推荐问题",
        "猜你喜欢",
        "全部内容",
        "付费问答",
        "社区公告",
        "注册 登录",
    )
    hits = sum(1 for term in directory_terms if term.lower() in content_text)
    if hits >= 3:
        return True
    date_like_count = content_text.count("更新") + content_text.count("回复了问题")
    return date_like_count >= 8


def has_question_or_pain_signal(text: str) -> bool:
    terms = (
        "怎么",
        "如何",
        "有没有",
        "求",
        "请教",
        "问题",
        "被封",
        "关联",
        "防关联",
        "验证码",
        "403",
        "429",
        "cloudflare",
        "代理",
        "ip",
        "proxy",
        "blocked",
        "captcha",
    )
    lowered = text.lower()
    return any(term in lowered for term in terms)


def extract_title(soup: BeautifulSoup) -> str:
    for selector in ("h1", "meta[property='og:title']", "meta[name='twitter:title']", "title"):
        node = soup.select_one(selector)
        if not node:
            continue
        if node.name == "meta":
            value = node.get("content", "")
        else:
            value = node.get_text(" ", strip=True)
        value = " ".join(value.split())
        if value:
            return value[:300]
    return ""


def extract_published_at(soup: BeautifulSoup) -> datetime | None:
    attrs = [
        ("meta[property='article:published_time']", "content"),
        ("meta[name='pubdate']", "content"),
        ("meta[name='publishdate']", "content"),
        ("meta[name='date']", "content"),
        ("time[datetime]", "datetime"),
    ]
    for selector, attr in attrs:
        node = soup.select_one(selector)
        if not node:
            continue
        parsed = parse_datetime_value(str(node.get(attr, "")))
        if parsed:
            return parsed
    text = ""
    for node in soup.select("time, .date, .time, .created, .published"):
        text += "\n" + node.get_text(" ", strip=True)
    return parse_text_date(text)


def parse_datetime_value(value: str) -> datetime | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return parse_text_date(cleaned)


def extract_main_text(soup: BeautifulSoup) -> str:
    candidates = []
    selectors = [
        "article",
        "main",
        ".QuestionRichText",
        ".RichContent-inner",
        ".topic_content",
        ".content",
        ".post-content",
        ".markdown-body",
        "#Main",
        "body",
    ]
    for selector in selectors:
        for node in soup.select(selector):
            text = clean_text(node.get_text("\n", strip=True))
            if text:
                candidates.append(text)
    if not candidates:
        return ""
    candidates.sort(key=len, reverse=True)
    return candidates[0][:5000]


def clean_text(value: str) -> str:
    lines = []
    seen = set()
    for raw in value.splitlines():
        line = " ".join(raw.split())
        if len(line) < 2:
            continue
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines)
