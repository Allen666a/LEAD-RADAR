from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models import CandidateItem, Mention, Source
from app.services.signals import HIGH_VALUE_SIGNALS


CURRENT_YEAR = 2026


@dataclass(frozen=True)
class PlatformDefinition:
    key: str
    name: str
    mode: str
    source_prefixes: tuple[str, ...]
    host_keywords: tuple[str, ...]
    note: str


@dataclass
class PlatformStatus:
    key: str
    name: str
    mode: str
    note: str
    source_count: int = 0
    enabled_sources: int = 0
    success_count: int = 0
    failure_count: int = 0
    blocked_sources: int = 0
    fetched: int = 0
    inserted: int = 0
    candidates: int = 0
    candidate_accepted: int = 0
    candidate_review: int = 0
    candidate_rejected: int = 0
    candidate_duplicate: int = 0
    not_detail: int = 0
    missing_time: int = 0
    old_content: int = 0
    low_intent: int = 0
    detail_ok: int = 0
    detail_blocked: int = 0
    detail_failed: int = 0
    detail_deferred: int = 0
    mentions: int = 0
    usable_mentions: int = 0
    review_mentions: int = 0
    invalid_mentions: int = 0
    high_value_mentions: int = 0
    stale_usable: int = 0
    quality_score: int = 0
    quality_status: str = "未接入"
    status: str = "未接入"
    recommended_action: str = "先接入来源或导入验证线索。"
    next_collect_at: datetime | None = None
    cooldown_until: datetime | None = None
    last_checked_at: datetime | None = None
    last_error: str = ""


