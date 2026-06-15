from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import CandidateItem, Mention, Prospect
from app.services.ingest import run_ingestion
from app.services.prospects import CUSTOMER_TYPE_LABELS, rebuild_prospects
from app.services.session_collector import run_enabled_session_collections
from app.services.signals import HIGH_VALUE_SIGNALS

MIN_LEAD_YEAR = 2026


@dataclass(frozen=True)
class LeadSegment:
    key: str
    label: str
    description: str
    terms: tuple[str, ...]


@dataclass(frozen=True)
class LeadSourceScope:
    key: str
    label: str
    description: str
    prefixes: tuple[str, ...]
    uses_session: bool = False


@dataclass(frozen=True)
class LeadPool:
    key: str
    label: str
    description: str


@dataclass
class LeadFinderRow:
    id: int
    prospect_id: int | None
    title: str
    url: str
    source: str
    platform: str
    score: int
    signal_type: str
    status: str
    published_at: datetime | None
    discovered_at: datetime | None
    customer_type: str
    customer_label: str
    why: str
    next_step: str
    missing: str
    screening_label: str
    screening_tone: str
    time_label: str
    time_tone: str
    action_label: str
    action_kind: str
    row_type: str = "mention"
    detail_url: str = ""
    can_action: bool = True


@dataclass
class LeadFinderBoard:
    segments: list[LeadSegment]
    scopes: list[LeadSourceScope]
    pools: list[LeadPool]
    selected_segment: str
    selected_scope: str
    selected_pool: str
    min_score: int
    rows: list[LeadFinderRow]
    stats: dict[str, int]
    examples: list[str]
    message: str = ""


SEGMENTS = [
    LeadSegment(
        "all",
        "全部目标客户",
        "系统自动筛选所有动态住宅 IP 相关需求。",
        (),
    ),
    LeadSegment(
        "tiktok_matrix",
        "TikTok 矩阵/小店",
        "养号、小店、直播、带货、多账号防关联。",
        ("tiktok", "小店", "本土店", "直播", "养号", "矩阵", "防关联"),
    ),
    LeadSegment(
        "amazon_multi_account",
        "亚马逊多账号/铺货",
        "多店铺、铺货、防关联、账号关联和二审。",
        ("亚马逊", "amazon", "多账号", "多店铺", "铺货", "关联", "二审"),
    ),
    LeadSegment(
        "shopee_lazada_shein",
        "Shopee/Lazada/Shein 店群",
        "东南亚跨境店群、多账号、价格敏感型团队。",
        ("shopee", "lazada", "shein", "东南亚", "店群", "多账号"),
    ),
    LeadSegment(
        "crawler_data",
        "爬虫/数据采集团队",
        "403、429、验证码、Cloudflare、IP 被封。",
        ("爬虫", "数据采集", "403", "429", "cloudflare", "验证码", "ip 被封", "ip被封"),
    ),
    LeadSegment(
        "social_matrix",
        "海外社媒矩阵",
        "FB、IG、YouTube、X/Twitter、海外账号养号。",
        ("facebook", "fb", "instagram", "ig", "youtube", "twitter", "x ", "社媒", "养号"),
    ),
    LeadSegment(
        "shopify_independent",
        "独立站/Shopify",
        "Shopify、多站群、支付风控、广告投放环境。",
        ("shopify", "独立站", "站群", "支付风控", "广告投放"),
    ),
    LeadSegment(
        "account_service",
        "账号注册/养号服务商",
        "账号注册、海外账号、养号、环境异常。",
        ("账号注册", "养号", "海外账号", "环境异常", "登录环境"),
    ),
]


