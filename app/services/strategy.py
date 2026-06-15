from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Prospect, Source
from app.services import domestic_search_strategy as search_strategy
from app.services.analytics import (
    CustomerTypeAttribution,
    KeywordAttribution,
    SourceAttribution,
    build_customer_type_attribution,
    build_keyword_attribution,
    build_source_attribution,
)
from app.services.prospects import CUSTOMER_TYPE_LABELS


@dataclass(frozen=True)
class StrategyAction:
    priority: int
    kind: str
    title: str
    reason: str
    next_step: str

    @property
    def priority_label(self) -> str:
        if self.priority >= 85:
            return "马上做"
        if self.priority >= 65:
            return "本周做"
        return "观察"


@dataclass(frozen=True)
class KeywordSuggestion:
    phrase: str
    category: str
    weight: int
    reason: str
    priority: int


@dataclass(frozen=True)
class SourceSuggestion:
    name: str
    kind: str
    url: str
    reason: str
    priority: int


@dataclass(frozen=True)
class SalesBrief:
    due_followups: int
    high_score_new: int
    no_next_action: int
    trial_pending: int
    missing_contact: int
    active_pipeline: int


@dataclass(frozen=True)
class StrategyBoard:
    actions: list[StrategyAction]
    top_sources: list[SourceAttribution]
    weak_sources: list[SourceAttribution]
    top_keywords: list[KeywordAttribution]
    weak_keywords: list[KeywordAttribution]
    keyword_suggestions: list[KeywordSuggestion]
    source_suggestions: list[SourceSuggestion]
    top_customer_types: list[CustomerTypeAttribution]
    priority_prospects: list[Prospect]
    sales_brief: SalesBrief


def build_strategy_board(db: Session) -> StrategyBoard:
    source_rows = build_source_attribution(db)
    keyword_rows = build_keyword_attribution(db)
    customer_type_rows = build_customer_type_attribution(db)
    priority_prospects = load_priority_prospects(db)

    top_sources = [
        row
        for row in source_rows
        if row.prospects > 0 and (row.quality_score >= 70 or row.high_value_mentions >= 3 or row.trial_sent > 0 or row.won > 0)
    ][:10]
    weak_sources = [
        row
        for row in source_rows
        if row.mentions >= 3 and row.prospects == 0 and row.high_value_mentions == 0
    ][:10]
    top_keywords = [
        row
        for row in keyword_rows
        if row.prospects > 0 and (row.strategy_score >= 45 or row.high_value_mentions >= 3 or row.trial_sent > 0 or row.won > 0)
    ][:12]
    weak_keywords = [
        row
        for row in keyword_rows
        if row.mentions >= 4 and row.high_value_mentions == 0 and row.prospects == 0
    ][:12]
    keyword_suggestions = build_keyword_suggestions(db, customer_type_rows, keyword_rows)
    source_suggestions = build_source_suggestions(db, keyword_suggestions)
    top_customer_types = [
        row
        for row in customer_type_rows
        if row.prospects > 0
    ][:8]
    sales_brief = build_sales_brief(db)

    actions = build_actions(
        top_sources=top_sources,
        weak_sources=weak_sources,
        top_keywords=top_keywords,
        weak_keywords=weak_keywords,
        customer_types=top_customer_types,
        priority_prospects=priority_prospects,
    )
    return StrategyBoard(
        actions=actions,
        top_sources=top_sources,
        weak_sources=weak_sources,
        top_keywords=top_keywords,
        weak_keywords=weak_keywords,
        keyword_suggestions=keyword_suggestions,
        source_suggestions=source_suggestions,
        top_customer_types=top_customer_types,
        priority_prospects=priority_prospects,
        sales_brief=sales_brief,
    )