PLATFORMS = [
    PlatformDefinition(
        "blackhatworld",
        "BlackHatWorld",
        "公开论坛",
        ("BlackHatWorld",),
        ("blackhatworld.com",),
        "海外营销、账号、社媒矩阵和爬虫需求密集，是动态住宅 IP 的重点来源。",
    ),
    PlatformDefinition(
        "github",
        "GitHub",
        "公开代码/Issue",
        ("GitHub", "GitHub Issues:", "GitHub Search:"),
        ("github.com",),
        "适合发现爬虫、指纹浏览器、代理异常、账号系统相关项目和 issue。",
    ),
    PlatformDefinition(
        "gitee",
        "Gitee",
        "公开代码/Issue",
        ("Gitee", "Gitee Issues:", "Gitee Intent:"),
        ("gitee.com",),
        "国内开发者 issue 来源；容易受限，建议有 token 时加码。",
    ),
    PlatformDefinition(
        "v2ex",
        "V2EX",
        "公开社区",
        ("V2EX", "V2EX Intent:", "V2EX Tag:"),
        ("v2ex.com",),
        "中文技术和独立开发讨论，适合发现代理、爬虫、账号异常痛点。",
    ),
    PlatformDefinition(
        "segmentfault",
        "SegmentFault",
        "公开问答",
        ("SegmentFault Search:", "SegmentFault Intent:"),
        ("segmentfault.com",),
        "中文技术问答，需严格过滤旧帖、教程和泛技术讨论。",
    ),
    PlatformDefinition(
        "zhihu",
        "知乎",
        "登录会话/公开搜索",
        ("Zhihu", "知乎", "Session 知乎:"),
        ("zhihu.com",),
        "适合补充国内讨论线索；遇到验证或低质输出必须降频。",
    ),
    PlatformDefinition(
        "wearesellers",
        "WeAreSellers/卖家论坛",
        "跨境卖家社区",
        ("WeAreSellers", "Amazon Seller Forum CN:", "FOB Shanghai:"),
        ("wearesellers.com", "sellercentral.amazon.com", "bbs.fobshanghai.com"),
        "跨境卖家场景强，但要剔除栏目页、广告和泛资讯。",
    ),
    PlatformDefinition(
        "amazon_seller",
        "Amazon Seller Forum",
        "跨境卖家社区",
        ("Amazon Seller", "Amazon Seller Forum"),
        ("sellercentral.amazon.com", "sellercentral.amazon."),
        "亚马逊多账号、防关联、店群场景，优先找真实求助帖。",
    ),
    PlatformDefinition(
        "shopify",
        "Shopify Community",
        "跨境卖家社区",
        ("Shopify", "Shopify Community"),
        ("community.shopify.com", "shopify.com/community"),
        "独立站、多店铺、支付风控和广告投放环境相关补充来源。",
    ),
    PlatformDefinition(
        "amz123",
        "AMZ123",
        "跨境卖家资讯/社区",
        ("AMZ123",),
        ("amz123.com",),
        "国内跨境卖家入口，需重点过滤资讯和广告，只保留讨论/需求。",
    ),
    PlatformDefinition(
        "cifnews",
        "雨果跨境",
        "跨境卖家资讯/社区",
        ("Cifnews", "雨果"),
        ("cifnews.com",),
        "跨境卖家入口，适合补充店群、防关联、平台风控话题。",
    ),
    PlatformDefinition(
        "warriorforum",
        "Warrior Forum",
        "海外营销论坛",
        ("Warrior Forum",),
        ("warriorforum.com",),
        "海外营销和自动化讨论，适合账号矩阵、流量和代理需求。",
    ),
    PlatformDefinition(
        "reddit",
        "Reddit",
        "海外社区",
        ("Reddit",),
        ("reddit.com",),
        "海外公开讨论补充源；要避免把泛讨论当成可触达客户。",
    ),
    PlatformDefinition(
        "gologin",
        "GoLogin",
        "同行/指纹浏览器生态",
        ("GoLogin",),
        ("gologin.com",),
        "用于发现指纹浏览器用户痛点，同行文章只可做情报，不进可触达线索。",
    ),
    PlatformDefinition(
        "adspower",
        "AdsPower",
        "同行/指纹浏览器生态",
        ("AdsPower",),
        ("adspower.com",),
        "用于发现账号矩阵、防关联关键词，同行官网内容需要严格剔除。",
    ),
    PlatformDefinition(
        "octobrowser",
        "Octo Browser",
        "同行/指纹浏览器生态",
        ("Octo Browser",),
        ("octobrowser.net",),
        "用于研究需求语言，不应作为直接获客主源。",
    ),
    PlatformDefinition(
        "csdn",
        "CSDN",
        "公开技术内容",
        ("CSDN",),
        ("csdn.net",),
        "只保留真实问题和近期内容，教程、搬运、泛文章进入垃圾池。",
    ),
    PlatformDefinition(
        "oschina",
        "开源中国",
        "公开技术社区",
        ("OSChina",),
        ("oschina.net",),
        "国内技术社区补充来源，适合代理异常和采集痛点。",
    ),
    PlatformDefinition(
        "cnblogs",
        "博客园",
        "公开技术内容",
        ("CNBlogs",),
        ("cnblogs.com",),
        "低优先级补充源，只保留近期真实需求。",
    ),
    PlatformDefinition(
        "xiaohongshu",
        "小红书",
        "登录会话/社媒补充",
        ("小红书", "Session 小红书:"),
        ("xiaohongshu.com",),
        "只做低频公开搜索补充，不作为主战场。",
    ),
    PlatformDefinition(
        "douyin",
        "抖音",
        "登录会话/社媒补充",
        ("抖音", "Session 抖音:"),
        ("douyin.com",),
        "只做低频公开搜索补充，不自动互动。",
    ),
    PlatformDefinition(
        "bilibili",
        "B站",
        "登录会话/视频社区补充",
        ("B站", "Bilibili", "Session B站"),
        ("bilibili.com",),
        "适合发现教程作者和公开讨论，需人工判断是否可触达。",
    ),
    PlatformDefinition(
        "weibo",
        "微博",
        "登录会话/社媒补充",
        ("微博", "Session 微博:"),
        ("weibo.com",),
        "公开讨论补充源，遇验证立即停。",
    ),
]


DEFINITION_BY_KEY = {item.key: item for item in PLATFORMS}
SOURCE_PREFIX_MAP = [(item.key, item.source_prefixes) for item in PLATFORMS]
HOST_KEYWORDS = [(item.key, item.host_keywords) for item in PLATFORMS]