SCOPES = [
    LeadSourceScope(
        "domestic",
        "国内优先",
        "先找中文平台和国内社区，方便沟通。",
        (
            "V2EX Tag:",
            "V2EX Intent:",
            "SegmentFault Search:",
            "SegmentFault Intent:",
            "LearnKu Search:",
            "LearnKu Intent:",
            "Gitee Issues:",
            "Gitee Intent:",
            "Zhihu Search:",
            "Zhihu Intent:",
            "Baidu Tieba Search:",
            "Baidu Tieba Intent:",
            "CSDN Search Intent:",
            "OSChina Intent:",
            "CNBlogs Intent:",
        ),
    ),
    LeadSourceScope(
        "logged_in",
        "已登录平台",
        "使用你已登录的平台会话，低频读取公开搜索结果。",
        ("Session ",),
        uses_session=True,
    ),
    LeadSourceScope(
        "technical",
        "技术社区",
        "适合爬虫、采集、Cloudflare、代理异常线索。",
        (
            "V2EX",
            "V2EX Tag:",
            "V2EX Intent:",
            "SegmentFault Search:",
            "SegmentFault Intent:",
            "LearnKu Search:",
            "LearnKu Intent:",
            "Gitee Issues:",
            "Gitee Intent:",
            "GitHub Issues:",
            "GitHub Search:",
        ),
    ),
    LeadSourceScope(
        "crossborder",
        "跨境卖家",
        "适合 TikTok、亚马逊、店群和独立站场景。",
        (
            "WeAreSellers:",
            "WeAreSellers Intent:",
            "Amazon Seller Forum CN:",
            "FOB Shanghai:",
            "Zhihu Search:",
            "Zhihu Intent:",
            "Baidu Tieba Search:",
            "Baidu Tieba Intent:",
        ),
    ),
    LeadSourceScope("all", "全部来源", "使用全部已启用来源，适合高级用户。", ()),
]

POOLS = [
    LeadPool("usable", "全部可用线索", "主线索池和待复核池一起看，排除垃圾，适合人工挑选获客。"),
    LeadPool("main", "主线索池", "高确定性线索，适合直接进入补联系方式和跟进。"),
    LeadPool("review", "待复核池", "可能是客户但证据不足，防止误杀。"),
    LeadPool("invalid", "垃圾池", "广告、教程、旧帖、工程噪音等低价值内容。"),
    LeadPool("all", "全部", "包含主池、待复核和垃圾池，用于审计。"),
]

CHINESE_LEAD_PREFIXES = (
    "Zhihu Intent:",
    "Baidu Tieba Intent:",
    "WeAreSellers Search:",
    "WeAreSellers Intent:",
    "P34 WeAreSellers Intent:",
    "SegmentFault Search:",
    "SegmentFault Intent:",
    "LearnKu Search:",
    "LearnKu Intent:",
    "CSDN Search Intent:",
    "Gitee Issues:",
    "Gitee Intent:",
    "V2EX Tag:",
    "V2EX Intent:",
    "Session 知乎:",
    "Session 百度贴吧:",
    "Session 小红书:",
    "Session 抖音:",
    "Session B站:",
    "Session 微博:",
)

CHINESE_DYNAMIC_IP_TERMS = (
    "ip",
    "代理",
    "住宅",
    "动态住宅",
    "住宅ip",
    "住宅 IP",
    "指纹浏览器",
    "adspower",
    "bitbrowser",
    "hubstudio",
    "候鸟浏览器",
    "登录环境",
    "网络环境",
    "网络设备",
    "家宽",
    "环境异常",
    "防关联",
    "账号关联",
    "店铺关联",
    "封号",
    "被封",
    "验证码",
    "cloudflare",
    "403",
    "429",
    "爬虫",
)

STRONG_LEAD_CONTEXT_TERMS = (
    "动态住宅",
    "住宅ip",
    "住宅 ip",
    "家宽",
    "指纹浏览器",
    "adspower",
    "bitbrowser",
    "hubstudio",
    "登录环境",
    "网络环境",
    "环境异常",
    "防关联",
    "账号关联",
    "店铺关联",
    "封号",
    "被封",
    "验证码",
    "cloudflare",
    "403",
    "429",
    "residential proxy",
    "residential proxies",
    "rotating proxy",
    "rotating proxies",
    "mobile proxy",
    "mobile proxies",
    "anti detect",
    "antidetect",
    "account suspension",
    "ip blocked",
    "captcha",
)

DIRECT_PROXY_NEED_TERMS = (
    "动态住宅",
    "住宅ip",
    "住宅 ip",
    "家宽",
    "代理ip",
    "代理 ip",
    "代理池",
    "socks5",
    "指纹浏览器",
    "adspower",
    "bitbrowser",
    "候鸟浏览器",
    "登录环境",
    "网络环境",
    "网络设备",
    "网络问题",
    "环境异常",
    "防关联",
    "账号关联",
    "店铺关联",
    "ip 被封",
    "ip被封",
    "验证码",
    "cloudflare",
    "403",
    "429",
    "residential proxy",
    "residential proxies",
    "rotating proxy",
    "rotating proxies",
    "mobile proxy",
    "mobile proxies",
    "proxy pool",
    "socks5",
    "captcha",
    "ip blocked",
    "banned",
)

