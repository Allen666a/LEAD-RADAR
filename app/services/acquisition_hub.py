from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Source
from app.services.ingest import run_domestic_acquisition_sync
from app.services.session_collector import load_tasks


@dataclass(frozen=True)
class SourceCoverage:
    key: str
    label: str
    description: str
    enabled: int
    total: int
    priority: int


SOURCE_GROUPS = (
    (
        "professional",
        "专业平台",
        "GitHub/Gitee、开发者问答、技术社区、爬虫和自动化问题源。",
        (
            "GitHub Issues:",
            "P30 GitHub Issues:",
            "Gitee Issues:",
            "P30 Gitee Issues:",
            "Gitee Intent:",
            "SegmentFault",
            "LearnKu",
            "CSDN",
            "OSChina",
            "CNBlogs",
            "V2EX",
        ),
        1,
    ),
    (
        "cross_border",
        "跨境卖家",
        "亚马逊、TikTok Shop、卖家论坛、外贸论坛、店群防关联场景。",
        (
            "Amazon Seller",
            "WeAreSellers",
            "WeAreSellers Search",
            "Amazon Seller Forum CN Search",
            "FOB Shanghai",
            "TikTok Seller",
            "AMZ123",
            "Yuguo",
            "SellerHome",
            "Ennews",
            "IKJZD",
            "Ebrun",
            "Egainnews",
            "Shopify Community Search",
            "Shopify Community",
            "eBay Community",
            "Etsy Community",
            "Walmart Seller",
            "Shopee Seller",
            "Lazada Seller",
        ),
        2,
    ),
    (
        "overseas_forums",
        "海外高意图论坛",
        "BlackHatWorld、Reddit、WarriorForum 等代理、多账号、爬虫和自动化需求源。",
        (
            "BlackHatWorld",
            "BlackHatWorld Search",
            "Reddit",
            "Reddit Search",
            "WarriorForum",
            "WarriorForum Search",
        ),
        3,
    ),
    (
        "crawler_anti_bot",
        "爬虫/反爬社区",
        "StackOverflow、Scrapy、Playwright、Puppeteer、Apify 等被封、验证码和代理轮换问题源。",
        (
            "StackOverflow",
            "StackOverflow Search",
            "Scrapy",
            "Playwright",
            "Puppeteer",
            "Apify",
            "P30 Bing Search",
        ),
        4,
    ),
    (
        "anti_detect",
        "防关联工具生态",
        "AdsPower、GoLogin、Dolphin、Multilogin、Octo、比特浏览器等代理配置和账号环境异常源。",
        (
            "AdsPower",
            "GoLogin",
            "Dolphin Anty",
            "Multilogin",
            "Octo Browser",
            "BitBrowser",
            "Hubstudio",
        ),
        5,
    ),
    (
        "domestic_search",
        "国内公开搜索",
        "知乎、贴吧等公开搜索结果，作为补充发现小团队和工作室需求。",
        (
            "Zhihu",
            "Baidu Tieba",
        ),
        6,
    ),
    (
        "social_session",
        "社媒补充",
        "小红书、抖音、B站、微博等登录后低频会话采集，只作为补充源。",
        (
            "Session 小红书",
            "Session 抖音",
            "Session B站",
            "Session 微博",
            "小红书",
            "抖音",
        ),
        7,
    ),
)


def build_source_coverage(db: Session) -> list[SourceCoverage]:
    sources = list(db.query(Source).all())
    session_tasks = load_tasks()
    rows: list[SourceCoverage] = []
    for key, label, description, prefixes, priority in SOURCE_GROUPS:
        matched = [source for source in sources if source.name.startswith(prefixes)]
        enabled = sum(1 for source in matched if source.enabled)
        total = len(matched)
        if key == "social_session":
            social_platforms = {"xiaohongshu", "douyin", "bilibili", "weibo"}
            social_tasks = [task for task in session_tasks if task.platform in social_platforms]
            enabled += sum(1 for task in social_tasks if task.enabled)
            total += len(social_tasks)
        rows.append(
            SourceCoverage(
                key=key,
                label=label,
                description=description,
                enabled=enabled,
                total=total,
                priority=priority,
            )
        )
    known_prefixes = tuple(prefix for *_, prefixes, _priority in SOURCE_GROUPS for prefix in prefixes)
    other = [source for source in sources if not source.name.startswith(known_prefixes)]
    if other:
        rows.append(
            SourceCoverage(
                key="other",
                label="其他公开源",
                description="RSS、普通网页和历史扩展源；质量不稳定时自动降权。",
                enabled=sum(1 for source in other if source.enabled),
                total=len(other),
                priority=9,
            )
        )
    return sorted(rows, key=lambda row: row.priority)


def run_unified_public_collection(
    db: Session,
    source_limit: int | None = None,
    force_run: bool = False,
    detail_fetch_limit_per_source: int | None = None,
) -> dict[str, int]:
    normalized_limit = None if source_limit is None or source_limit <= 0 else max(1, source_limit)
    return run_domestic_acquisition_sync(
        db,
        source_limit=normalized_limit,
        force_run=force_run,
        detail_fetch_limit_per_source=detail_fetch_limit_per_source,
    )