def build_actions(
    top_sources: list[SourceAttribution],
    weak_sources: list[SourceAttribution],
    top_keywords: list[KeywordAttribution],
    weak_keywords: list[KeywordAttribution],
    customer_types: list[CustomerTypeAttribution],
    priority_prospects: list[Prospect],
) -> list[StrategyAction]:
    actions: list[StrategyAction] = []

    if priority_prospects:
        actions.append(
            StrategyAction(
                priority=92,
                kind="销售执行",
                title=f"优先处理 {len(priority_prospects)} 个高分动态住宅 IP 客户",
                reason="这些客户已经满足产品匹配和分数门槛，继续堆数据前应该先推进触达、加微信或测试包。",
                next_step="打开跟进池，把状态从新客户推进到已筛选/已触达，并给每个客户补下一步动作。",
            )
        )

    if top_keywords:
        best = top_keywords[0]
        actions.append(
            StrategyAction(
                priority=88 if best.trial_sent or best.won else 76,
                kind="关键词加码",
                title=f"围绕「{best.keyword}」扩展同义词和平台搜索",
                reason=f"该词已带来 {best.high_value_mentions} 条高价值信号、{best.prospects} 个客户，策略分 {best.strategy_score}。",
                next_step="补充 5-10 个同义词，并优先加到卖家社区、技术问答、Gitee/GitHub Issue 搜索源。",
            )
        )

    if top_sources:
        best = top_sources[0]
        actions.append(
            StrategyAction(
                priority=84 if best.trial_sent or best.won else 72,
                kind="来源加码",
                title=f"复制「{best.source_name}」这类来源",
                reason=f"该来源已有 {best.high_value_mentions} 条高价值信号、{best.prospects} 个客户，质量分 {best.quality_score}。",
                next_step="找同平台相邻板块、相同搜索语法、同类社区标签，新增为受控来源。",
            )
        )

    if customer_types:
        best_type = customer_types[0]
        actions.append(
            StrategyAction(
                priority=80,
                kind="客户画像",
                title=f"把话术聚焦到「{best_type.label}」",
                reason=f"当前该类型客户数 {best_type.prospects}，平均分 {best_type.avg_score}，是现阶段最值得观察的画像。",
                next_step="为这个画像补一版更具体的首触达话术、测试包说明和异议处理。",
            )
        )

    if weak_sources:
        weak = weak_sources[0]
        actions.append(
            StrategyAction(
                priority=62,
                kind="来源降噪",
                title=f"复查低产来源「{weak.source_name}」",
                reason=f"该来源已有 {weak.mentions} 条入库，但没有形成客户或高价值信号。",
                next_step="如果连续审计仍低产，暂停该来源或收窄查询词。",
            )
        )

    if weak_keywords:
        weak_kw = weak_keywords[0]
        actions.append(
            StrategyAction(
                priority=58,
                kind="关键词降权",
                title=f"观察或降权「{weak_kw.keyword}」",
                reason=f"该词已出现 {weak_kw.mentions} 次，但没有高价值信号和客户画像。",
                next_step="检查是否过泛、是否吸引教程/新闻/同行文章，必要时改成更具体的痛点词。",
            )
        )

    return sorted(actions, key=lambda action: action.priority, reverse=True)


def load_priority_prospects(db: Session) -> list[Prospect]:
    return list(
        db.scalars(
            select(Prospect)
            .where(Prospect.product_fit.in_(["direct_dynamic_residential", "scenario_fit"]))
            .where(Prospect.lead_score >= 75)
            .where(Prospect.status.in_(["new", "qualified", "contacted", "wechat_added", "trial_sent", "follow_up"]))
            .order_by(desc(Prospect.lead_score), desc(Prospect.last_seen_at))
            .limit(20)
        )
    )


def build_sales_brief(db: Session) -> SalesBrief:
    today_end = datetime.combine(datetime.now().date(), datetime.max.time())
    base = (
        db.query(Prospect)
        .filter(Prospect.product_fit.in_(["direct_dynamic_residential", "scenario_fit"]))
        .filter(Prospect.lead_score >= 60)
        .filter(Prospect.status.notin_(["won", "invalid"]))
    )
    return SalesBrief(
        due_followups=base.filter(Prospect.next_follow_up_at.is_not(None)).filter(Prospect.next_follow_up_at <= today_end).count(),
        high_score_new=base.filter(Prospect.status == "new").filter(Prospect.lead_score >= 75).count(),
        no_next_action=base.filter(Prospect.next_action == "").filter(Prospect.status.in_(["new", "qualified", "contacted"])).count(),
        trial_pending=base.filter(Prospect.status == "trial_sent").count(),
        missing_contact=base.filter(Prospect.wechat == "").filter(Prospect.telegram == "").filter(Prospect.email == "").count(),
        active_pipeline=base.count(),
    )