REVIEW_CANDIDATE_TERMS = (
    "动态住宅",
    "住宅ip",
    "住宅 ip",
    "家宽",
    "代理ip",
    "代理 ip",
    "代理池",
    "指纹浏览器",
    "防关联",
    "账号关联",
    "店铺关联",
    "登录环境",
    "网络环境",
    "环境异常",
    "ip 被封",
    "ip被封",
    "验证码",
    "cloudflare",
    "403",
    "429",
    "爬虫",
    "采集",
    "residential proxy",
    "residential proxies",
    "rotating proxy",
    "rotating proxies",
    "mobile proxy",
    "proxy pool",
    "anti detect",
    "antidetect",
    "captcha",
    "ip blocked",
)

REVIEW_BUYER_TERMS = (
    "求推荐",
    "有没有",
    "哪家",
    "哪里",
    "怎么解决",
    "如何解决",
    "稳定",
    "不稳定",
    "被封",
    "封号",
    "关联",
    "风控",
    "失败",
    "购买",
    "采购",
    "替换",
    "looking for",
    "recommend",
    "best",
    "how to",
    "need",
    "blocked",
    "suspended",
    "failed",
)

REVIEW_HARD_NOISE_TERMS = (
    "官网",
    "排行榜",
    "十大",
    "测评",
    "评测",
    "教程",
    "培训",
    "课程",
    "招商",
    "代运营",
    "广告代运营",
    "广告开户",
    "免费试用",
    "福利",
    "优惠",
    "read the rules",
    "rules clarification",
    "subscriptions and prices",
)

ACTIONABLE_BUYER_TERMS = (
    "求推荐",
    "有没有",
    "哪家",
    "哪里",
    "怎么买",
    "采购",
    "购买",
    "报价",
    "试用",
    "测试",
    "换代理",
    "找代理",
    "不稳定",
    "被封",
    "封号",
    "过不去",
    "怎么解决",
    "如何解决",
    "need",
    "looking for",
    "recommend",
    "best proxy",
    "where can",
    "how to solve",
)

PLATFORM_SCENE_TERMS = (
    "tiktok",
    "小店",
    "亚马逊",
    "amazon",
    "shopee",
    "lazada",
    "shopify",
    "facebook",
    "instagram",
    "youtube",
    "x/twitter",
    "多账号",
    "多店铺",
    "店群",
    "矩阵",
    "爬虫",
    "采集",
)

WEAK_CONTENT_TERMS = (
    "广告节奏",
    "广告数据",
    "选品",
    "品牌备案",
    "合作的本质",
    "库存",
    "上架",
    "申诉",
    "运营节奏",
    "运营系统",
    "ai 提效",
    "基于 ai 进行提效",
    "opc 这个事",
    "教程",
    "培训",
    "课程",
    "排行榜",
    "测评",
    "官网",
    "解决方案",
    "provider adapter",
    "selenium it suite",
    "youtube data api",
    "railway deployment",
    "dead code",
    "provider adapter",
    "scraper resiliency",
)

GITHUB_ENGINEERING_TITLE_PREFIXES = (
    "add ",
    "enhance ",
    "fix ",
    "feat",
    "refactor",
    "do not ",
    "dead code",
    "cmd ",
    "implement ",
    "replace ",
    "remove ",
)

AD_OR_NOISE_TERMS = (
    "广告代运营",
    "广告开户",
    "代投",
    "代运营",
    "招商",
    "加盟",
    "优惠",
    "限时",
    "全网低价",
    "免费测试",
    "免费试用",
    "内附福利",
    "注册即送",
    "联系我们",
    "联系客服",
    "官网",
    "排行榜",
    "十大",
    "测评",
    "评测",
    "推荐榜",
    "教程",
    "培训",
    "课程",
    "公开课",
    "直播课",
    "下载",
    "解决方案",
    "来试试",
    "必备",
    "干货",
    "read the rules",
    "rules clarification",
    "unit coverage",
    "split scraper",
    "test suite",
    "p0:",
    "p1 ",
    "p2 ",
    "mango proxy",
    "ipfighter",
    "scraperapi",
    "proxy-seller",
    "proxy seller",
)

BUYER_OR_PAIN_TERMS = (
    "求",
    "怎么",
    "如何",
    "哪里",
    "有没有",
    "推荐",
    "被封",
    "封号",
    "关联",
    "风控",
    "验证",
    "失败",
    "不稳定",
    "解决",
    "换",
    "需要",
    "采购",
    "购买",
)


def is_chinese_lead_source(mention: Mention) -> bool:
    return (mention.source_name or "").startswith(CHINESE_LEAD_PREFIXES)