def build_platform_statuses(db: Session) -> list[PlatformStatus]:
    sources = list(db.query(Source).all())
    candidates = list(db.query(CandidateItem).all())
    mentions = list(db.query(Mention).all())

    keys = set(DEFINITION_BY_KEY)
    keys.update(platform_key_for_source(source) for source in sources)
    keys.update(platform_key_for_candidate(candidate) for candidate in candidates)
    keys.update(platform_key_for_mention(mention) for mention in mentions)
    keys.discard("")

    source_groups: dict[str, list[Source]] = defaultdict(list)
    candidate_groups: dict[str, list[CandidateItem]] = defaultdict(list)
    mention_groups: dict[str, list[Mention]] = defaultdict(list)

    for source in sources:
        source_groups[platform_key_for_source(source)].append(source)
    for candidate in candidates:
        candidate_groups[platform_key_for_candidate(candidate)].append(candidate)
    for mention in mentions:
        mention_groups[platform_key_for_mention(mention)].append(mention)

    rows: list[PlatformStatus] = []
    for key in sorted(keys):
        definition = DEFINITION_BY_KEY.get(
            key,
            PlatformDefinition(key, display_name(key), "公开来源", tuple(), (key,), "自动识别的新来源，先观察产出和噪音。"),
        )
        row = build_row(definition, source_groups[key], candidate_groups[key], mention_groups[key])
        rows.append(row)

    return sorted(rows, key=platform_sort_key)


def build_row(
    definition: PlatformDefinition,
    sources: list[Source],
    candidates: list[CandidateItem],
    mentions: list[Mention],
) -> PlatformStatus:
    failure_counts = Counter((item.failure_type or "").strip() for item in candidates)
    detail_counts = Counter((item.detail_status or "").strip() for item in candidates)
    candidate_status_counts = Counter((item.status or "").strip() for item in candidates)

    usable_mentions = [item for item in mentions if item.status != "invalid"]
    row = PlatformStatus(
        key=definition.key,
        name=definition.name,
        mode=definition.mode,
        note=definition.note,
        source_count=len(sources),
        enabled_sources=sum(1 for source in sources if source.enabled),
        success_count=sum(source.success_count or 0 for source in sources),
        failure_count=sum(source.failure_count or 0 for source in sources),
        blocked_sources=sum(
            1
            for source in sources
            if (source.quality_status or "") == "blocked"
            or is_blocked_error(source.last_error)
            or source.cooldown_until
        ),
        fetched=sum(source.last_fetched_count or 0 for source in sources),
        inserted=sum(source.last_inserted_count or 0 for source in sources),
        candidates=len(candidates),
        candidate_accepted=sum(1 for item in candidates if item.mention_id or item.status in {"accepted", "inserted"}),
        candidate_review=sum(candidate_status_counts.get(status, 0) for status in ("review", "needs_review", "candidate")),
        candidate_rejected=sum(candidate_status_counts.get(status, 0) for status in ("rejected", "invalid", "discarded")),
        candidate_duplicate=failure_counts.get("duplicate", 0),
        not_detail=failure_counts.get("not_detail", 0) + detail_counts.get("not_detail", 0),
        missing_time=failure_counts.get("missing_time", 0),
        old_content=failure_counts.get("old_content", 0),
        low_intent=failure_counts.get("low_intent", 0),
        detail_ok=detail_counts.get("ok", 0),
        detail_blocked=detail_counts.get("blocked", 0),
        detail_failed=detail_counts.get("failed", 0),
        detail_deferred=detail_counts.get("deferred", 0),
        mentions=len(usable_mentions),
        usable_mentions=len(usable_mentions),
        review_mentions=sum(1 for item in mentions if item.status in {"review", "needs_review"}),
        invalid_mentions=sum(1 for item in mentions if item.status == "invalid"),
        high_value_mentions=sum(
            1 for item in usable_mentions if item.signal_type in HIGH_VALUE_SIGNALS and (item.score or 0) >= 60
        ),
        stale_usable=sum(
            1 for item in usable_mentions if item.published_at is not None and item.published_at.year < CURRENT_YEAR
        ),
        next_collect_at=min((source.next_collect_at for source in sources if source.next_collect_at), default=None),
        cooldown_until=max((source.cooldown_until for source in sources if source.cooldown_until), default=None),
        last_checked_at=max((source.last_checked_at for source in sources if source.last_checked_at), default=None),
        last_error=latest_error(sources),
    )
    row.quality_score = score_platform(row)
    row.quality_status = classify_platform_status(row)
    row.status = row.quality_status
    row.recommended_action = recommend_action(row)
    return row


def score_platform(row: PlatformStatus) -> int:
    score = 35
    score += min(row.usable_mentions * 2, 25)
    score += min(row.high_value_mentions * 5, 25)
    score += min(row.detail_ok, 10)
    score -= min(row.old_content * 2, 25)
    score -= min(row.not_detail, 20)
    score -= min(row.detail_blocked * 5 + row.blocked_sources * 4, 25)
    score -= min(row.low_intent, 15)
    if row.stale_usable:
        score -= 30
    return max(0, min(100, score))