def build_keyword_suggestions(
    db: Session,
    customer_type_rows: list[CustomerTypeAttribution] | None = None,
    keyword_rows: list[KeywordAttribution] | None = None,
) -> list[KeywordSuggestion]:
    from app.models import Keyword

    existing = {row.phrase.strip().lower() for row in db.query(Keyword).all()}
    active_customer_types = {row.customer_type: row for row in customer_type_rows or []}
    active_keywords = {row.keyword.lower(): row for row in keyword_rows or []}

    suggestions: list[KeywordSuggestion] = []
    for item in search_strategy.all_intent_keywords():
        if item.phrase.lower() in existing:
            continue
        boost = 0
        if item.category in {"buyer_intent", "pain"}:
            boost += 10
        if any(term in item.phrase.lower() for term in ["tiktok", "亚马逊", "店群", "指纹浏览器", "爬虫"]):
            boost += 8
        for row in active_customer_types.values():
            if row.customer_type in {"tiktok_matrix", "amazon_multi_account", "crawler_data", "antidetect_browser", "social_matrix"}:
                boost += min(row.prospects, 8)
        for keyword, row in active_keywords.items():
            if any(part.lower() in keyword for part in item.phrase.split() if len(part) >= 2):
                boost += min(row.high_value_mentions * 2, 10)
        suggestions.append(
            KeywordSuggestion(
                phrase=item.phrase,
                category=item.category,
                weight=item.weight,
                reason=item.reason,
                priority=max(30, min(100, item.weight + boost)),
            )
        )

    return sorted(suggestions, key=lambda row: row.priority, reverse=True)[:20]

    candidates = [
        ("TikTok 动态住宅 IP", "scenario", 30, "TikTok 矩阵/小店/养号更贴近动态住宅 IP 需求", ["tiktok_matrix"]),
        ("TikTok IP 防关联", "review", 32, "多账号防关联场景明确，适合人工审核后触达", ["tiktok_matrix"]),
        ("TikTok 小店 住宅 IP", "scenario", 28, "小店矩阵和直播运营常需要稳定环境", ["tiktok_matrix"]),
        ("亚马逊动态住宅 IP", "scenario", 32, "亚马逊多账号和铺货团队预算更高", ["cross_border_seller"]),
        ("亚马逊 IP 关联", "review", 35, "防关联痛点强，但需要人工判断合规边界", ["cross_border_seller"]),
        ("亚马逊 住宅代理 防关联", "review", 35, "直连产品价值，适合扩卖家社区来源", ["cross_border_seller"]),
        ("Shopee 动态住宅 IP", "scenario", 28, "东南亚店群量大，价格敏感但线索多", ["cross_border_seller"]),
        ("Shopify 店群 IP", "review", 28, "独立站群和多账号环境相关", ["cross_border_seller"]),
        ("指纹浏览器 动态住宅", "review", 35, "指纹浏览器用户通常理解 IP 环境价值", ["antidetect_browser"]),
        ("AdsPower 住宅 IP", "competitor", 28, "指纹浏览器生态里的代理需求更集中", ["antidetect_browser"]),
        ("Dolphin Anty 住宅代理", "competitor", 28, "海外矩阵团队常见工具相关词", ["antidetect_browser"]),
        ("Cloudflare 住宅代理", "pain", 32, "爬虫验证和风控拦截痛点强", ["crawler_data"]),
        ("Cloudflare 验证码 代理", "pain", 32, "明确反爬痛点，适合技术社区来源", ["crawler_data"]),
        ("Playwright 住宅代理", "scenario", 28, "开发者采集/自动化场景明确", ["crawler_data"]),
        ("Puppeteer 住宅代理", "scenario", 28, "开发者采集/自动化场景明确", ["crawler_data"]),
        ("爬虫 429 代理", "pain", 30, "频率限制痛点接近动态轮换需求", ["crawler_data"]),
        ("IP 被封 住宅代理", "pain", 35, "高痛点词，适合问答和 Issue 来源", ["crawler_data"]),
        ("社媒矩阵 住宅 IP", "review", 30, "社媒多账号环境需求接近动态住宅", ["social_matrix"]),
        ("Facebook 养号 IP", "review", 28, "社媒养号场景强但需人工审核", ["social_matrix"]),
        ("Instagram 多账号 IP", "review", 28, "社媒矩阵相关，适合私域线索筛选", ["social_matrix"]),
        ("动态住宅代理", "core", 35, "国内客户常用说法，比 residential proxy 更适合中文获客", ["crawler_data", "cross_border_seller"]),
        ("海外动态住宅IP", "core", 35, "直接对应你的业务，不偏静态住宅", ["crawler_data", "cross_border_seller"]),
        ("亚马逊 多店铺 防关联", "review", 34, "国内跨境卖家常见表达，适合卖家群和问答平台", ["cross_border_seller"]),
        ("店群 IP 防关联", "review", 33, "跨境店群和独立站群需求明确", ["cross_border_seller"]),
        ("指纹浏览器 住宅IP", "review", 35, "国内矩阵团队常围绕指纹浏览器找代理方案", ["antidetect_browser"]),
        ("AdsPower 代理IP", "scenario", 30, "国内用户常以工具名搜索代理需求", ["antidetect_browser"]),
        ("比特浏览器 代理IP", "scenario", 30, "国内指纹浏览器生态关键词", ["antidetect_browser"]),
        ("候鸟浏览器 代理IP", "scenario", 28, "国内指纹浏览器生态关键词", ["antidetect_browser"]),
        ("小红书 矩阵 IP", "review", 28, "小红书不适合无登录抓取，但适合人工导入和私域跟进", ["social_matrix"]),
        ("抖音 矩阵 IP", "review", 28, "抖音不适合无登录抓取，但适合人工导入和私域跟进", ["social_matrix"]),
    ]

    suggestions: list[KeywordSuggestion] = []
    for phrase, category, weight, reason, customer_types in candidates:
        if phrase.lower() in existing:
            continue
        boost = 0
        for customer_type in customer_types:
            row = active_customer_types.get(customer_type)
            if row:
                boost += min(row.prospects * 3, 18)
                boost += min(row.trial_sent * 8, 20)
                boost += min(row.won * 15, 30)
        for keyword, row in active_keywords.items():
            if any(part.lower() in keyword for part in phrase.split() if len(part) >= 3):
                boost += min(row.high_value_mentions * 2, 12)
        priority = max(30, min(100, weight + boost))
        suggestions.append(
            KeywordSuggestion(
                phrase=phrase,
                category=category,
                weight=weight,
                reason=reason,
                priority=priority,
            )
        )

    return sorted(suggestions, key=lambda item: item.priority, reverse=True)[:20]