def mention_text(mention: Mention, *, include_source: bool = True) -> str:
    parts = [
        mention.title or "",
        mention.content or "",
        mention.score_reasons or "",
        mention.recommendation or "",
    ]
    if include_source:
        parts.extend(
            [
                mention.matched_keywords or "",
                mention.source_name or "",
            ]
        )
    return "\n".join(parts)


def has_dynamic_ip_context(mention: Mention) -> bool:
    text = "\n".join([mention.title or "", mention.content or ""]).lower()
    for term in CHINESE_DYNAMIC_IP_TERMS:
        needle = term.lower()
        if needle == "ip":
            if re.search(r"(?<![a-z])ip(?![a-z])", text):
                return True
            continue
        if needle in text:
            return True
    return False


def looks_like_ad_or_noise(mention: Mention) -> bool:
    text = mention_text(mention).lower()
    title = (mention.title or "").lower()
    url = (mention.canonical_url or "").lower()
    if is_index_or_profile_page(url, title):
        return True
    if has_hard_title_noise(title):
        return True
    generic_supplier_title = any(
        phrase in title
        for phrase in (
            "rotating residential proxies",
            "residential proxies:",
            "mango proxy",
            "ipfighter",
            "read the full",
            "read the rules",
            "rules clarification",
        )
    ) and not any(term in title for term in ("?", "how", "need", "looking", "recommend", "best way"))
    if generic_supplier_title:
        return True
    has_noise = any(term.lower() in text for term in AD_OR_NOISE_TERMS)
    if not has_noise:
        return False
    has_buyer_or_pain = any(term.lower() in text for term in BUYER_OR_PAIN_TERMS)
    supplier_brand_noise = any(
        brand in title
        for brand in (
            "novproxy",
            "kookeey",
            "922s5",
            "iproyal",
            "bright data",
            "oxylabs",
            "smartproxy",
            "soax",
            "mango proxy",
            "ipfighter",
            "scraperapi",
            "proxy-seller",
            "proxy seller",
        )
    ) and any(term in title for term in ("住宅", "代理", "ip", "proxy", "动态", "免费", "福利", "解决方案"))
    bracketed_promo = title.startswith("[") and any(term in title for term in ("干货", "独立开发", "福利", "免费测试"))
    engineering_noise = any(
        term in title
        for term in (
            "unit coverage",
            "split scraper",
            "test suite",
            "handler.py",
            "lambda data-plane",
            "我 port",
            "i port",
            "作品展示",
            "p0:",
            "p1 ",
            "p2 ",
        )
    )
    generic_rule_page = any(term in title for term in ("read the rules", "rules clarification"))
    v2ex_ad = "advertisement" in text and any(term in title for term in ("福利", "推广", "9.9", "注册即送", "免费", "住宅 ip"))
    return supplier_brand_noise or bracketed_promo or engineering_noise or generic_rule_page or v2ex_ad or not has_buyer_or_pain


def has_hard_title_noise(title: str) -> bool:
    return any(
        term.lower() in title
        for term in (
            "代运营",
            "招商",
            "优惠",
            "福利",
            "免费测试",
            "排行榜",
            "十大",
            "测评",
            "评测",
            "教程",
            "培训",
            "课程",
            "官网",
            "解决方案",
            "来试试",
            "推广",
            "注册即送",
            "免费流量",
            "9.9 元起",
            "疯抢",
            "到底有多香",
            "我 port",
            "i port",
            "作品展示",
            "dead code",
            "provider adapter",
            "ai 提效",
            "基于 ai 进行提效",
            "opc 这个事",
        )
    )


def is_index_or_profile_page(url: str, title: str) -> bool:
    if any(part in url for part in ("/category", "/categories", "/tag/", "/tags/", "/members/", "/users/")):
        if len(title) <= 80 or any(term in title for term in ("shopify", "proxy", "proxies", "ip", "用户", "标签", "分类")):
            return True
    if any(part in url for part in ("/forums/", "/forum/")) and not any(part in url for part in ("/threads/", "/posts/", "/question/")):
        return True
    return False


def usable_display_mention(mention: Mention, pool: str) -> bool:
    if pool == "invalid":
        return True
    if not is_fresh_lead(mention):
        return False
    if looks_like_ad_or_noise(mention):
        return False
    if is_chinese_lead_source(mention) and not has_dynamic_ip_context(mention):
        return False
    if is_engineering_task_without_buyer_need(mention):
        return False
    return True


def candidate_text(candidate: CandidateItem) -> str:
    return "\n".join(
        [
            candidate.title or "",
            candidate.content or "",
            candidate.detail_excerpt or "",
            candidate.source_name or "",
            candidate.platform or "",
        ]
    ).lower()


