from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.models import Source


@dataclass(frozen=True)
class HighYieldSource:
    name: str
    kind: str
    url: str
    group: str
    priority: int


@dataclass(frozen=True)
class HighYieldExpansionResult:
    created: int
    updated: int
    skipped: int
    total_templates: int
    names: list[str]


CN_BUYER_QUERIES = (
    "TikTok 小店 多账号 防关联",
    "TikTok 本土店 登录环境异常 住宅IP",
    "TikTok 矩阵 封号 住宅IP",
    "TikTok 养号 网络环境 代理IP",
    "亚马逊 多店铺 防关联 IP",
    "亚马逊 账号关联 被封 IP",
    "亚马逊 铺货团队 登录环境",
    "店群 防关联 IP 地址",
    "Shopee 店群 防关联",
    "Lazada 多账号 防关联",
    "Shopify 多店铺 支付风控 IP",
    "独立站群 IP 环境",
    "指纹浏览器 住宅IP 防关联",
    "AdsPower 住宅IP 配置",
    "比特浏览器 代理IP 防关联",
    "候鸟浏览器 代理IP 配置",
    "Hubstudio 代理IP 配置",
    "海外社媒矩阵 住宅IP",
    "Facebook 多账号 防关联",
    "Instagram 养号 代理IP",
    "海外账号注册 环境异常 代理",
    "账号养号 工作室 住宅IP",
    "爬虫 403 代理IP 被封",
    "Cloudflare 一直验证 代理IP",
    "爬虫 429 住宅IP",
    "代理IP 不稳定 换供应商",
    "动态住宅IP 测试包",
    "住宅代理 不稳定",
)

EN_BUYER_QUERIES = (
    "tiktok accounts residential proxy",
    "tiktok shop proxy account suspension",
    "amazon seller account proxy association",
    "amazon multiple accounts residential proxy",
    "shopify multiple stores proxy payment risk",
    "facebook accounts residential proxy",
    "instagram accounts proxy suspended",
    "antidetect browser residential proxy",
    "adspower residential proxy",
    "gologin residential proxy",
    "cloudflare 403 residential proxy",
    "scraping captcha residential proxy",
    "proxy blocked scraping",
    "rotating residential proxy blocked",
    "residential proxy account suspension",
    "need stable residential proxy",
)


def build_high_yield_sources(limit: int = 160) -> list[HighYieldSource]:
    rows: list[HighYieldSource] = []

    for query in CN_BUYER_QUERIES:
        encoded = quote(query)
        rows.extend(
            [
                HighYieldSource(
                    name=f"HQ WeAreSellers: {query}",
                    kind="html_links",
                    url=f"https://www.wearesellers.com/search?keyword={encoded}",
                    group="cross_border_cn",
                    priority=96,
                ),
                HighYieldSource(
                    name=f"HQ Amazon Seller CN: {query}",
                    kind="html_links",
                    url=f"https://sellercentral.amazon.com/seller-forums/discussions?locale=zh-CN&searchTerm={encoded}",
                    group="cross_border_cn",
                    priority=94,
                ),
                HighYieldSource(
                    name=f"HQ SegmentFault: {query}",
                    kind="html_links",
                    url=f"https://segmentfault.com/search?q={encoded}",
                    group="tech_cn",
                    priority=86,
                ),
                HighYieldSource(
                    name=f"HQ LearnKu: {query}",
                    kind="html_links",
                    url=f"https://learnku.com/search?q={encoded}",
                    group="tech_cn",
                    priority=80,
                ),
                HighYieldSource(
                    name=f"HQ Gitee: {query}",
                    kind="gitee_search",
                    url=query,
                    group="developer_cn",
                    priority=78,
                ),
                HighYieldSource(
                    name=f"HQ Zhihu: {query}",
                    kind="html_links",
                    url=f"https://www.zhihu.com/search?type=content&q={encoded}",
                    group="domestic_cn",
                    priority=72,
                ),
                HighYieldSource(
                    name=f"HQ Tieba: {query}",
                    kind="html_links",
                    url=f"https://tieba.baidu.com/f/search/res?ie=utf-8&qw={encoded}",
                    group="domestic_cn",
                    priority=70,
                ),
            ]
        )

    for query in EN_BUYER_QUERIES:
        encoded = quote(query)
        rows.extend(
            [
                HighYieldSource(
                    name=f"HQ GitHub Issues: {query}",
                    kind="github_search",
                    url=query,
                    group="developer_global",
                    priority=90,
                ),
                HighYieldSource(
                    name=f"HQ BlackHatWorld: {query}",
                    kind="html_links",
                    url=f"https://www.blackhatworld.com/search/1/?q={encoded}",
                    group="growth_forum_global",
                    priority=88,
                ),
                HighYieldSource(
                    name=f"HQ Reddit: {query}",
                    kind="html_links",
                    url=f"https://www.reddit.com/search/?q={encoded}&sort=new",
                    group="community_global",
                    priority=76,
                ),
                HighYieldSource(
                    name=f"HQ StackOverflow: {query}",
                    kind="html_links",
                    url=f"https://stackoverflow.com/search?q={encoded}",
                    group="developer_global",
                    priority=72,
                ),
            ]
        )

    rows.sort(key=lambda row: (-row.priority, row.name))
    return rows[: max(0, limit)]


def apply_high_yield_source_expansion(db: Session, limit: int = 120) -> HighYieldExpansionResult:
    templates = build_high_yield_sources(limit=limit)
    created = 0
    updated = 0
    skipped = 0
    names: list[str] = []

    for item in templates:
        source = db.query(Source).filter(Source.name == item.name[:120]).first()
        if source is None:
            db.add(
                Source(
                    name=item.name[:120],
                    kind=item.kind[:40],
                    url=item.url,
                    enabled=True,
                    quality_score=max(50, min(100, item.priority - 20)),
                    learned_priority=max(50, min(100, item.priority)),
                    quality_status="unchecked",
                    mode="high_yield_expansion",
                )
            )
            created += 1
            names.append(item.name[:120])
            continue

        changed = False
        if source.kind != item.kind:
            source.kind = item.kind[:40]
            changed = True
        if source.url != item.url:
            source.url = item.url
            changed = True
        if not source.enabled:
            source.enabled = True
            source.auto_disabled_at = None
            changed = True
        if (source.learned_priority or 0) < item.priority:
            source.learned_priority = max(50, min(100, item.priority))
            changed = True
        if changed:
            updated += 1
            names.append(item.name[:120])
        else:
            skipped += 1

    db.commit()
    return HighYieldExpansionResult(
        created=created,
        updated=updated,
        skipped=skipped,
        total_templates=len(templates),
        names=names,
    )