def classify_platform_status(row: PlatformStatus) -> str:
    if row.stale_usable:
        return "需清理"
    if row.detail_blocked >= 10 or row.blocked_sources:
        return "受阻"
    if row.usable_mentions >= 10 or row.high_value_mentions >= 5:
        return "加码"
    if row.old_content or row.not_detail >= max(5, row.candidates // 2):
        return "降噪"
    if row.candidates or row.usable_mentions:
        return "观察"
    if row.source_count:
        return "低产"
    return "未接入"


def recommend_action(row: PlatformStatus) -> str:
    if row.status == "加码":
        return "继续跑；复制高分关键词，适当提高该平台来源上限。"
    if row.status == "需清理":
        return "先清理旧帖，禁止 2026 年前内容进入线索池。"
    if row.status == "受阻":
        return "先降频或冷却；登录/验证码/403 不要连续重试。"
    if row.status == "降噪":
        return "收紧页面类型、时间和广告过滤；低质栏目页不要入池。"
    if row.status == "观察":
        return "保留小批量采集，观察是否能稳定产出高分线索。"
    if row.status == "低产":
        return "降频；连续低产就暂停，把资源给高产平台。"
    return "先接入公开来源或导入一批样本验证。"


def platform_sort_key(row: PlatformStatus) -> tuple[int, int, int, str]:
    rank = {"加码": 0, "观察": 1, "降噪": 2, "受阻": 3, "需清理": 4, "低产": 5, "未接入": 6}
    return (rank.get(row.status, 9), -row.quality_score, -row.usable_mentions, row.name.lower())


def platform_key_for_source(source: Source) -> str:
    name = source.name or ""
    for key, prefixes in SOURCE_PREFIX_MAP:
        if prefixes and name.startswith(prefixes):
            return key
    return platform_key_from_text(" ".join([name, source.url or ""]))


def platform_key_for_candidate(candidate: CandidateItem) -> str:
    if candidate.platform:
        return normalize_platform_key(candidate.platform)
    return platform_key_from_text(" ".join([candidate.source_name or "", candidate.canonical_url or ""]))


def platform_key_for_mention(mention: Mention) -> str:
    return platform_key_from_text(" ".join([mention.source_name or "", mention.canonical_url or ""]))


def platform_key_from_text(text: str) -> str:
    lowered = text.lower()
    host = ""
    for part in lowered.split():
        if part.startswith(("http://", "https://")):
            host = urlparse(part).netloc.lower()
            break
    haystack = f"{lowered} {host}"
    for key, keywords in HOST_KEYWORDS:
        if any(keyword and keyword.lower() in haystack for keyword in keywords):
            return key
    return normalize_platform_key(host or lowered.split(":", 1)[0])


def normalize_platform_key(value: str) -> str:
    key = value.strip().lower()
    key = key.replace("www.", "").replace("session ", "")
    aliases = {
        "amazon_seller_cn": "amazon_seller",
        "sellercentral.amazon.com": "amazon_seller",
        "shopify_community": "shopify",
        "community.shopify.com": "shopify",
        "octobrowser.net": "octobrowser",
        "gologin.com": "gologin",
        "adspower.com": "adspower",
        "amz123.com": "amz123",
        "cifnews.com": "cifnews",
        "m.cifnews.com": "cifnews",
        "segmentfault.com": "segmentfault",
        "blackhatworld.com": "blackhatworld",
        "apify.com": "apify",
        "multilogin.com": "multilogin",
        "tools.ikjzd.com": "ikjzd",
    }
    if key in aliases:
        return aliases[key]
    if "." in key:
        return key.split("/")[0].split(":")[0].replace(".", "_")
    return key.replace(" ", "_").replace("-", "_")[:80]


def display_name(key: str) -> str:
    if not key:
        return "未知来源"
    return key.replace("_", " ").title()


def latest_error(sources: list[Source]) -> str:
    for source in sorted(sources, key=lambda item: item.last_checked_at or item.created_at, reverse=True):
        if source.last_error:
            if "P11QualityDecision" in source.last_error:
                continue
            return source.last_error[:180]
    return ""


def is_blocked_error(error: str | None) -> bool:
    if not error:
        return False
    lowered = error.lower()
    return any(term in lowered for term in ["403", "401", "429", "forbidden", "rate limit", "captcha", "验证码"])