def candidate_has_chinese(candidate: CandidateItem) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", " ".join([candidate.title or "", candidate.content or ""])))


def candidate_has_review_need(candidate: CandidateItem) -> bool:
    text = candidate_text(candidate)
    return any(term.lower() in text for term in REVIEW_CANDIDATE_TERMS)


def candidate_has_buyer_language(candidate: CandidateItem) -> bool:
    text = candidate_text(candidate)
    return any(term.lower() in text for term in REVIEW_BUYER_TERMS)


def candidate_is_hard_noise(candidate: CandidateItem) -> bool:
    title = (candidate.title or "").lower()
    text = candidate_text(candidate)
    if any(term.lower() in title for term in REVIEW_HARD_NOISE_TERMS):
        return True
    if candidate.failure_type in {"old_content", "duplicate", "invalid_path"}:
        return True
    if candidate.detail_status == "not_detail" and not candidate_has_buyer_language(candidate):
        return True
    if candidate.source_kind == "html_links" and not candidate_has_buyer_language(candidate):
        return True
    supplier_like = any(
        brand in title
        for brand in (
            "bright data",
            "oxylabs",
            "smartproxy",
            "iproyal",
            "mango proxy",
            "ipfighter",
            "proxy-seller",
            "proxy seller",
        )
    )
    return supplier_like and not candidate_has_buyer_language(candidate)


def is_review_candidate(candidate: CandidateItem) -> bool:
    if candidate.mention_id:
        return False
    if candidate.published_at is None or candidate.published_at.year < MIN_LEAD_YEAR:
        return False
    if candidate_is_hard_noise(candidate):
        return False
    if not candidate_has_review_need(candidate):
        return False
    if candidate_has_buyer_language(candidate):
        return True
    return (candidate.score or 0) >= 65 and candidate.failure_type in {"low_intent", "not_detail", "review_required", ""}


def candidate_pool(candidate: CandidateItem) -> str:
    if candidate_is_hard_noise(candidate):
        return "invalid"
    if is_review_candidate(candidate):
        return "review"
    return "invalid"


def is_fresh_lead(mention: Mention) -> bool:
    return mention.published_at is not None and mention.published_at.year >= MIN_LEAD_YEAR


def has_strong_lead_context(mention: Mention) -> bool:
    text = mention_primary_text(mention).lower()
    return any(term.lower() in text for term in STRONG_LEAD_CONTEXT_TERMS)


def has_direct_proxy_need(mention: Mention) -> bool:
    text = mention_primary_text(mention).lower()
    return any(term.lower() in text for term in DIRECT_PROXY_NEED_TERMS)


def has_actionable_buyer_language(mention: Mention) -> bool:
    text = mention_primary_text(mention).lower()
    return any(term.lower() in text for term in ACTIONABLE_BUYER_TERMS)


def has_platform_scene(mention: Mention) -> bool:
    text = mention_primary_text(mention).lower()
    return any(term.lower() in text for term in PLATFORM_SCENE_TERMS)


def has_weak_content_shape(mention: Mention) -> bool:
    text = mention_primary_text(mention).lower()
    return any(term.lower() in text for term in WEAK_CONTENT_TERMS)


def is_engineering_task_without_buyer_need(mention: Mention) -> bool:
    title = (mention.title or "").lower().strip()
    source = (mention.source_name or "").lower()
    if "github" not in source and "github.com" not in (mention.canonical_url or "").lower():
        return False
    if not title.startswith(GITHUB_ENGINEERING_TITLE_PREFIXES):
        return False
    title_has_pain = any(term in title for term in ("fail", "failing", "failed", "blocked", "403", "captcha", "cloudflare", "proxy"))
    return not title_has_pain


def mention_primary_text(mention: Mention) -> str:
    return "\n".join([mention.title or "", mention.content or ""])


def sales_action_score(mention: Mention, prospect: Prospect | None) -> int:
    score = max(mention.priority_score or 0, mention.score or 0)
    direct_proxy = has_direct_proxy_need(mention)
    buyer_language = has_actionable_buyer_language(mention)
    platform_scene = has_platform_scene(mention)
    weak_content = has_weak_content_shape(mention)

    if direct_proxy and buyer_language:
        score += 16
    elif direct_proxy:
        score += 8
    if platform_scene and direct_proxy:
        score += 8
    if mention.signal_type in {"buyer_intent", "pain_signal"}:
        score += 6
    if weak_content and not direct_proxy:
        score -= 35
    elif weak_content and not buyer_language:
        score -= 18
    if weak_content and not direct_proxy:
        score = min(score, 48)
    if platform_scene and not direct_proxy and not buyer_language:
        score = min(score, 58)
    if mention.signal_type == "competitor_signal" and not buyer_language:
        score = min(score, 62)
    if looks_like_ad_or_noise(mention):
        score = min(score, 35)
    return max(0, min(100, score))