def build_source_suggestions(
    db: Session,
    keyword_suggestions: list[KeywordSuggestion] | None = None,
) -> list[SourceSuggestion]:
    existing = {source.name.strip().lower() for source in db.query(Source).all()}
    suggestions: list[SourceSuggestion] = []

    for item in search_strategy.source_queries():
        if item.name.lower() in existing:
            continue
        suggestions.append(
            SourceSuggestion(
                name=item.name[:120],
                kind=item.kind,
                url=item.url,
                reason=item.reason,
                priority=item.priority,
            )
        )

    return sorted(suggestions, key=lambda row: row.priority, reverse=True)[:24]

    for item in (keyword_suggestions or build_keyword_suggestions(db))[:8]:
        source_candidates = [
            (
                f"GitHub Issues: {item.phrase}",
                "github_search",
                item.phrase,
                "开发者、爬虫、自动化团队的问题场景，适合发现真实报错和替代需求。",
                item.priority,
            ),
            (
                f"Gitee Issues: {item.phrase}",
                "gitee_search",
                item.phrase,
                "中文开发者和国内团队的问题场景，适合补齐国内市场信号。",
                item.priority - 2,
            ),
        ]
        if contains_chinese(item.phrase):
            encoded = quote(item.phrase)
            source_candidates.extend(
                [
                    (
                        f"Zhihu Search: {item.phrase}",
                        "html_links",
                        f"https://www.zhihu.com/search?type=content&q={encoded}",
                        "中文问答搜索，适合发现跨境、防关联、指纹浏览器、爬虫被封等求助。",
                        item.priority - 2,
                    ),
                    (
                        f"Baidu Tieba Search: {item.phrase}",
                        "html_links",
                        f"https://tieba.baidu.com/f/search/res?ie=utf-8&qw={encoded}",
                        "贴吧公开搜索，适合发现小团队和个人工作室需求。",
                        item.priority - 3,
                    ),
                    (
                        f"SegmentFault Search: {item.phrase}",
                        "html_links",
                        f"https://segmentfault.com/search?q={encoded}",
                        "中文技术问答搜索，适合采集爬虫、风控、验证码、代理异常等公开讨论。",
                        item.priority - 4,
                    ),
                    (
                        f"LearnKu Search: {item.phrase}",
                        "html_links",
                        f"https://learnku.com/search?q={encoded}",
                        "中文开发者社区搜索，适合补充技术型需求。",
                        item.priority - 6,
                    ),
                ]
            )

        for name, kind, url, reason, priority in source_candidates:
            if name.lower() in existing:
                continue
            suggestions.append(
                SourceSuggestion(
                    name=name[:120],
                    kind=kind,
                    url=url,
                    reason=reason,
                    priority=max(1, min(100, priority)),
                )
            )

    return sorted(suggestions, key=lambda item: item.priority, reverse=True)[:24]


def contains_chinese(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def customer_type_label(customer_type: str) -> str:
    return CUSTOMER_TYPE_LABELS.get(customer_type, customer_type)
