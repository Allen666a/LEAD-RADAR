from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse


DOMESTIC_AUTHOR_PLATFORMS = {
    "zhihu",
    "tieba",
    "xiaohongshu",
    "douyin",
    "bilibili",
    "weibo",
    "wearesellers",
    "v2ex",
    "segmentfault",
    "learnku",
    "gitee",
}

GENERIC_PATH_PARTS = (
    "/search",
    "/tag/",
    "/tags/",
    "/topic",
    "/topics",
    "/explore",
    "/category",
    "/question/",
    "/questions/",
    "/answer/",
    "/article/",
    "/post/",
    "/video/",
    "/note/",
)

AUTHOR_NOISE = {
    "",
    "anonymous",
    "unknown",
    "null",
    "none",
    "知乎用户",
    "匿名用户",
    "百度用户",
    "小红书用户",
    "抖音用户",
    "b站用户",
    "微博用户",
    "用户",
    "作者",
    "楼主",
    "搜索",
    "推荐",
    "广告",
}

AUTHOR_PREFIX_NOISE = (
    "赞同",
    "评论",
    "关注",
    "分享",
    "阅读全文",
    "展开",
    "登录",
    "注册",
)


@dataclass(frozen=True)
class IdentityCandidate:
    key: str
    display_name: str
    profile_url: str
    confidence: int
    reason: str


def resolve_domestic_identity(platform: str, author: str, url: str, title: str = "", content: str = "") -> IdentityCandidate | None:
    platform = (platform or "").strip().lower()
    if platform not in DOMESTIC_AUTHOR_PLATFORMS:
        return None

    cleaned_author = clean_author_name(author)
    profile_url = extract_profile_url(platform, url, content)
    profile_handle = handle_from_profile_url(platform, profile_url or url)

    if cleaned_author:
        key_value = normalize_key_part(profile_handle or cleaned_author)
        return IdentityCandidate(
            key=f"{platform}:person:{key_value}",
            display_name=cleaned_author,
            profile_url=profile_url or url,
            confidence=86 if profile_handle else 72,
            reason="author",
        )

    if profile_handle and not is_generic_url(platform, url):
        return IdentityCandidate(
            key=f"{platform}:person:{normalize_key_part(profile_handle)}",
            display_name=profile_handle,
            profile_url=profile_url or url,
            confidence=70,
            reason="profile_url",
        )

    if is_specific_discussion_url(platform, url) and has_personal_demand_text(title, content):
        discussion_key = discussion_identity_key(platform, url)
        if discussion_key:
            return IdentityCandidate(
                key=f"{platform}:discussion:{discussion_key}",
                display_name=f"{platform} demand {discussion_key[-8:]}",
                profile_url=url,
                confidence=48,
                reason="specific_discussion",
            )

    return None


def clean_author_name(author: str) -> str:
    value = re.sub(r"\s+", " ", (author or "").strip())
    value = value.strip(":-_｜|·•,，。;；")
    if not value:
        return ""
    if len(value) > 48:
        return ""
    lower = value.lower()
    if lower in AUTHOR_NOISE or value in AUTHOR_NOISE:
        return ""
    if any(value.startswith(prefix) for prefix in AUTHOR_PREFIX_NOISE):
        return ""
    if re.fullmatch(r"\d+", value):
        return ""
    if re.search(r"(赞同|浏览|评论|回答|粉丝|关注)\s*\d*", value):
        return ""
    if value.count(" ") > 5:
        return ""
    return value


def extract_profile_url(platform: str, url: str, content: str = "") -> str:
    parsed = urlparse(url or "")
    candidates = [url or ""]
    candidates.extend(re.findall(r"https?://[^\s\"'<>]+", content or ""))
    for candidate in candidates:
        normalized = normalize_profile_url(platform, candidate)
        if normalized:
            return normalized
    if platform == "zhihu":
        qs = parse_qs(parsed.query)
        for value in qs.get("author", []) + qs.get("user", []):
            if value:
                return f"https://www.zhihu.com/people/{value}"
    return ""