def sort_key_for_lead(mention: Mention, prospect: Prospect | None) -> tuple:
    score = sales_action_score(mention, prospect)
    published_ts = int(mention.published_at.timestamp()) if mention.published_at else 0
    discovered_ts = int(mention.discovered_at.timestamp()) if mention.discovered_at else 0
    return (
        0 if is_chinese_lead_source(mention) else 1,
        0 if has_dynamic_ip_context(mention) else 1,
        0 if is_fresh_lead(mention) else 1,
        -score,
        0 if mention.status not in {"review", "invalid"} else 1,
        -published_ts,
        -discovered_ts,
    )


def sort_key_for_row(row: LeadFinderRow) -> tuple:
    published_ts = int(row.published_at.timestamp()) if row.published_at else 0
    discovered_ts = int(row.discovered_at.timestamp()) if row.discovered_at else 0
    return (
        0 if candidate_has_chinese_like(row) else 1,
        0 if row.row_type == "mention" else 1,
        0 if row.status not in {"invalid"} else 1,
        -row.score,
        -published_ts,
        -discovered_ts,
    )


def candidate_has_chinese_like(row: LeadFinderRow) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", f"{row.title} {row.why} {row.source}"))


def build_lead_finder_board(
    db: Session,
    *,
    segment: str = "all",
    scope: str = "all",
    pool: str = "usable",
    min_score: int = 0,
    message: str = "",
) -> LeadFinderBoard:
    segment = segment if any(item.key == segment for item in SEGMENTS) else "all"
    scope = scope if any(item.key == scope for item in SCOPES) else "all"
    pool = pool if any(item.key == pool for item in POOLS) else "usable"
    min_score = max(0, min(100, min_score))

    prospects = {row.id: row for row in db.scalars(select(Prospect)).all()}
    base_mentions = list(db.scalars(
        select(Mention)
        .where(Mention.published_at.is_not(None))
        .order_by(desc(Mention.discovered_at))
        .limit(2000)
    ))
    base_candidates = list(
        db.scalars(
            select(CandidateItem)
            .where(CandidateItem.published_at.is_not(None))
            .order_by(desc(CandidateItem.fetched_at))
            .limit(3000)
        )
    )
    matched_mentions: list[tuple[Mention, Prospect | None]] = []
    for mention in base_mentions:
        if not matches_pool(mention, pool):
            continue
        if not usable_display_mention(mention, pool):
            continue
        if mention.score < min_score:
            continue
        prospect = prospects.get(mention.prospect_id or 0)
        if not matches_scope(mention, scope):
            continue
        if not matches_segment(mention, prospect, segment):
            continue
        matched_mentions.append((mention, prospect))

    matched_mentions.sort(key=lambda item: sort_key_for_lead(item[0], item[1]))
    matched_rows = [to_row(mention, prospect) for mention, prospect in matched_mentions]

    candidate_rows: list[LeadFinderRow] = []
    if pool in {"usable", "review", "all"}:
        for candidate in base_candidates:
            c_pool = candidate_pool(candidate)
            if pool == "review" and c_pool != "review":
                continue
            if pool == "usable" and c_pool != "review":
                continue
            if pool == "all" and c_pool not in {"review", "invalid"}:
                continue
            if (candidate.score or 0) < min_score:
                continue
            if not matches_candidate_scope(candidate, scope):
                continue
            if not matches_candidate_segment(candidate, segment):
                continue
            candidate_rows.append(candidate_to_row(candidate))

    all_rows = matched_rows + candidate_rows
    all_rows.sort(key=sort_key_for_row)
    rows = all_rows[:120]

    stats = {
        "results": len(all_rows),
        "shown": len(rows),
        "fresh": sum(1 for row in all_rows if row.published_at and row.published_at.year >= 2026),
        "high": sum(1 for row in all_rows if row.score >= 80),
        "missing_contact": sum(1 for row in all_rows if row.missing),
        "main_pool": sum(
            1 for mention in base_mentions if matches_pool(mention, "main") and usable_display_mention(mention, "main")
        ),
        "review_pool": sum(1 for row in all_rows if row.status in {"review", "candidate_review"}),
        "invalid_pool": sum(1 for mention in base_mentions if matches_pool(mention, "invalid")),
        "candidate_review": len(candidate_rows),
    }
    selected = next((item for item in SEGMENTS if item.key == segment), SEGMENTS[0])
    return LeadFinderBoard(
        segments=SEGMENTS,
        scopes=SCOPES,
        pools=POOLS,
        selected_segment=segment,
        selected_scope=scope,
        selected_pool=pool,
        min_score=min_score,
        rows=rows,
        stats=stats,
        examples=list(selected.terms[:5]),
        message=message,
    )


def run_lead_finder_search(
    db: Session,
    *,
    segment: str,
    scope: str,
    source_limit: int | None = None,
) -> dict[str, object]:
    scope_row = next((item for item in SCOPES if item.key == scope), SCOPES[0])
    if scope_row.uses_session:
        result = run_enabled_session_collections(
            db,
            platform_limit=2,
            keyword_limit=1,
            per_platform_limit=5,
            headless=True,
        )
    else:
        prefixes = scope_row.prefixes
        result = asyncio.run(
            run_ingestion(
                db,
                source_prefixes=prefixes,
                source_limit=source_limit,
                force_run=True,
                detail_fetch_limit_per_source=8,
            )
        )
    rebuild_prospects(db)
    result["segment"] = segment
    result["scope"] = scope
    return result


def matches_scope(mention: Mention, scope: str) -> bool:
    if scope == "all":
        return True
    scope_row = next((item for item in SCOPES if item.key == scope), SCOPES[0])
    return mention.source_name.startswith(scope_row.prefixes)


def matches_candidate_scope(candidate: CandidateItem, scope: str) -> bool:
    if scope == "all":
        return True
    scope_row = next((item for item in SCOPES if item.key == scope), SCOPES[0])
    return (candidate.source_name or "").startswith(scope_row.prefixes)


def matches_pool(mention: Mention, pool: str) -> bool:
    if pool == "all":
        return True
    if pool == "usable":
        return mention.status != "invalid"
    if pool == "review":
        return mention.status == "review"
    if pool == "invalid":
        return mention.status == "invalid"
    return mention.status not in {"review", "invalid"}


def matches_segment(mention: Mention, prospect: Prospect | None, segment: str) -> bool:
    if segment == "all":
        return True
    if prospect and prospect.customer_type == segment:
        return True
    selected = next((item for item in SEGMENTS if item.key == segment), None)
    if selected is None:
        return True
    haystack = f"{mention.title}\n{mention.content}\n{mention.matched_keywords}\n{mention.score_reasons}".lower()
    return any(term.lower() in haystack for term in selected.terms)


def matches_candidate_segment(candidate: CandidateItem, segment: str) -> bool:
    if segment == "all":
        return True
    selected = next((item for item in SEGMENTS if item.key == segment), None)
    if selected is None:
        return True
    haystack = candidate_text(candidate)
    return any(term.lower() in haystack for term in selected.terms)


def to_row(mention: Mention, prospect: Prospect | None) -> LeadFinderRow:
    customer_type = prospect.customer_type if prospect else "unknown"
    customer_label = CUSTOMER_TYPE_LABELS.get(customer_type, customer_type or "未识别")
    return LeadFinderRow(
        id=mention.id,
        prospect_id=mention.prospect_id,
        title=mention.title,
        url=mention.canonical_url,
        source=mention.source_name,
        platform=prospect.platform if prospect else platform_from_source(mention),
        score=sales_action_score(mention, prospect),
        signal_type=mention.signal_type,
        status=mention.status,
        published_at=mention.published_at,
        discovered_at=mention.discovered_at,
        customer_type=customer_type,
        customer_label=customer_label,
        why=lead_reason(mention, prospect),
        next_step=next_step_for(mention, prospect),
        missing=missing_contact(prospect),
        screening_label=screening_label(mention, prospect),
        screening_tone=screening_tone(mention, prospect),
        time_label=time_label(mention),
        time_tone=time_tone(mention),
        action_label=primary_action_label(mention, prospect),
        action_kind=primary_action_kind(mention, prospect),
        row_type="mention",
        detail_url=f"/mentions/{mention.id}",
        can_action=True,
    )