def normalize_profile_url(platform: str, url: str) -> str:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    if not host or not path:
        return ""
    if platform == "zhihu" and "zhihu.com" in host and path.startswith("/people/"):
        return f"{parsed.scheme or 'https'}://{host}{path}"
    if platform == "xiaohongshu" and "xiaohongshu.com" in host and path.startswith("/user/profile/"):
        return f"{parsed.scheme or 'https'}://{host}{path}"
    if platform == "douyin" and "douyin.com" in host and path.startswith("/user/"):
        return f"{parsed.scheme or 'https'}://{host}{path}"
    if platform == "bilibili" and "bilibili.com" in host and path.startswith("/"):
        parts = [part for part in path.split("/") if part]
        if parts and parts[0].isdigit():
            return f"https://space.bilibili.com/{parts[0]}"
        if host == "space.bilibili.com" and parts:
            return f"https://space.bilibili.com/{parts[0]}"
    if platform == "weibo" and "weibo.com" in host:
        parts = [part for part in path.split("/") if part]
        if parts and parts[0] not in {"search", "weibo", "u"}:
            return f"https://weibo.com/{parts[0]}"
        if len(parts) >= 2 and parts[0] == "u":
            return f"https://weibo.com/u/{parts[1]}"
    return ""


def handle_from_profile_url(platform: str, url: str) -> str:
    parsed = urlparse(url or "")
    path = parsed.path.rstrip("/")
    parts = [part for part in path.split("/") if part]
    if not parts:
        return ""
    if platform == "zhihu" and len(parts) >= 2 and parts[0] == "people":
        return parts[1]
    if platform == "xiaohongshu" and len(parts) >= 3 and parts[:2] == ["user", "profile"]:
        return parts[2]
    if platform == "douyin" and len(parts) >= 2 and parts[0] == "user":
        return parts[1]
    if platform == "bilibili":
        if urlparse(url or "").netloc.lower() == "space.bilibili.com" and parts:
            return parts[0]
        if parts and parts[0].isdigit():
            return parts[0]
    if platform == "weibo":
        if len(parts) >= 2 and parts[0] == "u":
            return parts[1]
        if parts and parts[0] not in {"search", "weibo"}:
            return parts[0]
    return ""


def is_generic_url(platform: str, url: str) -> bool:
    parsed = urlparse(url or "")
    path = parsed.path.lower()
    if not path or path == "/":
        return True
    if any(part in path for part in ("/search", "/tag/", "/tags/", "/topic", "/explore", "/category")):
        return True
    if platform == "zhihu" and "zhuanlan.zhihu.com" in parsed.netloc.lower():
        return True
    return False


def is_specific_discussion_url(platform: str, url: str) -> bool:
    parsed = urlparse(url or "")
    path = parsed.path.lower()
    if is_generic_url(platform, url):
        return False
    return any(part in path for part in GENERIC_PATH_PARTS)


def discussion_identity_key(platform: str, url: str) -> str:
    parsed = urlparse(url or "")
    compact = f"{parsed.netloc.lower()}{parsed.path.rstrip('/').lower()}"
    compact = re.sub(r"[^a-z0-9/_-]+", "", compact)
    return compact[-180:]


def has_personal_demand_text(title: str, content: str) -> bool:
    text = f"{title}\n{content}".lower()
    pain_or_buy = (
        "怎么办",
        "怎么解决",
        "求推荐",
        "哪里买",
        "有没有",
        "不稳定",
        "被封",
        "关联",
        "防关联",
        "验证",
        "403",
        "429",
        "cloudflare",
        "captcha",
        "looking for",
        "recommend",
    )
    scenario = (
        "tiktok",
        "亚马逊",
        "amazon",
        "shopee",
        "店群",
        "矩阵",
        "多账号",
        "爬虫",
        "采集",
        "指纹浏览器",
        "代理",
        "住宅ip",
        "residential proxy",
    )
    return any(term in text for term in pain_or_buy) and any(term in text for term in scenario)


def normalize_key_part(value: str) -> str:
    value = re.sub(r"\s+", "_", (value or "").strip().lower())
    return re.sub(r"[^a-z0-9_\-\u4e00-\u9fff]+", "", value)[:120] or "unknown"