def candidate_to_row(candidate: CandidateItem) -> LeadFinderRow:
    reason = candidate.gate_reason or candidate.detail_reason or candidate.failure_type or "需要人工确认是否是真需求。"
    source = candidate.source_name or candidate.platform or candidate.source_kind or "candidate"
    platform = candidate.platform or candidate.source_kind or "-"
    score = max(30, min(88, candidate.score or 45))
    if candidate_has_buyer_language(candidate):
        score = min(92, score + 8)
    if candidate_has_chinese(candidate):
        score = min(95, score + 4)
    return LeadFinderRow(
        id=candidate.id,
        prospect_id=None,
        title=candidate.title or candidate.canonical_url or "-",
        url=candidate.canonical_url or "",
        source=source,
        platform=platform,
        score=score,
        signal_type=candidate.signal_type or "community_signal",
        status="candidate_review",
        published_at=candidate.published_at,
        discovered_at=candidate.fetched_at,
        customer_type="unknown",
        customer_label="待判断候选",
        why=compact_sentence(reason, 220),
        next_step="先打开原文确认是否是真需求；确认后再补联系方式或标记无效。",
        missing="人工确认",
        screening_label="待判断候选",
        screening_tone="warn",
        time_label=candidate_time_label(candidate),
        time_tone="good" if candidate.published_at and candidate.published_at.year >= MIN_LEAD_YEAR else "warn",
        action_label="打开原文",
        action_kind="open_source",
        row_type="candidate",
        detail_url=f"/candidates/{candidate.id}",
        can_action=False,
    )


def candidate_time_label(candidate: CandidateItem) -> str:
    if candidate.published_at is None:
        return "时间待核验"
    if candidate.published_at.year >= MIN_LEAD_YEAR:
        return "2026 新候选"
    return f"{candidate.published_at.year} 旧候选"


def lead_reason(mention: Mention, prospect: Prospect | None) -> str:
    if prospect and prospect.evidence:
        return compact_sentence(prospect.evidence)
    if mention.recommendation:
        return compact_sentence(mention.recommendation)
    if mention.score_reasons:
        return compact_sentence(mention.score_reasons)
    if mention.signal_type in HIGH_VALUE_SIGNALS:
        return "命中高价值需求信号，建议人工确认场景和联系方式。"
    return "命中动态住宅 IP 相关讨论，建议先人工判断。"


def next_step_for(mention: Mention, prospect: Prospect | None) -> str:
    missing = missing_contact(prospect)
    if missing:
        return f"先补{missing}，再轻触达。"
    if prospect and prospect.suggested_action:
        return compact_sentence(prospect.suggested_action)
    if mention.recommendation:
        return compact_sentence(mention.recommendation)
    return "打开原文，确认平台、国家、并发量和当前代理痛点。"


def screening_label(mention: Mention, prospect: Prospect | None) -> str:
    if mention.published_at and mention.published_at.year < 2026:
        return "旧线索"
    if mention.score >= 80:
        return "优先看"
    if prospect and prospect.product_fit in {"direct_dynamic_residential", "scenario_fit"}:
        return "场景匹配"
    if mention.score < 60:
        return "先复核"
    return "可观察"


def screening_tone(mention: Mention, prospect: Prospect | None) -> str:
    label = screening_label(mention, prospect)
    if label in {"优先看", "场景匹配"}:
        return "good"
    if label in {"旧线索", "先复核"}:
        return "warn"
    return "neutral"


def time_label(mention: Mention) -> str:
    if mention.published_at is None:
        return "时间未知"
    if mention.published_at.year >= 2026:
        return "2026 新线索"
    return f"{mention.published_at.year} 旧线索"


def time_tone(mention: Mention) -> str:
    if mention.published_at and mention.published_at.year >= 2026:
        return "good"
    return "warn"


def primary_action_label(mention: Mention, prospect: Prospect | None) -> str:
    if mention.status == "review":
        return "值得补联系"
    if missing_contact(prospect):
        return "补联系方式"
    return "加入跟进"


def primary_action_kind(mention: Mention, prospect: Prospect | None) -> str:
    if mention.status == "review":
        return "need_contact"
    if missing_contact(prospect):
        return "need_contact"
    return "qualify"


def missing_contact(prospect: Prospect | None) -> str:
    if prospect is None:
        return "联系方式"
    has_contact = any(
        [
            prospect.wechat,
            prospect.telegram,
            prospect.email,
            prospect.website,
            prospect.contact_note,
        ]
    )
    return "" if has_contact else "联系方式"


def platform_from_source(mention: Mention) -> str:
    source = mention.source_name.lower()
    for key in ("zhihu", "v2ex", "segmentfault", "gitee", "github", "weibo", "douyin"):
        if key in source:
            return key
    return mention.source_kind


def compact_sentence(text: str, limit: int = 180) -> str:
    cleaned = " ".join((text or "").replace("\n", " ").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"
